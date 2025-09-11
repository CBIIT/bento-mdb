#!/usr/bin/env python3
"""
Renumber changeset ids for all changesets in changelog.

Starts with n and increments by 1. Saves the resulting changelog at the given path.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import click

NAMESPACE = "http://www.liquibase.org/xml/ns/dbchangelog"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
NEO4J_NAMESPACE = "http://www.liquibase.org/xml/ns/dbchangelog-ext"
SCHEMA_LOCATION = f"{NAMESPACE} {NAMESPACE}/dbchangelog-latest.xsd"


def renumber_changelog_id(
    file_path: str | Path,
    starting_id: int | None = 1,
    new_file_path: str | Path | None = None,
) -> None:
    """Load xml changelog & renumber ids for all changesets."""
    id_num = starting_id if starting_id else 1
    if not new_file_path:
        new_file_path = file_path

    tree = ET.parse(file_path)
    root = tree.getroot()

    ET.register_namespace("", NAMESPACE)
    ET.register_namespace("xsi", XSI_NAMESPACE)
    ET.register_namespace("neo4j", NEO4J_NAMESPACE)

    for child in root:
        child.attrib["id"] = str(id_num)
        id_num += 1

    tree.write(
        file_or_filename=new_file_path,
        xml_declaration=True,
        method="xml",
    )

    print(
        f"\nRenumbered changelog ids for {file_path} starting with {starting_id}"
        f" and ending with {id_num - 1}. Next id will be {id_num}",
    )


@click.command()
@click.option(
    "--file_path",
    required=True,
    type=str,
    prompt=True,
    help="Path to changelog file",
)
@click.option(
    "--starting_id",
    required=False,
    type=int,
    prompt=True,
    default=1,
    help="Starting id. Default 1.",
)
@click.option(
    "--new_file_path",
    required=False,
    type=str,
    prompt=True,
    help="Path to new changelog file. Default is the same as the original file.",
)
def main(
    file_path: str,
    starting_id: int | None = 1,
    new_file_path: str | None = None,
) -> None:
    """Renumber changelog ids."""
    renumber_changelog_id(
        file_path=file_path,
        starting_id=starting_id,
        new_file_path=new_file_path,
    )


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameters
