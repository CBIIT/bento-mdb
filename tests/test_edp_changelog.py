from __future__ import annotations

from pathlib import Path
import pytest

from scripts.make_edp_changelog import (
    _escape,
    _to_snake_case,
    _generate_edp_changesets,
    _load_terms,
    _edp_specs_from_files,
    generate_edp_changelog,
)

TEST_EDP_PROPS = Path(__file__).parent / "samples" / "test_edp_props.yml"
TEST_EDP_TERMS = Path(__file__).parent / "samples" / "test_edp_terms.yml"
TEST_PLAIN_MDF = Path(__file__).parent / "samples" / "test_mdf_cdes.yml"

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
    def test_raises_when_edp_term_missing(self) -> None:
        terms = {}
        spec = {"Ext": True, "Enum": []}

        with pytest.raises(ValueError, match="must define Term as a mapping"):
            _generate_edp_changesets(
                "bad_edp",
                spec,
                terms,
                TEST_AUTHOR,
                TEST_COMMIT,
                1,
            )

    def test_generates_edp_term_changeset(self) -> None:
        """Should generate MERGE for EDP term node."""
        terms = _load_terms([TEST_EDP_TERMS])
        prop_handle, spec = _edp_specs_from_files([TEST_EDP_PROPS])[0]

        changesets = _generate_edp_changesets(
            prop_handle,
            spec,
            terms,
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
        terms = _load_terms([TEST_EDP_TERMS])
        prop_handle, spec = _edp_specs_from_files([TEST_EDP_PROPS])[0]

        changesets = _generate_edp_changesets(
            prop_handle,
            spec,
            terms,
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
        terms = _load_terms([TEST_EDP_TERMS])
        prop_handle, spec = _edp_specs_from_files([TEST_EDP_PROPS])[0]

        changesets = _generate_edp_changesets(
            prop_handle,
            spec,
            terms,
            TEST_AUTHOR,
            TEST_COMMIT,
            5,
        )

        ids = [int(cs.id) for cs in changesets]
        assert ids == list(range(5, 5 + len(changesets)))


class TestGenerateEdpChangelog:
    def test_no_edp_props_returns_empty_changelog(self) -> None:
        """A plain MDF with no EDP props should produce an empty changelog."""
        changelog = generate_edp_changelog(
            [TEST_PLAIN_MDF], [], author=TEST_AUTHOR, _commit=TEST_COMMIT
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