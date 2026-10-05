"""Check bento-edps for new EDP versions and update EDP config."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import yaml
from packaging.version import parse as parse_version

from bento_mdb.clients import GitHubClient
from bento_mdb.model_cdes import dump_to_yaml
from scripts.edp_packages import load_all_edp_packages

logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _find_config_entry(
    edp_config: dict,
    origin: str,
    code: str,
) -> tuple[str, dict] | None:
    for name, spec in edp_config.items():
        if (
            str(spec.get("origin") or "") == origin
            and str(spec.get("code") or "") == code
        ):
            return name, spec

    return None


def _new_config_key(edp_config: dict, property_handle: str) -> str:
    if property_handle not in edp_config:
        return property_handle

    suffix = 2
    while f"{property_handle}_{suffix}" in edp_config:
        suffix += 1

    return f"{property_handle}_{suffix}"

def update_edp_versions(
    edp_config: dict,
    edp_repo_path: Path,
    *,
    new_only: bool = True,
) -> bool:
    updated = False
    model_directory = Path(edp_repo_path) / "model-desc"
    edp_root = model_directory / "edps"

    for parsed in load_all_edp_packages(edp_root):
        term = parsed.edp_term

        origin = str(term.origin_name)
        code = str(term.origin_id)
        version = str(term.origin_version)
        property_handle = parsed.property_handle
        package = parsed.package.directory.relative_to(model_directory)
        source_hash = parsed.package.source_hash()

        existing = _find_config_entry(edp_config, origin, code)

        if existing is None:
            config_name = _new_config_key(
                edp_config,
                property_handle,
            )
            edp_config[config_name] = {
                "repository": "CBIIT/bento-edps",
                "mdf_directory": "model-desc",
                "package": package.as_posix(),
                "latest_version": version,
                "versions": [
                    {
                        "version": version,
                        "tag": version,
                    }
                ],
                "origin": origin,
                "code": code,
                "property": property_handle,
                "source_hash": source_hash,
            }
            updated = True
            continue

        _, spec = existing
        current_latest = str(
            spec.get("latest_version") or "0.0.0"
        )

        if (
            new_only
            and parse_version(version) < parse_version(current_latest)
        ):
            logger.warning(
                "Skipping %s v%s because latest is %s",
                property_handle,
                version,
                current_latest,
            )
            continue

        expected = {
            "repository": "CBIIT/bento-edps",
            "mdf_directory": "model-desc",
            "package": package.as_posix(),
            "origin": origin,
            "code": code,
            "property": property_handle,
            "source_hash": source_hash,
        }

        for field, value in expected.items():
            if spec.get(field) != value:
                spec[field] = value
                updated = True

        versions = spec.setdefault("versions", [])
        known_versions = {
            str(item.get("version"))
            for item in versions
        }

        if version not in known_versions:
            versions.append(
                {
                    "version": version,
                    "tag": version,
                }
            )
            updated = True

        versions.sort(
            key=lambda item: parse_version(
                str(item["version"])
            )
        )

        newest = str(versions[-1]["version"])
        if str(spec.get("latest_version")) != newest:
            spec["latest_version"] = newest
            updated = True

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
