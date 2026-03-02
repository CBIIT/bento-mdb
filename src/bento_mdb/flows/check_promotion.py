"""Promotion validation flow.

A single flow triggered at two stages of the data promotion pipeline:

  stage="pre"   Check 0: Confirm DEV is in sync with MDF — run before export.
  stage="post"  Check 1: Confirm QA received all promoted models.
                Check 2: Confirm DEV and QA are in sync.
                (both run after import)

When models_filter is not provided, the flow can compute it from optional
``since`` (git ref) or from config/sync_status.yml (last_promoted_sha,
the SHA of the commit that last changed config/mdb_models.yml).

The flow raises ValueError on any failure so Prefect marks the run as FAILED.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from prefect import flow, get_run_logger, task
from prefect.blocks.system import Secret

from bento_mdf.mdf import MDF
from bento_meta.mdb import MDB

from bento_mdb.model_cdes import get_yaml_files_from_spec, load_model_specs_from_yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MDB_MODELS_PATH = _REPO_ROOT / "config/mdb_models.yml"
_SYNC_STATUS_PATH = _REPO_ROOT / "config/sync_status.yml"


# ── shared helpers ─────────────────────────────────────────────────────────────

def _connect(mdb_id: str) -> MDB:
    uri = Secret.load(f"{mdb_id}-uri").get()
    user = Secret.load(f"{mdb_id}-usr").get()
    password = Secret.load(f"{mdb_id}-pwd").get()
    if uri.startswith("jdbc:neo4j:"):
        uri = uri.replace("jdbc:neo4j:", "")
    conn = MDB(uri=uri, user=user, password=password)
    if conn.driver is None:
        raise ConnectionError(f"Failed to connect to MDB '{mdb_id}' at {uri}")
    return conn


def _load_specs(models_filter: list[str] | None) -> dict:
    all_specs = load_model_specs_from_yaml(_MDB_MODELS_PATH)
    if not models_filter:
        return all_specs
    return {k: v for k, v in all_specs.items() if k in models_filter}


def read_last_promoted_sha() -> str | None:
    """Return the SHA in config/sync_status.yml under promotion.last_promoted_sha.

    The workflow sets this to the SHA of the commit that last changed
    config/mdb_models.yml (after each successful promotion).
    """
    try:
        with _SYNC_STATUS_PATH.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("promotion", {}).get("last_promoted_sha")
    except Exception:
        return None


def find_updated_models(since: str) -> list[str]:
    """Return model handles whose latest_version changed between *since* and HEAD.

    Parses the git diff of config/mdb_models.yml. Only lines that change
    ``latest_version:`` (not ``latest_prerelease_version:``) are considered.
    """
    result = subprocess.run(
        ["git", "diff", f"{since}..HEAD", "--", str(_MDB_MODELS_PATH)],
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


def get_updated_models(since: str | None = None) -> list[str]:
    """Return model handles with updated latest_version since the given ref.

    If *since* is None, uses promotion.last_promoted_sha from config/sync_status.yml
    (the SHA of the commit that last changed mdb_models.yml).
    Returns empty list if no ref is available or no updates found.
    """
    ref = since or read_last_promoted_sha()
    if not ref:
        return []
    return find_updated_models(ref)


def _query_handles(mdb: MDB, model: str, version: str) -> tuple[set, set, set]:
    logger = get_run_logger()
    p = {"model": model, "version": version}

    def _q(cypher: str) -> list:
        try:
            result = mdb.get_with_statement(cypher, p)
            return result if result is not None else []
        except Exception as exc:
            logger.warning("Query failed: %s", exc)
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
    urls = get_yaml_files_from_spec(spec, model, version)
    mdf = MDF(*urls, handle=model, raise_error=True, ignore_enum_by_reference=True)
    m = mdf.model
    nodes = set(m.nodes.keys())
    rels = {k[0] for k in m.edges.keys()}
    props = {(k[1], k[0]) for k in m.props.keys()}
    return nodes, rels, props


def _log_diff(logger, label: str, a_set: set, b_set: set, a_lbl: str, b_lbl: str) -> int:
    new     = sorted(a_set - b_set)
    removed = sorted(b_set - a_set)
    logger.info(
        "[%s]  %s=%d  %s=%d  same=%d  NEW=%d  REMOVED=%d",
        label, a_lbl, len(a_set), b_lbl, len(b_set),
        len(a_set & b_set), len(new), len(removed),
    )
    for h in new:
        logger.info("  <- NEW      %s", h)
    for h in removed:
        logger.info("  -> REMOVED  %s", h)
    return len(new) + len(removed)


@dataclass
class _DiffResult:
    model: str
    version: str
    inserts: int
    removals: int

    @property
    def passed(self) -> bool:
        return self.inserts == 0 and self.removals == 0


def _log_summary(logger, results: list[_DiffResult]) -> None:
    logger.info("─" * 60)
    logger.info("Results Summary")
    logger.info("─" * 60)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        logger.info("  %s  %-15s  v%-12s  inserts=%d  removals=%d",
                    status, r.model, r.version, r.inserts, r.removals)
    passed = sum(1 for r in results if r.passed)
    total  = len(results)
    logger.info("─" * 60)
    if passed == total:
        logger.info("  %d/%d models PASSED", total, total)
    else:
        logger.info("  %d/%d PASSED  |  %d/%d FAILED", passed, total, total - passed, total)


# ── tasks ──────────────────────────────────────────────────────────────────────

@task(name="check-model-dev")
def check_model_dev(model: str, spec: dict, mdb_id: str) -> _DiffResult:
    """Check 0: Compare MDF source against MDB-DEV for one model."""
    logger = get_run_logger()
    version = spec["latest_version"]
    mdb_version = version.lstrip("v")
    logger.info("=== Check 0: %s v%s (MDF vs MDB-DEV) ===", model, mdb_version)

    mdb = _connect(mdb_id)
    mdf_nodes, mdf_rels, mdf_props = _load_mdf_handles(spec, model, version)
    mdb_nodes, mdb_rels, mdb_props = _query_handles(mdb, model, mdb_version)

    _log_diff(logger, "NODES",         mdf_nodes, mdb_nodes, "MDF", "MDB-DEV")
    _log_diff(logger, "RELATIONSHIPS", mdf_rels,  mdb_rels,  "MDF", "MDB-DEV")
    _log_diff(logger, "PROPERTIES",    mdf_props, mdb_props, "MDF", "MDB-DEV")

    inserts  = (len(mdf_nodes - mdb_nodes) + len(mdf_rels - mdb_rels)
                + len(mdf_props - mdb_props))
    removals = (len(mdb_nodes - mdf_nodes) + len(mdb_rels - mdf_rels)
                + len(mdb_props - mdf_props))
    logger.info("Expected inserts=%d  removals=%d", inserts, removals)
    return _DiffResult(model, mdb_version, inserts, removals)


@task(name="check-model-qa")
def check_model_qa(model: str, spec: dict, mdb_id: str) -> _DiffResult:
    """Check 1: Compare MDF source against MDB-QA for one model."""
    logger = get_run_logger()
    version = spec["latest_version"]
    mdb_version = version.lstrip("v")
    logger.info("=== Check 1: %s v%s (MDF vs MDB-QA) ===", model, mdb_version)

    mdb = _connect(mdb_id)
    mdf_nodes, mdf_rels, mdf_props = _load_mdf_handles(spec, model, version)
    qa_nodes,  qa_rels,  qa_props  = _query_handles(mdb, model, mdb_version)

    _log_diff(logger, "NODES",         mdf_nodes, qa_nodes, "MDF", "MDB-QA")
    _log_diff(logger, "RELATIONSHIPS", mdf_rels,  qa_rels,  "MDF", "MDB-QA")
    _log_diff(logger, "PROPERTIES",    mdf_props, qa_props, "MDF", "MDB-QA")

    inserts  = (len(mdf_nodes - qa_nodes) + len(mdf_rels - qa_rels)
                + len(mdf_props - qa_props))
    removals = (len(qa_nodes - mdf_nodes) + len(qa_rels - mdf_rels)
                + len(qa_props - mdf_props))
    logger.info("Expected inserts=%d  removals=%d", inserts, removals)
    return _DiffResult(model, mdb_version, inserts, removals)


@task(name="check-model-sync")
def check_model_sync(model: str, spec: dict, dev_mdb_id: str, qa_mdb_id: str) -> _DiffResult:
    """Check 2: Compare MDB-DEV against MDB-QA for one model."""
    logger = get_run_logger()
    version = spec["latest_version"]
    mdb_version = version.lstrip("v")
    logger.info("=== Check 2: %s v%s (MDB-DEV vs MDB-QA) ===", model, mdb_version)

    mdb_dev = _connect(dev_mdb_id)
    mdb_qa  = _connect(qa_mdb_id)
    dev_nodes, dev_rels, dev_props = _query_handles(mdb_dev, model, mdb_version)
    qa_nodes,  qa_rels,  qa_props  = _query_handles(mdb_qa,  model, mdb_version)

    _log_diff(logger, "NODES",         dev_nodes, qa_nodes, "DEV", "QA")
    _log_diff(logger, "RELATIONSHIPS", dev_rels,  qa_rels,  "DEV", "QA")
    _log_diff(logger, "PROPERTIES",    dev_props, qa_props, "DEV", "QA")

    inserts  = (len(dev_nodes - qa_nodes) + len(dev_rels - qa_rels)
                + len(dev_props - qa_props))
    removals = (len(qa_nodes - dev_nodes) + len(qa_rels - dev_rels)
                + len(qa_props - dev_props))
    logger.info("Expected inserts=%d  removals=%d", inserts, removals)
    return _DiffResult(model, mdb_version, inserts, removals)


# ── flow ───────────────────────────────────────────────────────────────────────

@flow(name="check-promotion")
def check_promotion_flow(
    stage: Literal["pre", "post"],
    dev_mdb_id: str = "cloud-one-mdb-dev",
    qa_mdb_id: str = "cloud-one-mdb-qa",
    models_filter: list[str] | None = None,
    since: str | None = None,
) -> None:
    """Promotion validation flow.

    stage="pre"  — Check 0: MDF vs MDB-DEV (run before export).
    stage="post" — Check 1: MDF vs MDB-QA, Check 2: MDB-DEV vs MDB-QA (run after import).

    When models_filter is None, it is computed from *since* or from
    config/sync_status.yml (last_promoted_sha) via get_updated_models().
    """
    logger = get_run_logger()
    if models_filter is None and (since or read_last_promoted_sha()):
        models_filter = get_updated_models(since)
    specs = _load_specs(models_filter)

    if stage == "pre":
        logger.info("=" * 60)
        logger.info("Check 0 — MDF vs MDB-DEV  (pre-promotion validation)")
        logger.info("=" * 60)

        results = [check_model_dev(model, spec, dev_mdb_id) for model, spec in specs.items()]
        _log_summary(logger, results)

        failed = [r for r in results if not r.passed]
        if failed:
            raise ValueError(
                f"Check 0 FAILED — {len(failed)}/{len(results)} model(s) out of sync with MDF: "
                + ", ".join(r.model for r in failed)
            )
        logger.info("Check 0 PASSED — all models in DEV are in sync with MDF.")

    elif stage == "post":
        logger.info("=" * 60)
        logger.info("Check 1 — MDF vs MDB-QA  (post-promotion validation)")
        logger.info("=" * 60)

        qa_results = [check_model_qa(model, spec, qa_mdb_id) for model, spec in specs.items()]
        _log_summary(logger, qa_results)

        logger.info("=" * 60)
        logger.info("Check 2 — MDB-DEV vs MDB-QA  (tier sync validation)")
        logger.info("=" * 60)

        sync_results = [
            check_model_sync(model, spec, dev_mdb_id, qa_mdb_id)
            for model, spec in specs.items()
        ]
        _log_summary(logger, sync_results)

        failed = [r for r in qa_results + sync_results if not r.passed]
        if failed:
            raise ValueError(
                f"Post-promotion checks FAILED — {len(failed)} check(s) did not pass: "
                + ", ".join(f"{r.model}(v{r.version})" for r in failed)
            )
        logger.info("Post-promotion checks PASSED — QA is fully in sync with MDF and DEV.")

    else:
        raise ValueError(f"Unknown stage: {stage!r}. Must be 'pre' or 'post'.")
