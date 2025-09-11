#!/usr/bin/env python3
"""Check MDF repos for MDFs not in MDB. If found, add to models yaml."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import click
from dotenv import load_dotenv
from packaging.version import Version
from packaging.version import parse as parse_version

from bento_mdb_updates.clients import GitHubClient
from bento_mdb_updates.model_cdes import dump_to_yaml, load_model_specs_from_yaml

if TYPE_CHECKING:
    from bento_mdb_updates.datatypes import ModelSpec


load_dotenv(Path("config/.env"))
logger = logging.getLogger(__name__)


def normalize_tag_version(tag: str) -> str:
    """
    Extract a semantic version string (e.g., "2.1.0") from a tag.

    Returns an tag as-is if no valid semantic version is found.
    """
    match = re.search(r"(\d+\.\d+\.\d+)", tag)
    if match:
        return match.group(1)
    logger.warning("No semantic version found in tag %s", tag)
    return tag


def update_model_versions(
    model_specs: dict[str, ModelSpec],
    github_client: GitHubClient,
    *,
    new_only: bool = True,
) -> bool:
    """Update ModelSpec with missing version tags and prerelease commits from GitHub."""
    updated = False
    for model, spec in model_specs.items():
        logger.info("Checking %s for new tags...", model)
        repo = spec.get("repository")
        if not repo:
            logger.warning("No repository specified for %s", model)
            continue
        raw_tags = github_client.get_repo_tags(repo)
        current_versions = spec.get("versions", [])

        nonignored_versions = [
            v for v in current_versions if not v.get("ignore", False)
        ]
        current_latest_version = Version(
            max([v["version"] for v in nonignored_versions], default="0.0.0"),
        )
        if raw_tags:
            for tag in raw_tags:
                normalized_tag = normalize_tag_version(tag)
                tag_version = Version(normalized_tag)

                if any(
                    v.get("tag") == tag and v.get("ignore", False)
                    for v in current_versions
                ):
                    logger.info("Ignoring tag %s as it's marked as ignored", tag)
                    continue

                if new_only and tag_version <= current_latest_version:
                    logger.info(
                        "Skipping %s, version is not newer than latest version %s",
                        tag_version,
                        current_latest_version,
                    )
                    continue

                if not any(
                    v.get("version") == normalized_tag for v in current_versions
                ):
                    logger.info("Adding %s to versions for %s", normalized_tag, model)
                    new_version_entry = {"version": normalized_tag, "tag": tag}
                    current_versions.append(new_version_entry)
                    updated = True

        if current_versions:
            sorted_versions = sorted(
                current_versions,
                key=lambda x: parse_version(x["version"]),
            )
            spec["versions"] = sorted_versions

            nonignored_sorted = [
                v for v in sorted_versions if not v.get("ignore", False)
            ]
            if nonignored_sorted:
                spec["latest_version"] = nonignored_sorted[-1]["version"]
            else:
                spec["latest_version"] = "0.0.0"

        if not spec["in_data_hub"]:
            continue
        logger.info("Checking %s for new prerelease commits...", model)
        new_prerelease_info = github_client.get_prerelease_model_info(model)
        if not new_prerelease_info:
            logger.info("No prerelease commits found for %s", model)
            continue
        new_sha, new_version = new_prerelease_info
        old_sha = spec.get("latest_prerelease_commit", "")
        if new_sha != old_sha:
            logger.info(
                "New prerelease commit found for %s: %s",
                model,
                new_sha,
            )
            spec["latest_prerelease_commit"] = new_sha
            spec["latest_prerelease_version"] = new_version
            updated = True
    return updated


@click.command()
@click.option(
    "--model_specs_yaml",
    help="Path to model specs YAML file",
    default="config/mdb_models.yml",
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@click.option(
    "--new_only",
    type=bool,
    default=True,
    show_default=True,
    help="Only update new versions",
)
@click.option(
    "--no_commit",
    type=bool,
    default=False,
    show_default=True,
    help="Don't commit changes",
)
def main(
    model_specs_yaml: Path,
    *,
    new_only: bool = True,
    no_commit: bool = False,
) -> None:
    """Update model versions in the model spec YAML and commit changes to GitHub."""
    github_client = GitHubClient()
    model_specs = load_model_specs_from_yaml(model_specs_yaml)
    updated = update_model_versions(model_specs, github_client, new_only=new_only)
    if not updated:
        logger.info("No new versions found. Exiting.")
        return
    logger.info("Model versions updated. Saving changes...")
    dump_to_yaml(model_specs, model_specs_yaml)
    if not no_commit:
        logger.info("Committing changes...")
        github_client.commit_and_push_changes(Path(model_specs_yaml))


if __name__ == "__main__":
    main()
