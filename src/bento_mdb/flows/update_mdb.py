"""Run MDB-Changelog-Runner against changelog files."""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from mdb_changelog_runner import ChangelogExecutor, ChangelogRunResult

from prefect import flow, get_run_logger, task

from bento_mdb.mdb_utils import init_mdb_connection

MODEL_CHANGELOG_ROOT = "model_changelogs"
TERM_CHANGELOG_ROOT = "term_changelogs"
EXTERNAL_ONTOLOGY_CHANGELOG_ROOT = "external_ont_changelogs"
DEFAULT_CHANGELOG_SCOPE = ("OTHER", "MISC")
CHANGELOG_CYPHER_ENTITY_REPLACEMENTS = (
    ("&gt;", ">"),
    ("&lt;", "<"),
    ("&quot;", '"'),
    ("&apos;", "'"),
    ("&amp;", "&"),
)


def run_changelog_with_driver(
    driver: Any,
    changelog_file: Path | str,
    changelog_location: str,
    changelog_scope: str | None = None,
    changelog_scope_path: str | None = None,
    *,
    dry_run: bool = False,
    schema_mode: bool = False,
    logger: logging.Logger | None = None,
) -> ChangelogRunResult:
    """Run a changelog with MDB-Changelog-Runner using a Neo4j driver."""
    executor = ChangelogExecutor(driver, logger=logger)
    changelog_scope = changelog_scope.upper() if changelog_scope else None
    changelog_scope_path = changelog_scope_path.upper() if changelog_scope_path else None
    return executor.execute(
        changelog_file,
        changelog_location,
        changelog_scope,
        changelog_scope_path,
        dry_run=dry_run,
        schema_mode=schema_mode,
    )


def run_changelog_with_runner(
    changelog_file: Path | str,
    changelog_location: str,
    mdb_id: str,
    changelog_scope: str | None = None,
    changelog_scope_path: str | None = None,
    *,
    dry_run: bool = False,
    schema_mode: bool = False,
    logger: logging.Logger | None = None,
) -> ChangelogRunResult:
    """Run a changelog with MDB-Changelog-Runner."""
    mdb = init_mdb_connection(mdb_id, writeable=True, allow_empty=True)
    try:
        return run_changelog_with_driver(
            mdb.driver,
            changelog_file,
            changelog_location,
            changelog_scope,
            changelog_scope_path,
            dry_run=dry_run,
            schema_mode=schema_mode,
            logger=logger,
        )
    finally:
        mdb.close()


def infer_changelog_scope(key: str) -> tuple[str | None, str | None]:
    """Infer runner scope and scope_group from the changelog S3 key.

    Examples:
    - model_changelogs/CTDC/ctdc/file.xml -> ("MODEL", "CTDC")
    - term_changelogs/file.xml -> ("TERM", "TERM")
    - external_ont_changelogs/icdo/file.xml -> ("ICDO", "ICDO")
    """
    key_parts = [part for part in key.split("/") if part]
    if not key_parts:
        return DEFAULT_CHANGELOG_SCOPE

    if key_parts[0] == MODEL_CHANGELOG_ROOT:
        group = key_parts[2].upper() if len(key_parts) > 3 else "MISC"
        return "MODEL", group
    if key_parts[0] == TERM_CHANGELOG_ROOT:
        return "TERM", "TERM"
    if key_parts[0] == EXTERNAL_ONTOLOGY_CHANGELOG_ROOT:
        group = key_parts[1].upper() if len(key_parts) > 2 else "OTHER"
        return group, group

    return DEFAULT_CHANGELOG_SCOPE


