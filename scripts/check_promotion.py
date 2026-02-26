#!/usr/bin/env python3
"""Promotion validation checks.

Check 0 (check-dev)  : Confirm DEV is in sync with MDF  — run *before* promotion.
Check 1 (check-qa)   : Confirm QA received all promoted models — run *after* promotion.
Check 2 (check-sync) : Confirm DEV and QA are in sync — run *after* promotion.

Exit code 0 = all models pass; exit code 1 = one or more models fail.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import click
import yaml
from bento_mdf.mdf import MDF
from bento_meta.mdb import MDB
from prefect.blocks.system import Secret

from bento_mdb.model_cdes import get_yaml_files_from_spec, load_model_specs_from_yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SYNC_STATUS_PATH = _REPO_ROOT / "config/sync_status.yml"
_MDB_MODELS_PATH  = "config/mdb_models.yml"


# ── shared helpers ─────────────────────────────────────────────────────────────

def _connect(mdb_id: str) -> MDB:
    """Return a read-only MDB connection, credentials loaded from Prefect Secrets."""
    uri = Secret.load(f"{mdb_id}-uri").get()
    user = Secret.load(f"{mdb_id}-usr").get()
    password = Secret.load(f"{mdb_id}-pwd").get()
    if uri.startswith("jdbc:neo4j:"):
        uri = uri.replace("jdbc:neo4j:", "")
    conn = MDB(uri=uri, user=user, password=password)
    if conn.driver is None:
        raise ConnectionError(f"Failed to connect to MDB '{mdb_id}' at {uri}")
    click.echo(f"  Connected: {mdb_id}")
    return conn


def _query_handles(mdb: MDB, model: str, version: str) -> tuple[set, set, set]:
    """Return (node_handles, rel_handles, prop_tuples) for a model version in *mdb*."""
    p = {"model": model, "version": version}

    def _q(cypher: str) -> list:
        try:
            result = mdb.get_with_statement(cypher, p)
            return result if result is not None else []
        except Exception as exc:
            click.echo(f"  [WARN] Query failed: {exc}", err=True)
            return []

    nodes = {r["handle"] for r in _q(
        "MATCH (n:node {model:$model, version:$version}) RETURN n.handle AS handle"
    )}
    rels = {r["handle"] for r in _q(
        "MATCH (r:relationship {model:$model, version:$version}) RETURN r.handle AS handle"
    )}
    props = {(r["prop"], r["node"]) for r in _q(
        "MATCH (n:node {model:$model, version:$version})-[:has_property]->"
        "(p:property {model:$model, version:$version}) "
        "RETURN p.handle AS prop, n.handle AS node"
    )}
    return nodes, rels, props


def _load_mdf_handles(spec: dict, model: str, version: str) -> tuple[set, set, set]:
    """Return (node_handles, rel_handles, prop_tuples) from MDF source files."""
    urls = get_yaml_files_from_spec(spec, model, version)
    mdf = MDF(*urls, handle=model, raise_error=True, ignore_enum_by_reference=True)
    m = mdf.model
    nodes = set(m.nodes.keys())
    rels = {k[0] for k in m.edges.keys()}
    # model.props keys are (node_handle, prop_handle); swap to match MDB (prop, node)
    props = {(k[1], k[0]) for k in m.props.keys()}
    return nodes, rels, props


def _print_diff(label: str, a_set: set, b_set: set, a_lbl: str, b_lbl: str) -> int:
    """Print NEW/REMOVED diff for one entity type; return total number of diffs."""
    new = sorted(a_set - b_set)
    removed = sorted(b_set - a_set)
    click.echo(
        f"\n[{label}]"
        f"  {a_lbl}={len(a_set)}"
        f"  {b_lbl}={len(b_set)}"
        f"  same={len(a_set & b_set)}"
        f"  NEW={len(new)}"
        f"  REMOVED={len(removed)}"
    )
    for h in new:
        click.echo(f"    <- NEW      {h}")
    for h in removed:
        click.echo(f"    -> REMOVED  {h}")
    return len(new) + len(removed)


def _load_specs(config: str | None, models_filter: tuple[str, ...]) -> dict:
    config_path = (
        Path(config) if config
        else Path(__file__).resolve().parent.parent / "config/mdb_models.yml"
    )
    all_specs = load_model_specs_from_yaml(config_path)
    return {
        k: v for k, v in all_specs.items()
        if not models_filter or k in models_filter
    }


def _read_last_promoted_sha() -> str | None:
    """Return the SHA stored in config/sync_status.yml under promotion.last_promoted_sha."""
    try:
        with _SYNC_STATUS_PATH.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("promotion", {}).get("last_promoted_sha")
    except Exception:
        return None


def _find_updated_models(since: str) -> list[str]:
    """Return model handles whose latest_version changed between *since* and HEAD.

    Parses the git diff of config/mdb_models.yml.  Only lines that change
    ``latest_version:`` (not ``latest_prerelease_version:``) are considered.
    The model name is taken from the nearest preceding ``@@ ... @@ MODELNAME:``
    hunk header.
    """
    result = subprocess.run(
        ["git", "diff", f"{since}..HEAD", "--", _MDB_MODELS_PATH],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    updated: list[str] = []
    current_model: str | None = None
    for line in result.stdout.splitlines():
        hunk = re.match(r"^@@.*@@\s+(\w+):", line)
        if hunk:
            current_model = hunk.group(1)
        elif (
            re.match(r"^\+\s+latest_version:", line)
            and "prerelease" not in line
            and current_model
            and current_model not in updated
        ):
            updated.append(current_model)
    return updated


@dataclass
class _DiffResult:
    model: str
    version: str
    inserts: int
    removals: int

    @property
    def passed(self) -> bool:
        return self.inserts == 0 and self.removals == 0


def _print_summary(results: list[_DiffResult]) -> None:
    """Print a per-model results table and an overall pass/fail line."""
    click.echo(f"\n{'─'*60}")
    click.echo("Results Summary")
    click.echo(f"{'─'*60}")
    width = max((len(r.model) for r in results), default=5)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        click.echo(
            f"  {status}  {r.model:<{width}}  v{r.version:<12}"
            f"  inserts={r.inserts}  removals={r.removals}"
        )
    passed = sum(1 for r in results if r.passed)
    total  = len(results)
    click.echo(f"{'─'*60}")
    if passed == total:
        click.echo(f"  {total}/{total} models PASSED")
    else:
        click.echo(f"  {passed}/{total} PASSED  |  {total - passed}/{total} FAILED")


# ── CLI ────────────────────────────────────────────────────────────────────────

@click.group()
def main() -> None:
    """MDB promotion validation checks."""


_config_opt = click.option(
    "--config", default=None, metavar="PATH",
    help="Path to mdb_models.yml. Defaults to config/mdb_models.yml.",
)
_filter_opt = click.option(
    "--models-filter", multiple=True, metavar="MODEL",
    help="Restrict to specific model handles (repeatable). Defaults to all.",
)


@main.command("detect-updated")
@click.option(
    "--since", default=None, metavar="SHA",
    help=(
        "Git ref/SHA to compare against HEAD. "
        "Defaults to promotion.last_promoted_sha in config/sync_status.yml."
    ),
)
@click.option(
    "--format", "output_format",
    type=click.Choice(["lines", "space"]),
    default="lines", show_default=True,
    help="Output format: one model per line, or space-separated on one line.",
)
def detect_updated(since: str | None, output_format: str) -> None:
    """Detect model handles whose latest_version changed since the last promotion."""
    ref = since or _read_last_promoted_sha()
    if not ref:
        click.echo(
            "ERROR: no --since provided and promotion.last_promoted_sha not set "
            "in config/sync_status.yml.",
            err=True,
        )
        sys.exit(1)

    updated = _find_updated_models(ref)
    if not updated:
        click.echo(f"No models with updated latest_version detected since {ref}.", err=True)
        return

    click.echo(f"Updated models since {ref}: {updated}", err=True)
    if output_format == "space":
        click.echo(" ".join(updated))
    else:
        for m in updated:
            click.echo(m)


@main.command("check-dev")
@click.option(
    "--mdb-id", default="cloud-one-mdb-dev", show_default=True,
    help="DEV MDB identifier used to load Prefect secrets.",
)
@_filter_opt
@_config_opt
def check_dev(mdb_id: str, models_filter: tuple[str, ...], config: str | None) -> None:
    """Check 0 — Confirm DEV is in sync with MDF before promotion starts."""
    specs = _load_specs(config, models_filter)

    click.echo(f"\n{'='*60}")
    click.echo("Check 0 — MDF vs MDB-DEV  (pre-promotion validation)")
    click.echo(f"{'='*60}\n")

    mdb = _connect(mdb_id)
    overall_pass = True

    for model, spec in specs.items():
        version = spec["latest_version"]
        mdb_version = version.lstrip("v")
        click.echo(f"\n--- {model} v{mdb_version} ---")

        mdf_nodes, mdf_rels, mdf_props = _load_mdf_handles(spec, model, version)
        mdb_nodes, mdb_rels, mdb_props = _query_handles(mdb, model, mdb_version)

        click.echo(f"\n=== Check 0: {model} v{mdb_version} (MDF vs MDB-DEV) ===")
        _print_diff("NODES",         mdf_nodes, mdb_nodes, "MDF", "MDB-DEV")
        _print_diff("RELATIONSHIPS", mdf_rels,  mdb_rels,  "MDF", "MDB-DEV")
        _print_diff("PROPERTIES",    mdf_props, mdb_props, "MDF", "MDB-DEV")

        inserts  = (len(mdf_nodes - mdb_nodes) + len(mdf_rels - mdb_rels)
                    + len(mdf_props - mdb_props))
        removals = (len(mdb_nodes - mdf_nodes) + len(mdb_rels - mdf_rels)
                    + len(mdb_props - mdf_props))
        click.echo(f"\n  Expected inserts  : {inserts}")
        click.echo(f"  Expected removals : {removals}")

        if inserts == 0 and removals == 0:
            click.echo(f"\n  PASS — {model}: DEV is fully in sync with MDF.")
        else:
            click.echo(f"\n  FAIL — {model}: DEV is NOT in sync with MDF. Resolve before promoting.")
            overall_pass = False

    if not overall_pass:
        sys.exit(1)
    click.echo("\nCheck 0 PASSED — all models in DEV are in sync with MDF.")


@main.command("check-qa")
@click.option(
    "--mdb-id", default="cloud-one-mdb-qa", show_default=True,
    help="QA MDB identifier used to load Prefect secrets.",
)
@_filter_opt
@_config_opt
def check_qa(mdb_id: str, models_filter: tuple[str, ...], config: str | None) -> None:
    """Check 1 — Confirm QA received all promoted models (run after promotion)."""
    specs = _load_specs(config, models_filter)

    click.echo(f"\n{'='*60}")
    click.echo("Check 1 — MDF vs MDB-QA  (post-promotion validation)")
    click.echo(f"{'='*60}\n")

    mdb = _connect(mdb_id)
    overall_pass = True

    for model, spec in specs.items():
        version = spec["latest_version"]
        mdb_version = version.lstrip("v")
        click.echo(f"\n--- {model} v{mdb_version} ---")

        mdf_nodes, mdf_rels, mdf_props = _load_mdf_handles(spec, model, version)
        qa_nodes,  qa_rels,  qa_props  = _query_handles(mdb, model, mdb_version)

        click.echo(f"\n=== Check 1: {model} v{mdb_version} (MDF vs MDB-QA) ===")
        _print_diff("NODES",         mdf_nodes, qa_nodes, "MDF", "MDB-QA")
        _print_diff("RELATIONSHIPS", mdf_rels,  qa_rels,  "MDF", "MDB-QA")
        _print_diff("PROPERTIES",    mdf_props, qa_props, "MDF", "MDB-QA")

        inserts  = (len(mdf_nodes - qa_nodes) + len(mdf_rels - qa_rels)
                    + len(mdf_props - qa_props))
        removals = (len(qa_nodes - mdf_nodes) + len(qa_rels - mdf_rels)
                    + len(qa_props - mdf_props))
        click.echo(f"\n  Expected inserts  : {inserts}")
        click.echo(f"  Expected removals : {removals}")

        if inserts == 0 and removals == 0:
            click.echo(f"\n  PASS — {model}: Promotion completed; QA is fully in sync with MDF.")
        else:
            click.echo(f"\n  FAIL — {model}: QA is NOT fully in sync with MDF.")
            overall_pass = False

    if not overall_pass:
        sys.exit(1)
    click.echo("\nCheck 1 PASSED — all models on QA are in sync with MDF.")


@main.command("check-sync")
@click.option(
    "--dev-mdb-id", default="cloud-one-mdb-dev", show_default=True,
    help="DEV MDB identifier.",
)
@click.option(
    "--qa-mdb-id", default="cloud-one-mdb-qa", show_default=True,
    help="QA MDB identifier.",
)
@_filter_opt
@_config_opt
def check_sync(
    dev_mdb_id: str,
    qa_mdb_id: str,
    models_filter: tuple[str, ...],
    config: str | None,
) -> None:
    """Check 2 — Confirm DEV and QA are in sync (run after promotion)."""
    specs = _load_specs(config, models_filter)

    click.echo(f"\n{'='*60}")
    click.echo("Check 2 — MDB-DEV vs MDB-QA  (tier sync validation)")
    click.echo(f"{'='*60}\n")

    mdb_dev = _connect(dev_mdb_id)
    mdb_qa  = _connect(qa_mdb_id)
    overall_pass = True

    for model, spec in specs.items():
        version = spec["latest_version"]
        mdb_version = version.lstrip("v")
        click.echo(f"\n--- {model} v{mdb_version} ---")

        dev_nodes, dev_rels, dev_props = _query_handles(mdb_dev, model, mdb_version)
        qa_nodes,  qa_rels,  qa_props  = _query_handles(mdb_qa,  model, mdb_version)

        click.echo(f"\n=== Check 2: {model} v{mdb_version} (MDB-DEV vs MDB-QA) ===")
        _print_diff("NODES",         dev_nodes, qa_nodes, "DEV", "QA")
        _print_diff("RELATIONSHIPS", dev_rels,  qa_rels,  "DEV", "QA")
        _print_diff("PROPERTIES",    dev_props, qa_props, "DEV", "QA")

        inserts  = (len(dev_nodes - qa_nodes) + len(dev_rels - qa_rels)
                    + len(dev_props - qa_props))
        removals = (len(qa_nodes - dev_nodes) + len(qa_rels - dev_rels)
                    + len(qa_props - dev_props))

        click.echo(f"\n  Expected inserts: {inserts}", nl=False)
        if inserts == 0 and removals == 0:
            click.echo("; DEV and QA are fully in sync.")
            click.echo(f"\n  PASS — {model}: DEV and QA are fully in sync.")
        else:
            click.echo()
            click.echo(f"  Expected removals: {removals}")
            click.echo(f"\n  FAIL — {model}: DEV and QA are NOT in sync.")
            overall_pass = False

    if not overall_pass:
        sys.exit(1)
    click.echo("\nCheck 2 PASSED — DEV and QA are fully in sync for all models.")


if __name__ == "__main__":
    main()
