#!/usr/bin/env python3
"""
Script to take one MDF file representing a model and produce a Liquibase Changelog.

This contains the necessary cypher statements to add the model to an MDB.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
from bento_mdf.mdf import MDF

from bento_mdb_updates.model_cypher import ModelToChangelogConverter

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "-m",
    "--model_handle",
    required=True,
    type=str,
    prompt=True,
    help="CRDC Model Handle (e.g. 'GDC')",
)
@click.option(
    "-f",
    "--mdf_files",
    required=True,
    type=str,
    prompt=True,
    multiple=True,
    help="path or URL to MDF YAML file(s)",
)
@click.option(
    "-o",
    "--output_file_path",
    required=False,
    type=click.Path(),
    prompt=False,
    help="File path for output changelog",
)
@click.option(
    "-a",
    "--author",
    required=True,
    type=str,
    help="Author for changeset",
)
@click.option(
    "-c",
    "--_commit",
    required=False,
    type=str,
    help="Commit string",
)
@click.option(
    "-r",
    "--add_rollback",
    required=False,
    type=bool,
    help="Add cypher stmts with rollback to changesets",
)
@click.option(
    "-v",
    "--model_version",
    required=False,
    type=str,
    help="Manually set model version (e.g., 1.2.3) if not included in MDF.",
)
@click.option(
    "-l",
    "--latest_version",
    required=False,
    type=bool,
    help="Is this the latest data model version?",
)
def main(  # noqa: PLR0913
    model_handle: str,
    mdf_files: str | list[str],
    output_file_path: str | Path,
    author: str,
    _commit: str | None,
    model_version: str | None,
    *,
    add_rollback: bool,
    latest_version: bool,
) -> None:
    """Get liquibase changelog from mdf files for a model."""
    logger.info("Script started")

    mdf = MDF(*mdf_files, handle=model_handle, _commit=_commit, raise_error=True)
    if not mdf.model:
        msg = "Error getting model from MDF"
        raise RuntimeError(msg)
    logger.info("Model MDF loaded successfully")

    converter = ModelToChangelogConverter(
        model=mdf.model,
        add_rollback=add_rollback,
    )
    changelog = converter.convert_model_to_changelog(
        author,
        model_version,
        latest_version=latest_version,
    )
    logger.info("Changelog converted from MDF successfully")

    if not output_file_path:
        output_dir = Path().cwd() / f"data/output/model_changelogs/{model_handle}"
        output_file_path = output_dir / f"{model_handle}_changelog_{model_version}.xml"

    changelog.save_to_file(str(Path(output_file_path)), encoding="UTF-8")
    logger.info("Changelog saved at: {output_file_path}")


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
