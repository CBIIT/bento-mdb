"""Run configurable read-only MDB consistency checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect import flow, get_run_logger, task

from bento_mdb.consistency import (
    ExpectationResult,
    evaluate_expectation,
    load_checks_from_yaml,
    load_query,
)

from bento_mdb.mdb_utils import execute_read_query, init_mdb_connection


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@task
def load_checks(checks_yaml: str, tags: list[str] | None = None) -> list[dict[str, Any]]:
    return load_checks_from_yaml(checks_yaml, tags, repo_root=_REPO_ROOT)


@task
def run_check(mdb_id: str, check: dict[str, Any]) -> ExpectationResult:
    logger = get_run_logger()
    query = load_query(check, repo_root=_REPO_ROOT)
    params = check.get("params", {})

    logger.info("Running MDB consistency check: %s", check["id"])

    mdb = init_mdb_connection(mdb_id, writeable=False, allow_empty=True)
    try:
        # Consistency checks must be safe against prod; use read-only query execution.
        rows = execute_read_query(mdb, query, params) or []
    finally:
        mdb.close()

    result = evaluate_expectation(check, rows)

    if result.passed:
        logger.info("PASS %s: actual=%r expected=%r", result.check_id, result.actual, result.expected)
    else:
        logger.error("FAIL %s: actual=%r expected=%r rows=%r", result.check_id, result.actual, result.expected, result.rows[:10])

    return result


@flow(name="check-mdb-consistency", log_prints=True)
def check_mdb_consistency_flow(
    mdb_id: str,
    checks_yaml: str = "config/mdb_consistency_queries.yml",
    tags: list[str] | None = None,
) -> None:
    logger = get_run_logger()
    checks = load_checks(checks_yaml, tags)

    if not checks:
        raise ValueError(f"No MDB consistency checks found in {checks_yaml}")

    results = [run_check(mdb_id, check) for check in checks]
    failures = [result for result in results if not result.passed]

    logger.info(
        "MDB consistency summary: %d passed, %d failed",
        len(results) - len(failures),
        len(failures),
    )

    if failures:
        failed_ids = ", ".join(result.check_id for result in failures)
        raise ValueError(f"MDB consistency checks failed: {failed_ids}")
