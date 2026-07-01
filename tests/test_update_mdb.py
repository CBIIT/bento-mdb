"""Tests for update_mdb module."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from bento_mdb.flows.update_mdb import (
    infer_changelog_scope,
    prepare_changelog_file_for_runner,
    run_changelog_with_driver,
    split_changelog_file,
)

CURRENT_DIRECTORY = Path(__file__).resolve().parent
TEST_CHANGELOG_FILE_LARGE = Path(CURRENT_DIRECTORY, "samples", "sample_changelog_large.xml")
TEST_CHANGELOG_FILE_SMALL = Path(CURRENT_DIRECTORY, "samples", "sample_changelog.xml")


class FakeTx:
    def __init__(self):
        self.runs = []

    def run(self, query: str, parameters=None, **kwargs):
        self.runs.append((query, parameters if parameters is not None else kwargs))

    def commit(self):
        pass

    def rollback(self):
        pass


class FakeSession:
    def __init__(self, tx: FakeTx):
        self.tx = tx

    def begin_transaction(self):
        return self.tx


class TestRunChangelogWithRunner:
    """Tests for MDB changelog runner integration."""

    def test_passes_logger_to_changelog_runner(self, tmp_path, caplog) -> None:
        """Run changelog through the provided logger."""
        changelog_file = tmp_path / "changelog.xml"
        changelog_file.write_text(
            """<?xml version='1.0' encoding='UTF-8'?>
<databaseChangeLog
  xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
  xmlns:neo4j="http://www.liquibase.org/xml/ns/dbchangelog-ext">
  <changeSet id="test-runner-logs-1" author="TEST">
    <neo4j:cypher>CREATE (n:codex_runner_log_test)</neo4j:cypher>
  </changeSet>
</databaseChangeLog>
""",
            encoding="utf-8",
        )
        logger = logging.getLogger("bento_mdb.test.runner")

        with caplog.at_level(logging.INFO, logger=logger.name):
            result = run_changelog_with_driver(
                FakeSession(FakeTx()),
                changelog_file,
                "local://test-runner-logs.xml",
                changelog_scope="model",
                changelog_scope_path="ctdc",
                logger=logger,
            )

        messages = [record.getMessage() for record in caplog.records]
        assert result.changelog_scope == "MODEL"
        assert result.changelog_scope_path == "CTDC"
        assert "Found 1 changesets in changelog file" in messages
        assert "Completed changelog update 1" in messages

    def test_prepares_changelog_file_before_runner(self, tmp_path) -> None:
        """Rewrite XML entity escapes before passing the temp changelog to runner."""
        changelog_file = tmp_path / "changelog.xml"
        changelog_file.write_text(
            """<?xml version='1.0' encoding='UTF-8'?>
<databaseChangeLog
  xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
  xmlns:neo4j="http://www.liquibase.org/xml/ns/dbchangelog-ext">
  <changeSet id="test-runner-rewrite-1" author="TEST">
    <neo4j:cypher>MATCH (a)-[r]-&gt;(b) WHERE a.value &lt;&gt; &quot;x&quot; RETURN a &amp; b</neo4j:cypher>
  </changeSet>
</databaseChangeLog>
""",
            encoding="utf-8",
        )
        logger = logging.getLogger("bento_mdb.test.prepare")
        tx = FakeTx()

        assert prepare_changelog_file_for_runner(changelog_file, logger) == 1
        result = run_changelog_with_driver(
            FakeSession(tx),
            changelog_file,
            "local://test-runner-rewrite.xml",
            logger=logger,
        )

        assert result.changesets_executed == 1
        assert tx.runs[0][0] == 'MATCH (a)-[r]->(b) WHERE a.value <> "x" RETURN a & b'

    def test_infers_scope_from_fixed_s3_folder_layout(self) -> None:
        """Infer runner scope metadata from the fixed S3 folder layout."""
        assert infer_changelog_scope("model_changelogs/CTDC/ctdc/file.xml") == (
            "MODEL",
            "CTDC",
        )
        assert infer_changelog_scope("model_changelogs/CTDC/file.xml") == (
            "MODEL",
            "MISC",
        )
        assert infer_changelog_scope("term_changelogs/dev_term_updates.xml") == (
            "TERM",
            "TERM",
        )
        assert infer_changelog_scope("external_ont_changelogs/icdo/icdo.xml") == (
            "ICDO",
            "ICDO",
        )
        assert infer_changelog_scope("external_ont_changelogs/obib/obib.xml") == (
            "OBIB",
            "OBIB",
        )
        assert infer_changelog_scope("external_ont_changelogs/uberon/uberon.xml") == (
            "UBERON",
            "UBERON",
        )
        assert infer_changelog_scope("external_ont_changelogs/new_ontology/foo.xml") == (
            "NEW_ONTOLOGY",
            "NEW_ONTOLOGY",
        )
        assert infer_changelog_scope("external_ont_changelogs/foo.xml") == (
            "OTHER",
            "OTHER",
        )
        assert infer_changelog_scope("other_changelogs/misc.xml") == ("OTHER", "MISC")
        assert infer_changelog_scope("misc.xml") == ("OTHER", "MISC")

    def test_executes_changelog_against_local_neo4j(self, tmp_path) -> None:
        """Run changelog through MDB-Changelog-Runner against local Neo4j."""
        uri = os.getenv("MDB_TEST_NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("MDB_TEST_NEO4J_USER", "neo4j")
        password = os.getenv("MDB_TEST_NEO4J_PASSWORD", "changeme")
        changelog_file = tmp_path / "changelog.xml"
        changelog_file.write_text(
            """<?xml version='1.0' encoding='UTF-8'?>
