#!/usr/bin/env python3
"""Check bento-edps for new EDP versions and update EDP config."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import yaml
from packaging.version import parse as parse_version

from bento_mdb.clients import GitHubClient
from bento_mdb.model_cdes import dump_to_yaml

logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_edp_specs(edp_props_file: Path) -> dict[str, dict]:
    data = load_yaml(edp_props_file)
    return data.get("PropDefinitions") or {}


def get_edp_version(edp_specs: dict[str, dict], prop_definition: str) -> str | None:
    spec = edp_specs.get(prop_definition)
    if not spec:
        logger.warning("No EDP PropDefinition found for %s", prop_definition)
        return None

    term = spec.get("Term") or {}
    version = term.get("Version")
    return str(version) if version is not None else None


def update_edp_versions(
    edp_config: dict,
    edp_repo_path: Path,
    *,
    new_only: bool = True,
) -> bool:
    updated = False

    for edp_name, spec in edp_config.items():
        logger.info("Checking %s for new EDP version...", edp_name)

        mdf_directory = spec.get("mdf_directory", "model-desc")
        edp_props_file = edp_repo_path / mdf_directory / "edp-props.yml"
        edp_specs = load_edp_specs(edp_props_file)

        prop_definition = spec.get("prop_definition")
        if not prop_definition:
            logger.warning("No prop_definition specified for %s", edp_name)
            continue

        found_version = get_edp_version(edp_specs, prop_definition)
        if not found_version:
            logger.warning("No Version found for %s", edp_name)
            continue

        versions = spec.setdefault("versions", [])
        known_versions = {str(v.get("version")) for v in versions}

        current_latest = str(spec.get("latest_version") or "0.0.0")
        if new_only and parse_version(found_version) <= parse_version(current_latest):
            logger.info(
                "Skipping %s v%s, not newer than latest version %s",
                edp_name,
                found_version,
                current_latest,
            )
            continue

        if found_version not in known_versions:
            logger.info("Adding EDP version %s for %s", found_version, edp_name)
            versions.append({"version": found_version, "tag": found_version})
            updated = True

        sorted_versions = sorted(
            versions,
            key=lambda x: parse_version(str(x["version"])),
        )
        spec["versions"] = sorted_versions
        spec["latest_version"] = str(sorted_versions[-1]["version"])

    return updated


@click.command()
@click.option(
    "--edp_specs_yaml",
    default="config/mdb_edps.yml",
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
    help="Path to EDP version-tracking YAML.",
)
@click.option(
    "--edp_repo_path",
    default="edp-repo",
    type=click.Path(exists=True, dir_okay=True, file_okay=False),
    help="Path to checked-out bento-edps repository.",
)
@click.option(
    "--new_only",
    type=bool,
    default=True,
    show_default=True,
    help="Only update when the EDP version is newer than latest_version.",
)
@click.option(
    "--no_commit",
    type=bool,
    default=False,
    show_default=True,
    help="Don't commit changes.",
)
def main(
    edp_specs_yaml: str,
    edp_repo_path: str,
    *,
    new_only: bool = True,
    no_commit: bool = False,
) -> None:
    edp_specs_path = Path(edp_specs_yaml)
    edp_config = load_yaml(edp_specs_path)

    updated = update_edp_versions(
        edp_config,
        Path(edp_repo_path),
        new_only=new_only,
    )

    if not updated:
        logger.info("No new EDP versions found. Exiting.")
        return

    logger.info("EDP versions updated. Saving changes...")
    dump_to_yaml(edp_config, edp_specs_path)

    if not no_commit:
        logger.info("Committing changes...")
        GitHubClient().commit_and_push_changes(edp_specs_path)


if __name__ == "__main__":
    main()