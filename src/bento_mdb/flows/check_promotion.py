"""Promotion validation flow.
Check 0 — Confirm DEV is up to date before promotion starts
Compare MDF source files against MDB(DEV). Run before export (stage="pre").

Check 1 — Confirm QA received all promoted models
Compare MDF vs MDB(QA). After promotion, if Expected inserts: 0, the data
promotion completed successfully and QA is fully in sync with MDF.
Run after import (stage="post").

Check 2 — Check DEV DB and QA DB are in sync
Compare MDB-DEV vs MDB-QA. If Expected inserts: 0, DEV and QA are fully in sync.
Run after import (stage="post").

models_filter is passed from the workflow (YAML detect step). When None,
all models from config/mdb_models.yml are used.

The flow raises ValueError on any failure so Prefect marks the run as FAILED.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from prefect import flow, get_run_logger, task

from bento_mdf.mdf import MDF
from bento_meta.mdb import MDB

from bento_mdb.mdb_utils import init_mdb_connection
from bento_mdb.model_cdes import get_yaml_files_from_spec, load_model_specs_from_yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_MDB_MODELS_PATH = _REPO_ROOT / "config/mdb_models.yml"


# ── shared helpers ─────────────────────────────────────────────────────────────

def _connect(mdb_id: str) -> MDB:
    """Return a validated MDB connection (uses init_mdb_connection, allow_empty for diff-only use)."""
    return init_mdb_connection(mdb_id, allow_empty=True)


def _load_specs(models_filter: list[str] | None) -> dict:
    all_specs = load_model_specs_from_yaml(_MDB_MODELS_PATH)
    if not models_filter:
        return all_specs
    unknown_models = [m for m in models_filter if m not in all_specs]
    if unknown_models:
        raise ValueError(
            "Unknown model(s) requested in models_filter: "
            + ", ".join(sorted(unknown_models))
        )
    return {k: all_specs[k] for k in models_filter}


def _query_handles(mdb: MDB, model: str, version: str) -> tuple[set, set, set]:
    logger = get_run_logger()
    p = {"model": model, "version": version}

    def _q(cypher: str) -> list:
        try:
            result = mdb.get_with_statement(cypher, p)
            return result if result is not None else []
        except Exception as exc:
            logger.exception(
                "Query failed for model=%s version=%s cypher=%r: %s",
                model,
                version,
                cypher,
                exc,
            )
            raise

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


def _log_diff(logger, label: str, a_set: set, b_set: set, a_lbl: str, b_lbl: str) -> None:
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
    """Check 0: Confirm DEV is up to date before promotion — compare MDF source against MDB(DEV)."""
    logger = get_run_logger()
    version = spec["latest_version"]
    mdb_version = version.lstrip("v")
    logger.info("=== Diff: %s v%s (MDF vs MDB-DEV) ===", model, mdb_version)

    mdb = _connect(mdb_id)
    try:
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
        if inserts == 0 and removals == 0:
            logger.info("DEV is up to date with MDF.")
        return _DiffResult(model, mdb_version, inserts, removals)
    finally:
        mdb.close()


@task(name="check-model-qa")
def check_model_qa(model: str, spec: dict, mdb_id: str) -> _DiffResult:
    """Check 1: Confirm QA received all promoted models — compare MDF vs MDB(QA)."""
    logger = get_run_logger()
    version = spec["latest_version"]
    mdb_version = version.lstrip("v")
    logger.info("=== Diff: %s v%s (MDF vs MDB-QA) ===", model, mdb_version)

    mdb = _connect(mdb_id)
    try:
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
        if inserts == 0 and removals == 0:
            logger.info("Expected inserts: 0; the data promotion completed successfully and QA is fully in sync with MDF.")
        return _DiffResult(model, mdb_version, inserts, removals)
    finally:
        mdb.close()


@task(name="check-model-sync")
def check_model_sync(model: str, spec: dict, dev_mdb_id: str, qa_mdb_id: str) -> _DiffResult:
    """Check 2: Check DEV DB and QA DB are in sync — compare MDB-DEV vs MDB-QA."""
    logger = get_run_logger()
    version = spec["latest_version"]
    mdb_version = version.lstrip("v")
    logger.info("=== Diff: %s v%s (MDB-DEV vs MDB-QA) ===", model, mdb_version)

    mdb_dev = _connect(dev_mdb_id)
    mdb_qa  = _connect(qa_mdb_id)
    try:
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
        if inserts == 0 and removals == 0:
            logger.info("Expected inserts: 0; DEV and QA are fully in sync.")
        return _DiffResult(model, mdb_version, inserts, removals)
    finally:
        mdb_dev.close()
        mdb_qa.close()


# ── flow ───────────────────────────────────────────────────────────────────────

@flow(name="check-promotion")
def check_promotion_flow(
    stage: Literal["pre", "post"],
    dev_mdb_id: str = "cloud-one-mdb-dev",
    qa_mdb_id: str = "cloud-one-mdb-qa",
    models_filter: list[str] | None = None,
) -> None:
    """Promotion validation flow.

    Check 0 (stage=pre):  Confirm DEV is up to date — MDF vs MDB(DEV). Run before export.
    Check 1 (stage=post): Confirm QA received all promoted models — MDF vs MDB(QA).
    Check 2 (stage=post): Check DEV and QA are in sync — MDB-DEV vs MDB-QA.

    models_filter is passed from the workflow (detect step in YAML). When None, all models are used.
    """
    logger = get_run_logger()
    specs = _load_specs(models_filter)

    if stage == "pre":
        logger.info("=" * 60)
        logger.info("Check 0 — Confirm DEV is up to date before promotion (MDF vs MDB-DEV)")
        logger.info("=" * 60)

        results = [check_model_dev(model, spec, dev_mdb_id) for model, spec in specs.items()]
        _log_summary(logger, results)

        failed = [r for r in results if not r.passed]
        if failed:
            raise ValueError(
                f"Check 0 FAILED — {len(failed)}/{len(results)} model(s) out of sync with MDF: "
                + ", ".join(r.model for r in failed)
            )
        logger.info("Check 0 PASSED — DEV is up to date with MDF.")

    elif stage == "post":
        logger.info("=" * 60)
        logger.info("Check 1 — Confirm QA received all promoted models (MDF vs MDB-QA)")
        logger.info("=" * 60)

        qa_results = [check_model_qa(model, spec, qa_mdb_id) for model, spec in specs.items()]
        _log_summary(logger, qa_results)

        logger.info("=" * 60)
        logger.info("Check 2 — Check DEV DB and QA DB are in sync (MDB-DEV vs MDB-QA)")
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
        logger.info("Post-promotion checks PASSED — QA received all promoted models and DEV/QA are in sync.")

    else:
        raise ValueError(f"Unknown stage: {stage!r}. Must be 'pre' or 'post'.")
