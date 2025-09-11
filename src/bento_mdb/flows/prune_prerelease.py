"""Prune prerelease data from MDB."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE

from bento_mdb_updates.mdb_utils import init_mdb_connection

if TYPE_CHECKING:
    from bento_meta.mdb.writeable import WriteableMDB

DEFAULT_S3_ENDPOINT = "s3.us-east-1.amazonaws.com"

PRUNE_PRERELEASE_DRY_RUN_STMT = (
    "MATCH (n) "
    "WHERE n.version IS NOT NULL "
    "AND n.version =~ '.*-[a-f0-9]{7}$' "
    "RETURN count(n) as prerelease_nodes_to_delete, "
    "collect(DISTINCT labels(n)) as node_types, "
    "collect(n.version)[0..10] as sample_versions"
)

PRUNE_PRERELEASE_STMT = (
    "CALL apoc.periodic.iterate("
    "'MATCH (n) WHERE n.version IS NOT NULL "
    'AND n.version =~ ".*-[a-f0-9]{7}$" RETURN n\', '
    "'DETACH DELETE n', "
    "{batchSize: 1000, parallel: false}) "
    "YIELD batches, total, timeTaken, committedOperations "
    "RETURN batches, total, timeTaken, committedOperations"
)


def get_current_date() -> str:
    """Get current date in YYYYMMDD format."""
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")


@task(name="Prune prerelease data from MDB", cache_policy=NO_CACHE)
def prune_prerelease_data(mdb: WriteableMDB, *, dry_run: bool = True) -> None:
    """Prune prerelease data from MDB."""
    logger = get_run_logger()

    logger.info("Running dry run to check prerelease nodes...")
    dry_run_result = mdb.put_with_statement(PRUNE_PRERELEASE_DRY_RUN_STMT)
    if dry_run_result:
        logger.info("Dry run result: %s", dry_run_result)
    else:
        logger.warning("Dry run returned no results")

    if not dry_run:
        logger.info("Executing batch deletion of prerelease data from MDB")
        result = mdb.put_with_statement(PRUNE_PRERELEASE_STMT)
        if result:
            logger.info("Batch deletion result: %s", result)
            return
        deletion_fail_msg = "Batch deletion failed - no results returned"
        raise RuntimeError(deletion_fail_msg)
    logger.info("Dry run complete. Set dry_run=False to execute actual deletion.")


@flow(name="mdb-prune-prerelease")
def prune_prerelease_flow(
    mdb_id: str,
    *,
    dry_run: bool = True,
) -> None:
    """Prune prerelease data from MDB."""
    mdb = init_mdb_connection(mdb_id, writeable=True)
    prune_prerelease_data(mdb, dry_run=dry_run)
