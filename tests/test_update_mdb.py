"""Tests for update_mdb module."""

from __future__ import annotations

from pathlib import Path

from bento_mdb.flows.update_mdb import liquibase_update_flow, split_changelog_file
from tests.test_utils import assert_equal

CURRENT_DIRECTORY = Path(__file__).resolve().parent
TEST_CHANGELOG_FILE_LARGE = Path(CURRENT_DIRECTORY, "samples", "sample_changelog_large.xml")
TEST_CHANGELOG_FILE_SMALL = Path(CURRENT_DIRECTORY, "samples", "sample_changelog.xml")


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


class TestLiquibaseUpdateFlow:
    """Tests for liquibase_update_flow function."""

    def test_liquibase_update_flow_success(
        self
    ):
        """Test successful execution of liquibase_update_flow."""
        changelog_file = TEST_CHANGELOG_FILE_SMALL
        try:
            liquibase_update_flow(
                changelog_file=str(changelog_file),
                mdb_id="fnl-mdb-qa",
                log_level="info",
                dry_run=False,
            )
        except Exception:
            assert False
        assert True