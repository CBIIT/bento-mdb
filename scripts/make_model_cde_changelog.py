#!/usr/bin/env python3
"""Convert cdes yaml to neo4j cypher statements."""

from __future__ import annotations

from pathlib import Path

import click

from bento_mdb_updates.cde_cypher import convert_model_cdes_to_changelog
from bento_mdb_updates.model_cdes import (
    load_model_cde_spec,
)


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
    "-v",
    "--model_version",
    required=False,
    type=str,
    help="Manually set model version (e.g., 1.2.3) if not included in MDF.",
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
def main(
    model_handle: str,
    model_version: str,
    author: str,
    _commit: str | None = None,
) -> None:
    """Convert CDE PVs to Neo4j Cypher statements."""
    model_cdes = load_model_cde_spec(model_handle, model_version)
    changelog = convert_model_cdes_to_changelog(model_cdes, author, _commit)
    output_dir = Path().cwd() / f"data/output/model_changelogs/{model_handle}"
    cde_changelog = output_dir / f"{model_handle}_{model_version}_cde_changelog.xml"
    changelog.save_to_file(str(cde_changelog), encoding="UTF-8")


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameters
