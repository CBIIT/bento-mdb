"""Orchestration script to update MDB and Data Hub sequentially."""

from prefect import flow, get_run_logger
from prefect.deployments import run_deployment


@flow(name="update-mdb-and-dh")
def update_mdb_and_dh_flow(
    changelog_file: str,
    mdb_id: str,
    log_level: str,
    tier: str,
    *,
    dry_run: bool = False,
    no_commit: bool = False,
) -> None:
    """Orchestration script to update MDB and Data Hub sequentially."""
    logger = get_run_logger()
    logger.info("Running update-mdb-and-dh flow...")
    liq_update_deployment = f"liquibase-update/liquibase-update-{tier}"
    run_deployment(
        name=liq_update_deployment,
        parameters={
            "changelog_file": changelog_file,
            "mdb_id": mdb_id,
            "log_level": log_level,
            "dry_run": dry_run,
        },
        timeout=None,
        as_subflow=True,
    )
    run_deployment(
        name="update-datahub/update-datahub",
        parameters={
            "mdb_id": mdb_id,
            "tier": tier,
            "no_commit": no_commit,
        },
        timeout=None,
        as_subflow=True,
    )
