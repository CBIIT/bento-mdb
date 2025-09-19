"""Orchestration script to update Cloud One Stage and Prod MDBs from graphml file."""

from prefect import flow, get_run_logger
from prefect.deployments import run_deployment

from bento_mdb.flows.mdb_s3 import get_current_date


@flow(name="update-c1-upper")
def update_c1_upper_flow(
    key: str,
) -> None:
    """Orchestration script to update Cloud One Stage and Prod MDBs from graphml file."""
    logger = get_run_logger()
    logger.info("Running update-c1-upper flow...")
    logger.info("Importing to cloud-one-mdb-stage from cloudone-mdb-data bucket")
    run_deployment(
        name="mdb-import-s3/mdb-import-s3",
        parameters={
            "mdb_id": "cloud-one-mdb-stage",
            "bucket": "cloudone-mdb-data",
            "key": key,
            "clear_db": True,
        },
        timeout=None,
        as_subflow=True,
    )
    logger.info("Pruning prerelease data from cloud-one-mdb-stage")
    run_deployment(
        name="mdb-prune-prerelease/prune-prerelease",
        parameters={
            "mdb_id": "cloud-one-mdb-stage",
            "dry_run": False,
        },
        timeout=None,
        as_subflow=True,
    )
    logger.info("Exporting from cloud-one-mdb-stage to cloudone-mdb-data bucket")
    run_deployment(
        name="mdb-export-s3/mdb-export-s3",
        parameters={
            "mdb_id": "cloud-one-mdb-stage",
            "bucket": "cloudone-mdb-data",
        },
        timeout=None,
        as_subflow=True,
    )
    current_date = get_current_date()
    c1_stage_key = f"{current_date}__cloud-one-mdb-stage.graphml"
    logger.info("Importing to cloud-one-mdb-prod from cloudone-mdb-data bucket")
    run_deployment(
        name="mdb-import-s3/mdb-import-s3",
        parameters={
            "mdb_id": "cloud-one-mdb-prod",
            "bucket": "cloudone-mdb-data",
            "key": c1_stage_key,
            "clear_db": True,
        },
        timeout=None,
        as_subflow=True,
    )
