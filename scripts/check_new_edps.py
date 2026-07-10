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
from bento_mdf import MDF
from bento_meta.model import Model

logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_edp_model(edp_repo_path: Path, spec: dict) -> Model:
    """Load EDP definitions using bento-mdf."""
    mdf_directory = spec.get("mdf_directory", "model-desc")
    mdf_files = spec.get("mdf_files") or ["edp-props.yml"]

    files = [edp_repo_path / mdf_directory / file_name for file_name in mdf_files]
    mdf = MDF(*files, handle="_EDP", raise_error=True)

    return mdf.model


def get_edp_version(edp_definitions: dict, prop_definition: str) -> str | None:
    """Get an EDP version from parsed bento-mdf EDP definitions."""
    prop = edp_definitions.get(prop_definition)
    if not prop:
        logger.warning("No EDP PropDefinition found for %s", prop_definition)
        return None

    if not prop.concept or not prop.concept.terms:
        logger.warning("No EDP Term found for %s", prop_definition)
        return None

    edp_term = next(iter(prop.concept.terms.values()))
    version = getattr(edp_term, "origin_version", None)

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

        edp_model = load_edp_model(edp_repo_path, spec)

        try:
           edp  = edp_model.nodes['_edp'].props[spec['property']]
        except KeyError:
            logger.error("No property '%s' defined for %s in config",
                          spec['property'], edp_name)
            continue

        if not edp.is_extended:
            logger.error("Property '%s' is not an extended property for %s in config",
                          spec['property'], edp_name)
            continue
        
        found_version = list(edp.value_set.edp_terms.values())[0].origin_version
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