<databaseChangeLog
  xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
  xmlns:neo4j="http://www.liquibase.org/xml/ns/dbchangelog-ext">
  <changeSet id="test-runner-integration-1" author="TEST">
    <neo4j:cypher>
      MERGE (n:codex_runner_test {handle: 'DATATEAM-628'})
      SET n.updated_by = 'mdb-changelog-runner'
    </neo4j:cypher>
  </changeSet>
</databaseChangeLog>
""",
            encoding="utf-8",
        )

        driver = GraphDatabase.driver(uri, auth=(user, password))
        connected = False
        try:
            try:
                driver.verify_connectivity()
            except Exception as exc:
                pytest.skip(f"Local Neo4j is not available at {uri}: {exc}")
            connected = True

            result = run_changelog_with_driver(
                driver,
                changelog_file,
                "local://test-runner-integration.xml",
            )

            with driver.session() as session:
                record = session.run(
                    "MATCH (n:codex_runner_test {handle: 'DATATEAM-628'}) "
                    "RETURN n.updated_by AS updated_by",
                ).single()
            assert result.changesets_executed == 1
            assert record is not None
            assert record["updated_by"] == "mdb-changelog-runner"
        finally:
            if connected:
                with driver.session() as session:
                    session.run(
                        "MATCH (n:codex_runner_test {handle: 'DATATEAM-628'}) DELETE n",
                    ).consume()
            driver.close()


class TestSplitChangelogFile:
    """Tests for split_changelog_file function."""

    def test_split_single_changeset(self, tmp_path) -> None:
        """Test splitting a file with a single changeset."""
        changelog_file = TEST_CHANGELOG_FILE_SMALL
        result = split_changelog_file(str(changelog_file), max_changesets=5000)

        # Should return 1 file since we have only 1 changeset
        assert len(result) == 1
        assert result[0].name == "sample_changelog_1.xml"
        assert result[0].exists()

    def test_split_exact_max_changesets(self, tmp_path) -> None:
        """Test splitting when file has exactly max_changesets changesets."""
        # Create changelog with exactly 5 changesets
        changelog_file = tmp_path / "test_changelog.xml"
        changesets = []
        for i in range(1, 6):
            changesets.append(
                f"""  <changeSet id="{i}" author="TEST">
    <neo4j:cypher>CREATE (n:test{i} {{handle:'TEST{i}'}})</neo4j:cypher>
  </changeSet>"""
            )

        changelog_content = """<?xml version='1.0' encoding='UTF-8'?>
<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:neo4j="http://www.liquibase.org/xml/ns/dbchangelog-ext" xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-latest.xsd">
""" + "\n".join(changesets) + "\n</databaseChangeLog>"
        changelog_file.write_text(changelog_content, encoding="utf-8")

        result = split_changelog_file(str(changelog_file), max_changesets=5)

        # Should return 1 file since we have exactly 5 changesets (max)
        assert len(result) == 1
        assert result[0].name == "test_changelog_1.xml"

    def test_split_multiple_files(self, tmp_path) -> None:
        """Test splitting into multiple files when changesets exceed max_changesets."""
        changelog_file = TEST_CHANGELOG_FILE_LARGE
        result = split_changelog_file(str(changelog_file), max_changesets=5000)

        # Should return 5 files as this sample changelog file has more than 21000 changesets
        assert len(result) == 5
        assert result[0].name == "sample_changelog_large_1.xml"
        assert result[1].name == "sample_changelog_large_2.xml"
        assert result[2].name == "sample_changelog_large_3.xml"
        assert result[3].name == "sample_changelog_large_4.xml"
        assert result[4].name == "sample_changelog_large_5.xml"
