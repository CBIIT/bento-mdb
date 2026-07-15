from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from scripts.make_edp_changelog import (
    _escape,
    _to_snake_case,
    _generate_edp_changesets,
    _edp_definitions_from_files,
    generate_edp_changelog,
)

TEST_EDP_PROPS = Path(__file__).parent / "samples" / "test_edp_props.yml"
TEST_EDP_TERMS = Path(__file__).parent / "samples" / "test_edp_terms.yml"

TEST_AUTHOR = "test-author"
TEST_COMMIT = "abc1234"


class TestToSnakeCase:
    def test_lowercases_and_replaces_spaces(self) -> None:
        assert _to_snake_case("Hello World") == "hello_world"

    def test_strips_leading_trailing_underscores(self) -> None:
        assert _to_snake_case("  hello  ") == "hello"

    def test_collapses_multiple_separators(self) -> None:
        assert _to_snake_case("foo--bar__baz") == "foo_bar_baz"

    def test_handles_empty_string(self) -> None:
        assert _to_snake_case("") == ""


class TestEscape:
    def test_escapes_single_quotes(self) -> None:
        assert _escape("it's") == "it\\'s"

    def test_no_quotes_unchanged(self) -> None:
        assert _escape("hello world") == "hello world"


class TestGenerateEdpChangesets:

    def test_invalid_edp_mdf_raises(self, tmp_path: Path) -> None:
        edp_props = tmp_path / "edp-props.yml"
        terms = tmp_path / "terms.yml"

        edp_props.write_text(
            yaml.safe_dump(
                {
                    "Nodes": {},
                    "Relationships": {},
                    "PropDefinitions": {
                        "bad_edp": {
                            "Ext": True,
                            "Enum": ["term_1"],
                        },
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        terms.write_text(
            yaml.safe_dump({"Terms": {}}, sort_keys=False),
            encoding="utf-8",
        )

        # bento-mdf will catch the bad edp
        with pytest.raises(RuntimeError, match="but has no Term: annotation"):
            prop_handle, prop = _edp_definitions_from_files([edp_props], [terms])[0]

    def test_generates_edp_term_changeset(self) -> None:
        """Should generate MERGE for EDP term node."""
        prop_handle, prop = _edp_definitions_from_files(
            [TEST_EDP_PROPS],
            [TEST_EDP_TERMS],
        )[0]

        changesets = _generate_edp_changesets(
            prop_handle,
            prop,
            TEST_AUTHOR,
            TEST_COMMIT,
            1,
        )

        stmts = [cs.change_type.text for cs in changesets]
        assert any("MERGE (edp:term" in s for s in stmts)
        assert any("specifies_value_set" in s for s in stmts)
        assert any("CRDC00001" in s for s in stmts)

    def test_generates_pv_term_changesets(self) -> None:
        """Should generate MERGE + has_term for each PV."""
        prop_handle, prop = _edp_definitions_from_files(
            [TEST_EDP_PROPS],
            [TEST_EDP_TERMS],
        )[0]

        changesets = _generate_edp_changesets(
            prop_handle,
            prop,
            TEST_AUTHOR,
            TEST_COMMIT,
            1,
        )

        stmts = [cs.change_type.text for cs in changesets]
        assert any("MERGE (pv:term" in s for s in stmts)
        assert any("has_term" in s for s in stmts)
        assert any("OBIB:0000070" in s for s in stmts)
        assert any("OBIB:0000071" in s for s in stmts)

    def test_changeset_ids_are_sequential(self) -> None:
        """Changeset IDs should start at start_id and increment."""
        prop_handle, prop = _edp_definitions_from_files(
            [TEST_EDP_PROPS],
            [TEST_EDP_TERMS],
        )[0]

        changesets = _generate_edp_changesets(
            prop_handle,
            prop,
            TEST_AUTHOR,
            TEST_COMMIT,
            5,
        )

        ids = [int(cs.id) for cs in changesets]
        assert ids == list(range(5, 5 + len(changesets)))


class TestGenerateEdpChangelog:
    def test_no_edp_props_returns_empty_changelog(self, tmp_path: Path) -> None:
        """An EDP-shaped MDF with no EDP props should produce an empty changelog."""
        edp_props = tmp_path / "edp-props.yml"

        edp_props.write_text(
            yaml.safe_dump(
                {
                    "Nodes": {},
                    "Relationships": {},
                    "PropDefinitions": {},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        changelog = generate_edp_changelog(
            [edp_props],
            [],
            author=TEST_AUTHOR,
            _commit=TEST_COMMIT,
        )

        assert changelog.count_changesets() == 0

    def test_edp_files_produce_changelog(self) -> None:
        """EDP props + terms files should produce a non-empty changelog."""
        changelog = generate_edp_changelog(
            [TEST_EDP_PROPS], [TEST_EDP_TERMS], author=TEST_AUTHOR, _commit=TEST_COMMIT
        )
        assert changelog.count_changesets() > 0

    def test_changelog_xml_is_valid(self) -> None:
        """Output XML should be parseable."""
        changelog = generate_edp_changelog(
            [TEST_EDP_PROPS], [TEST_EDP_TERMS], author=TEST_AUTHOR, _commit=TEST_COMMIT
        )
        xml_element = changelog.to_xml()
        assert xml_element.tag.endswith("databaseChangeLog")    

    def test_edp_config_filters_to_latest_configured_version(self, tmp_path: Path) -> None:
        edp_props = tmp_path / "edp-props.yml"
        terms = tmp_path / "terms.yml"
        config = tmp_path / "mdb_edps.yml"

        edp_props.write_text(
            yaml.safe_dump(
                {
                    "Nodes": {},
                    "Relationships": {},
                    "PropDefinitions": {
                        "obib_terms_valueset": {
                            "Ext": True,
                            "Term": [
                                {
                                    "Origin": "CRDC",
                                    "Code": "CRDC0002",
                                    "Version": "2",
                                    "Value": "OBIB",
                                },
                            ],
                            "Enum": ["term_1"],
                        },
                        "other_valueset": {
                            "Ext": True,
                            "Term": [
                                {
                                    "Origin": "CRDC",
                                    "Code": "CRDC0003",
                                    "Version": "1",
                                    "Value": "Other",
                                },
                            ],
                            "Enum": ["term_2"],
                        },
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        terms.write_text(
            yaml.safe_dump(
                {
                    "Terms": {
                        "term_1": {
                            "Origin": "OBIB",
                            "Code": "0001",
                            "Version": "1",
                            "Value": "term_1",
                        },
                        "term_2": {
                            "Origin": "OTHER",
                            "Code": "0002",
                            "Version": "1",
                            "Value": "term_2",
                        },
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        config.write_text(
            yaml.safe_dump(
                {
                    "OBIB": {
                        "latest_version": "2",
                        "prop_definition": "obib_terms_valueset",
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        changelog = generate_edp_changelog(
            [edp_props],
            [terms],
            author=TEST_AUTHOR,
            _commit=TEST_COMMIT,
            edp_config_file=config,
        )

        stmts = [cs.change_type.text for cs in changelog.subelements]
        assert any("CRDC0002" in stmt for stmt in stmts)
        assert not any("CRDC0003" in stmt for stmt in stmts)
