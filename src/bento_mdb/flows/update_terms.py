"""Check for new caDSR PVs and NCIT mappings and generate Cypher to update MDB."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING

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


def make_changelog_output_more_visible(changelog_file: Path) -> None:
    """
    Make the changelog output more visible in logs.

    Print multiple times with clear markers.
    """
    result_json = json.dumps([str(changelog_file)])
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


@flow(name="update-terms", log_prints=True)
def update_terms(
    mdb_id: str,
    author: str,
    commit: str | None = None,
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

    if changelog.count_changesets() == 0:
        logger.info("No changesets to report")

    # Print changlog file as JSON for GitHub Actions
    make_changelog_output_more_visible(changelog_file)
