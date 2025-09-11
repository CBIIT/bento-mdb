"""Check for new caDSR PVs and NCIT mappings and generate Cypher to update MDB."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING

from github import Github, GithubException, InputGitAuthor
from prefect import flow, get_run_logger, task
from prefect.blocks.system import Secret

from bento_mdb_updates.cde_cypher import convert_model_cdes_to_changelog
from bento_mdb_updates.clients import CADSRClient, NCItClient
from bento_mdb_updates.constants import (
    GITHUB_TOKEN_SECRET,
    MDB_UPDATES_GH_REPO,
)
from bento_mdb_updates.mdb_utils import init_mdb_connection
from bento_mdb_updates.model_cdes import (
    add_ncit_synonyms_to_model_cde_spec,
    get_cdes_from_mdb,
)

if TYPE_CHECKING:
    from bento_mdb_updates.datatypes import MDBCDESpec, ModelCDESpec


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


@task
def commit_new_files(files: list[Path]) -> list:
    """Commit new files to GitHub."""
    logger = get_run_logger()
    github_token = Secret.load(GITHUB_TOKEN_SECRET).get()  # type: ignore reportAttributeAccessIssue
    gh = Github(github_token)
    repo = gh.get_repo(MDB_UPDATES_GH_REPO)
    committer = InputGitAuthor("GitHub Actions Bot", "actions@github.com")

    results = []
    for file_path in files:
        try:
            if file_path.is_absolute():
                repo_path = str(file_path.relative_to(Path.cwd()))
            else:
                repo_path = str(file_path)
            repo_path = repo_path.lstrip("/")
            logger.info("Converting %s to %s", file_path, repo_path)
            with file_path.open("r", encoding="utf-8") as f:
                file_content = f.read()

            file_exists = False
            file_sha = None
            try:
                dir_path = "/".join(repo_path.split("/")[:-1])
                filename = repo_path.split("/")[-1]
                if not dir_path:
                    dir_path = ""
                logger.info("Checking directory '%s' for file '%s'", dir_path, filename)
                dir_contents = repo.get_contents(dir_path)
                if isinstance(dir_contents, list):
                    for item in dir_contents:
                        if item.path == repo_path:
                            file_exists = True
                            file_sha = item.sha
                            logger.info(
                                "Found file %s with SHA: %s",
                                repo_path,
                                file_sha,
                            )
                elif dir_contents.path == repo_path:
                    file_exists = True
                    file_sha = dir_contents.sha
            except GithubException as e:
                if e.status == 404:
                    logger.info("Directory %s does not exist", dir_path)
                    file_exists = False
                else:
                    raise
            try:
                if file_exists and file_sha is not None:
                    logger.info("Updating existing file %s", repo_path)
                    commit_msg = f"Update {repo_path} (GitHub Actions)"
                    result = repo.update_file(
                        path=repo_path,
                        message=commit_msg,
                        content=file_content,
                        sha=file_sha,
                        committer=committer,
                    )
                    results.append(
                        f"Updated {repo_path} (commit: {result['commit'].sha[:7]})",
                    )
                else:
                    logger.info("Creating new file %s", repo_path)
                    commit_msg = f"Add {repo_path} (GitHub Actions)"
                    result = repo.create_file(
                        path=repo_path,
                        message=commit_msg,
                        content=file_content,
                        committer=committer,
                    )
                    results.append(
                        f"Created {repo_path} (commit: {result['commit'].sha[:7]})",
                    )
            except GithubException as e:
                if e.status == 422 and "too large" in str(e):
                    logger.exception("File %s is too large for GitHub API", repo_path)
                    results.append(
                        f"Error: File {repo_path} is too large for GitHub API",
                    )
                else:
                    raise
        except Exception as e:
            error_msg = f"Error updating {file_path}: {e}"
            results.append(error_msg)
            logger.exception(error_msg)

    for result in results:
        logger.info(result)

    if any("Error" in result for result in results):
        msg = "Some files failed to update. See logs for details."
        raise RuntimeError(msg)

    return results


@flow(name="update-terms", log_prints=True)
def update_terms(
    mdb_id: str,
    author: str,
    output_file: str | Path | None = None,
    commit: str | None = None,
    *,
    no_commit: bool = False,
) -> None:
    """Check for new CDE PVs and synonyms and generate Cypher to update the database."""
    logger = get_run_logger()
    today = datetime.datetime.now(tz=datetime.UTC).strftime("%Y%m%d")
    if output_file is None:
        output_file = Path(f"data/output/mdb_cdes/mdb_cdes_{mdb_id}_{today}.json")
    else:
        output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    mdb_cdes = get_current_mdb_cdes(mdb_id)
    update_cde_spec = update_mdb_cdes_from_term_sources(mdb_cdes)

    # convert annotation updates to liquibase changelog
    changelog = convert_model_cdes_to_changelog(update_cde_spec, author, commit)
    output_dir = Path().cwd() / "data/output/term_changelogs"
    changelog_file = output_dir / f"{mdb_id}_{today}_term_updates.xml"
    changelog_file.parent.mkdir(parents=True, exist_ok=True)
    changelog.save_to_file(str(changelog_file), encoding="UTF-8")

    # Update mdb_cdes JSON file
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(mdb_cdes, f, indent=2)

    if changelog.count_changesets() == 0:
        logger.info("No changesets to commit")
        no_commit = True

    if not no_commit:
        logger.info("Committing changes...")
        commit_new_files([output_file, changelog_file])

    # Print changlog file as JSON for GitHub Actions
    make_changelog_output_more_visible(changelog_file)