def prepare_changelog_file_for_runner(
    changelog_file: Path,
    logger: logging.Logger | Any,
) -> int:
    """Validate and rewrite cypher text in a temp changelog before runner execution."""
    with changelog_file.open("r", encoding="utf-8") as f:
        content = f.read()

    header_match = re.search(
        r'(<\?xml[^>]*\?>\s*<databaseChangeLog[^>]*>)',
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not header_match:
        msg = "Could not find databaseChangeLog header in changelog file"
        raise ValueError(msg)

    changeset_pattern = re.compile(
        r'(<changeSet[^>]*>.*?</changeSet>)',
        re.DOTALL,
    )
    changesets = changeset_pattern.findall(content)

    total_changesets = len(changesets)
    logger.info("Found %d changesets in changelog file", total_changesets)

    if total_changesets == 0:
        msg = "No changesets found in changelog file"
        raise ValueError(msg)

    cypher_pattern = re.compile(
        r"(<neo4j:cypher[^>]*>)(.*?)(</neo4j:cypher>)",
        re.DOTALL,
    )

    def normalize_cypher(match: re.Match[str]) -> str:
        cypher_statement = match.group(2).strip()
        cypher_statement = cypher_statement.replace("<![CDATA[", "").replace("]]>", "").strip()
        for old, new in CHANGELOG_CYPHER_ENTITY_REPLACEMENTS:
            cypher_statement = cypher_statement.replace(old, new)
        return f"{match.group(1)}{_wrap_cdata(cypher_statement)}{match.group(3)}"

    content = cypher_pattern.sub(normalize_cypher, content)
    changelog_file.write_text(content, encoding="utf-8")
    return total_changesets


def _wrap_cdata(value: str) -> str:
    return f"<![CDATA[{value.replace(']]>', ']]]]><![CDATA[>')}]]>"


@task
def split_changelog_file(changelog_file: str, max_changesets: int) -> list[Path]:
    """Split changelog file into smaller files, each smaller file contains at most max_changesets changesets.
    
    This function properly parses XML to find changeset boundaries, regardless of how many lines
    each changeset spans. Changesets can have varying numbers of lines depending on the Cypher query content.
    """
    logger = get_run_logger()
    changelog_path = Path(changelog_file)
    
    # Read the entire file content
    with changelog_path.open("r", encoding="utf-8") as f:
        content = f.read()
    
    # Extract the XML header (first line) and databaseChangeLog opening tag
    # Find the opening databaseChangeLog tag with all its attributes
    header_match = re.search(
        r'(<\?xml[^>]*\?>\s*<databaseChangeLog[^>]*>)',
        content,
        re.MULTILINE | re.DOTALL
    )
    if not header_match:
        msg = "Could not find databaseChangeLog header in changelog file"
        raise ValueError(msg)
    
    header = header_match.group(1)
    closing_tag = "</databaseChangeLog>"
    
    # Find all changesets using regex that handles multi-line content
    # This pattern matches from <changeSet to </changeSet> including all content in between
    changeset_pattern = re.compile(
        r'(<changeSet[^>]*>.*?</changeSet>)',
        re.DOTALL
    )
    changesets = changeset_pattern.findall(content)
    
    total_changesets = len(changesets)
    logger.info("Found %d changesets in changelog file", total_changesets)
    
    if total_changesets == 0:
        msg = "No changesets found in changelog file"
        raise ValueError(msg)
    
    smaller_changelog_files = []
    
    # Split changesets into chunks
    num_splits = (total_changesets + max_changesets - 1) // max_changesets
    logger.info("Splitting into %d files (max %d changesets per file)", num_splits, max_changesets)
    
    for split_idx in range(num_splits):
        start_idx = split_idx * max_changesets
        end_idx = min(start_idx + max_changesets, total_changesets)
        chunk_changesets = changesets[start_idx:end_idx]
        
        # Create split file with suffix 1, 2, 3, etc.
        file_suffix = split_idx + 1
        smaller_changelog_file = changelog_path.with_name(
            f"{changelog_path.stem}_{file_suffix}.xml"
        )
        
        # Write the split file with proper XML structure
        with smaller_changelog_file.open("w", encoding="utf-8") as f:
            f.write(header + "\n")
            for changeset in chunk_changesets:
                # Add proper indentation (2 spaces) for readability
                # Split the changeset into lines and indent each line
                changeset_lines = changeset.split("\n")
                for line in changeset_lines:
                    if line.strip():  # Skip empty lines
                        f.write("  " + line + "\n")
            f.write(closing_tag + "\n")
        
        smaller_changelog_files.append(smaller_changelog_file)
        logger.info(
            "Created split file %d/%d: %s (%d changesets, %.2f MB)",
            split_idx + 1,
            num_splits,
            smaller_changelog_file.name,
            len(chunk_changesets),
            smaller_changelog_file.stat().st_size / (1024 * 1024),
        )
    
    logger.info("Successfully split changelog into %d files", len(smaller_changelog_files))
    return smaller_changelog_files

@flow(name="liquibase-update", log_prints=True)
def liquibase_update_flow(
    key: str,
    mdb_id: str,
    log_level: str = "info",
    bucket: str | None = None,
    scope: str | None = None,
    scope_group: str | None = None,
    *,
    dry_run: bool = False,
    schema_mode: bool = False,
) -> None:
    """Run MDB-Changelog-Runner against a changelog fetched from S3."""
    logger = get_run_logger()

    s3 = boto3.client("s3")

    try:
        meta = s3.head_object(Bucket=bucket, Key=key)
        logger.info("Found s3://%s/%s (size: %d bytes)", bucket, key, meta["ContentLength"])
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            msg = f"S3 key not found: s3://{bucket}/{key}"
            raise FileNotFoundError(msg) from e
        if code in ("403", "AccessDenied"):
            msg = f"Access denied to s3://{bucket}/{key}"
            raise PermissionError(msg) from e
        logger.error("Unexpected S3 error (code=%s) for s3://%s/%s: %s", code, bucket, key, e)
        raise

    changelog_location = f"s3://{bucket}/{key}"

    logger.info("Downloading s3://%s/%s", bucket, key)
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        s3.download_fileobj(bucket, key, tmp)
        changelog_file = Path(tmp.name)
    logger.info("Downloaded to temp file: %s", changelog_file)

    prepare_changelog_file_for_runner(changelog_file, logger)

    if scope is None and scope_group is None:
        scope, scope_group = infer_changelog_scope(key)
    logger.info(
        "Using changelog scope=%s scope_group=%s schema_mode=%s",
        scope,
        scope_group,
        schema_mode,
    )
    result = run_changelog_with_runner(
        changelog_file,
        changelog_location,
        mdb_id,
        scope,
        scope_group,
        dry_run=dry_run,
        schema_mode=schema_mode,
        logger=logger,
    )
    logger.info(
        "MDB-Changelog-Runner finished %s (%d changesets, dry_run=%s)",
        changelog_location,
        result.changesets_executed,
        result.dry_run,
    )
