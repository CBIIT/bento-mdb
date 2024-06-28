"""Tests for mapping changelog generation script."""

from pathlib import Path

from liquichange.changelog import Changeset

from src.changelog_utils import update_config_changeset_id
from src.make_mapping_changelog import convert_mappings_to_changelog

CURRENT_DIRECTORY = Path(__file__).resolve().parent
TEST_MAPPING_MDF = Path(CURRENT_DIRECTORY, "samples", "test_mapping_mdf.yml")
TEST_CHANGELOG_CONFIG = Path(CURRENT_DIRECTORY, "samples", "test_changelog.ini")
AUTHOR = "Tolkien"
_COMMIT = "_COMMIT_123"


def test_make_mapping_changelog() -> None:
    changelog = convert_mappings_to_changelog(
        mapping_mdf=TEST_MAPPING_MDF,
        author=AUTHOR,
        config_file_path=TEST_CHANGELOG_CONFIG,
        _commit=_COMMIT,
    )
    update_config_changeset_id(TEST_CHANGELOG_CONFIG, 1)
    sample_changeset = changelog.subelements[0]
    assert isinstance(sample_changeset, Changeset)
    assert sample_changeset.run_always is True
    actual_changelog_length = len(changelog.subelements)
    expected_changelog_length = 6
    assert actual_changelog_length == expected_changelog_length
