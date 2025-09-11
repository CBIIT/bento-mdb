"""Orchestration script to update Cloud One Dev and QA MDBs from graphml file."""

from prefect import flow, get_run_logger
from prefect.deployments import run_deployment

from bento_mdb_updates.flows.mdb_s3 import get_current_date


@flow(name="update-c1-lower")
def update_c1_lower_flow(
    key: str,
) -> None:
    """Orchestration script to update Cloud One Dev and QA MDBs from graphml file."""
    logger = get_run_logger()
    logger.info("Running update-c1-lower flow...")
    logger.info("Importing to cloud-one-mdb-dev from fnl-mdb-data bucket")
    run_deployment(
        name="mdb-import-s3/mdb-import-s3",
        parameters={
            "mdb_id": "cloud-one-mdb-dev",
            "bucket": "fnl-mdb-data",
            "key": key,
            "clear_db": True,
        },
        timeout=None,
        as_subflow=True,
    )
    logger.info("Exporting from cloud-one-mdb-dev to cloudone-mdb-data bucket")
    run_deployment(
        name="mdb-export-s3/mdb-export-s3",
        parameters={
            "mdb_id": "cloud-one-mdb-dev",
            "bucket": "cloudone-mdb-data",
        },
        timeout=None,
        as_subflow=True,
    )
    current_date = get_current_date()
    c1_dev_key = f"{current_date}__cloud-one-mdb-dev.graphml"
    logger.info("Importing to cloud-one-mdb-qa from cloudone-mdb-data bucket")
    run_deployment(
        name="mdb-import-s3/mdb-import-s3",
        parameters={
            "mdb_id": "cloud-one-mdb-qa",
            "bucket": "cloudone-mdb-data",
            "key": c1_dev_key,
            "clear_db": True,
        },
        timeout=None,
        as_subflow=True,
    )
    logger.info("Pruning prerelease data from cloud-one-mdb-qa")
    run_deployment(
        name="mdb-prune-prerelease/prune-prerelease",
        parameters={
            "mdb_id": "cloud-one-mdb-qa",
            "dry_run": False,
        },
        timeout=None,
        as_subflow=True,
    )
