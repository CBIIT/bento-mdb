"""Check for new caDSR PVs and NCIT mappings and generate Cypher to update MDB."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from prefect import flow, get_run_logger, task

from bento_mdb.cde_cypher import convert_model_cdes_to_changelog
from bento_mdb.clients import CADSRClient, NCItClient
from bento_mdb.mdb_utils import init_mdb_connection
from bento_mdb.model_cdes import (
    add_ncit_synonyms_to_model_cde_spec,
    get_cdes_from_mdb,
)

if TYPE_CHECKING:
    from bento_mdb.datatypes import MDBCDESpec, ModelCDESpec


def make_changelog_output_more_visible(changelog_files: list[str]) -> None:
    """
    Make the changelog output more visible in logs.

    Print multiple times with clear markers.
    """
    result_json = json.dumps(changelog_files)
    print("\n" + "*" * 80)  # noqa: T201
    print("RESULT_JSON_BEGIN")  # noqa: T201
    print(f"RESULT_JSON:{result_json}")  # noqa: T201
    print("RESULT_JSON_END")  # noqa: T201
    print("*" * 80 + "\n")  # noqa: T201
    print(f"RESULT_JSON:{result_json}")  # noqa: T201


@task
def get_current_mdb_cdes(
    mdb_id: str,
) -> list[MDBCDESpec]:
    """Get current MDB CDEs."""
    mdb = init_mdb_connection(mdb_id)
    return get_cdes_from_mdb(mdb)


@task
def update_mdb_cdes_from_term_sources(
    mdb_cdes: list[MDBCDESpec],
) -> ModelCDESpec:
    """Update ModelCDESpec with new CDE PVs and synonyms from caDSR and NCIt."""
    logger = get_run_logger()
    today = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d")
    update_cde_spec: ModelCDESpec = {
        "handle": "TERM_UPDATES",
        "version": today,
        "annotations": [],
    }

    logger.info("Checking caDSR for new PVs...")
    cadsr_client = CADSRClient()
    cadsr_annotations = cadsr_client.check_cdes_against_mdb(mdb_cdes)
    update_cde_spec["annotations"].extend(cadsr_annotations)

    logger.info("Getting NCIt synonyms for new PVs...")
    ncit_client = NCItClient()
    add_ncit_synonyms_to_model_cde_spec(update_cde_spec, ncit_client)

    if ncit_client.check_ncit_for_updated_mappings(force_update=True):
        logger.info("Checking NCIt for new PV synonyms...")
        ncit_annotations = ncit_client.check_synonyms_against_mdb(
            mdb_cdes,
        )
        update_cde_spec["annotations"].extend(ncit_annotations)
    return update_cde_spec


@task
def upload_changelog_to_s3(changelog_file: Path, bucket: str) -> str:
    """Upload a generated term changelog to S3 and return its key."""
    logger = get_run_logger()
    s3_key = f"term_changelogs/{changelog_file.name}"
    logger.info("Uploading %s to s3://%s/%s", changelog_file, bucket, s3_key)
    boto3.client("s3").upload_file(
        str(changelog_file),
        bucket,
        s3_key,
        ExtraArgs={"ContentType": "application/xml"},
    )
    logger.info("Uploaded term changelog to s3://%s/%s", bucket, s3_key)
    return s3_key


@flow(name="update-terms", log_prints=True)
def update_terms(
    mdb_id: str,
    author: str,
    commit: str | None = None,
    s3_bucket: str | None = None,
    *,
    no_commit: bool = False,
) -> None:
    """Check for new CDE PVs and synonyms and generate Cypher to update the database."""
    logger = get_run_logger()
    today = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d")

    mdb_cdes = get_current_mdb_cdes(mdb_id)
    update_cde_spec = update_mdb_cdes_from_term_sources(mdb_cdes)

    # convert annotation updates to liquibase changelog
    changelog = convert_model_cdes_to_changelog(update_cde_spec, author, commit)
    output_dir = Path().cwd() / "data/output/term_changelogs"
    changelog_file = output_dir / f"{mdb_id}_{today}_term_updates.xml"
    changelog_file.parent.mkdir(parents=True, exist_ok=True)
    changelog.save_to_file(str(changelog_file), encoding="UTF-8")

    changelog_files: list[str] = []
    if changelog.count_changesets() == 0:
        logger.info("No changesets to report")
    elif no_commit:
        logger.info("Skipping S3 upload because no_commit is true")
    elif s3_bucket:
        changelog_files.append(upload_changelog_to_s3(changelog_file, s3_bucket))
    else:
        msg = "s3_bucket is required unless no_commit is true"
        raise ValueError(msg)

    # Print changlog file as JSON for GitHub Actions
    make_changelog_output_more_visible(changelog_files)
