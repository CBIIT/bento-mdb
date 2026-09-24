"""Tests for cde changelog generation script."""
import pytest

from bento_mdb.cde_cypher import (
    convert_annotation_to_changesets,
    convert_model_cdes_to_changelog,
    create_cde_value_set_cypher,
    create_delete_pv_cypher,
    get_cde_value_set_handle,
    get_cde_value_set_url,
)

from tests.test_utils import (
    TEST_ANNOTATION_SPEC,
    TEST_ANNOTATION_SPEC_MIN,
    TEST_ANNOTATION_SPEC_NO_VS,
    TEST_MODEL_CDE_SPEC,
    TEST_MODEL_CDE_SPEC_NO_ANNOTATIONS,
    TEST_ANNOTATION_SPEC_EDP,
    assert_equal,
    remove_nanoids_from_str,
)

TEST_COMMIT = "CDEPV-TEST"
TEST_AUTHOR = "TOLKIEN"

def get_changeset_texts(changesets) -> list[str]:
    """Return generated Cypher from changesets."""
    return [
        changeset.change_type.text
        if changeset.change_type
        else ""
        for changeset in changesets
    ]


def assert_cde_value_set_merge(
    statement: str,
    *,
    handle: str,
    expected_url: str,
) -> None:
    """Assert that CDE identity uses handle and stores URL as metadata."""
    merge_clause = statement.split(
        "ON CREATE SET",
        maxsplit=1,
    )[0]

    assert statement.startswith("MERGE (vs:value_set")
    assert handle in merge_clause
    assert "url" not in merge_clause
    assert "nanoid" not in merge_clause
    assert "_commit" not in merge_clause

    assert "ON CREATE SET" in statement
    assert "nanoid" in statement
    assert "_commit" in statement

    assert "SET vs.url" in statement
    assert expected_url in statement

def test_cde_value_set_handle_uses_id_and_version() -> None:
    assert get_cde_value_set_handle("100", "1.00") == "100|1.00"
    assert get_cde_value_set_handle("200", "1.00") == "200|1.00"


def test_cde_value_set_versions_remain_distinct() -> None:
    assert get_cde_value_set_handle("100", "1") != (
        get_cde_value_set_handle("100", "1.00")
    )


def test_cde_value_set_normalizes_nullish_version() -> None:
    assert get_cde_value_set_handle("100", None) == "100|"
    assert get_cde_value_set_handle("100", "null") == "100|"


def test_cde_value_set_url_omits_null_version() -> None:
    assert get_cde_value_set_url("100", None).endswith(
        "/DataElement/100",
    )
    assert "?version=" not in get_cde_value_set_url("100", None)
    assert "?version=null" not in get_cde_value_set_url(
        "100",
        "null",
    )


def test_cde_value_set_requires_id() -> None:
    with pytest.raises(ValueError, match="CDE ID"):
        get_cde_value_set_handle("", "1")

    with pytest.raises(ValueError, match="CDE ID"):
        get_cde_value_set_url(None, "1")


def test_cde_value_set_merge_uses_only_handle_as_identity() -> None:
    statement = create_cde_value_set_cypher(
        "100",
        "1.00",
        "commit-1",
    )
    text = str(statement)
    merge_text = text.split("ON CREATE SET", maxsplit=1)[0]

    assert "handle" in merge_text
    assert "url" not in merge_text
    assert "nanoid" not in merge_text
    assert "_commit" not in merge_text
    assert "?version=1.00" in text

def test_create_delete_pv_cypher_escapes_single_quotes() -> None:
    actual = create_delete_pv_cypher(
        "Children's Hospital",
        "123",
        "1",
        "456",
        "2",
    )

    assert actual.startswith("MATCH (vs:value_set")
    assert 'handle: "456|2"' in actual
    assert "-[r:has_term]->(pv:term)" in actual
    assert "toLower(coalesce(pv.origin_name, ''))" in actual
    assert 'coalesce(pv.origin_id, \'\') = "123"' in actual
    assert (
        'coalesce(pv.value, \'\') = "Children\'s Hospital"'
        in actual
    )
    assert 'coalesce(pv.origin_version, \'\') = "1"' in actual
    assert actual.endswith("DELETE r")
    assert "DELETE r, pv" not in actual


class TestConvertAnnotationToChangesets:
    """Tests for convert_annotation_to_changesets."""

    def test_convert_annotation_to_changesets(self) -> None:
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = get_changeset_texts(changesets)

        assert actual

        assert_cde_value_set_merge(
            actual[0],
            handle="6118266|1.00",
            expected_url=(
                "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/"
                "api/DataElement/6118266?version=1.00"
            ),
        )

        term_merges = [
            stmt
            for stmt in actual
            if stmt.startswith("MERGE (n0:term")
        ]
        has_term_links = [
            stmt
            for stmt in actual
            if ":has_term" in stmt
        ]
        synonym_links = [
            stmt
            for stmt in actual
            if ":represents" in stmt
            and "mapping_source" in stmt
        ]

        assert term_merges
        assert len(has_term_links) == 3
        assert synonym_links

        # Term definitions are metadata, not MERGE identity.
        for statement in term_merges:
            merge_clause = statement.split(
                "ON CREATE SET",
                maxsplit=1,
            )[0].split(
                " SET ",
                maxsplit=1,
            )[0]

            assert "origin_definition" not in merge_clause
            assert "nanoid" not in merge_clause
            assert "_commit" not in merge_clause

        # Value-set relationship matching uses only the CDE handle.
        for statement in has_term_links:
            value_set_match = statement.split(
                "),",
                maxsplit=1,
            )[0]

            assert "handle:" in value_set_match
            assert "url:" not in value_set_match
            assert "nanoid:" not in value_set_match

        # The assertions preserve source-specific concepts.
        generated_text = "\n".join(actual)
        assert 'value: "caDSR"' in generated_text
        assert 'value: "NCIm"' in generated_text
        assert 'value: "alternate_name"' in generated_text

        # Existing concepts are searched from either term.
        assert "(left)-[:represents]->(candidate)" in generated_text
        assert "(right)-[:represents]->(candidate)" in generated_text

    def test_convert_annotation_to_changesets_min(self) -> None:
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC_MIN,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = get_changeset_texts(changesets)

        assert_cde_value_set_merge(
            actual[0],
            handle="11524549|",
            expected_url=(
                "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/"
                "api/DataElement/11524549"
            ),
        )

        assert "?version=" not in actual[0]
        assert "?version=null" not in actual[0]

        term_merges = [
            stmt
            for stmt in actual
            if stmt.startswith("MERGE (n0:term")
        ]
        has_term_links = [
            stmt
            for stmt in actual
            if ":has_term" in stmt
        ]

        assert len(term_merges) == 2
        assert len(has_term_links) == 2

        assert any("Pediatric" in stmt for stmt in term_merges)
        assert any(
            "Adult - legal age" in stmt
            for stmt in term_merges
        )

        for statement in term_merges:
            merge_clause = statement.split(
                "ON CREATE SET",
                maxsplit=1,
            )[0].split(
                " SET ",
                maxsplit=1,
            )[0]

            assert "origin_definition" not in merge_clause

    def test_convert_annotation_to_changesets_no_vs(self) -> None:
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC_NO_VS,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) if x.change_type else ""
            for x in changesets
        ]
        expected = []
        assert_equal(actual, expected)

    def test_convert_annotation_to_changesets_with_removed_pvs(self) -> None:
        """Test that removed PVs generate DELETE statements for relationships only."""
        # Create annotation with removed_pvs (with origin_id)
        annotation_with_removed_pvs = TEST_ANNOTATION_SPEC.copy()
        annotation_with_removed_pvs["removed_pvs"] = [  # type: ignore
            {"value": "Mouse", "origin_id": "2578400", "origin_version": "1"},
            {"value": "Dog", "origin_id": "5729587", "origin_version": "1"},
        ]
        
        changesets = convert_annotation_to_changesets(
            annotation_with_removed_pvs,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) if x.change_type else ""
            for x in changesets
        ]
        
        # Check that DELETE statements are present for removed PVs (deletes relationship only)
        # Uses composite key for matching (origin_id + value + origin_version, within value_set)
        delete_statements = [stmt for stmt in actual if "DELETE r" in stmt]
        assert any(
            'coalesce(pv.origin_id, \'\') = "2578400"' in stmt
            for stmt in delete_statements
        )
        assert any(
            'coalesce(pv.origin_id, \'\') = "5729587"' in stmt
            for stmt in delete_statements
        )
        assert any(
            'coalesce(pv.value, \'\') = "Mouse"' in stmt
            for stmt in delete_statements
        )
        assert any(
            'coalesce(pv.value, \'\') = "Dog"' in stmt
            for stmt in delete_statements
        )
        assert all(
            "coalesce(pv.origin_version, '')" in stmt
            for stmt in delete_statements
        )
        assert all(
            "toLower(coalesce(pv.origin_name, '')) "
            "CONTAINS 'cadsr'" in stmt
            for stmt in delete_statements
        )
        assert not any("DELETE r, pv" in stmt for stmt in delete_statements)

    def test_convert_annotation_to_changesets_with_cde_name_change(
    self,
) -> None:
        """A CDE name change updates metadata without changing VS identity."""
        annotation_with_name_change = {
            "entity": {},
            "annotation": {
                "key": ("Old Name", "caDSR"),
                "attrs": {
                    "origin_id": "12345",
                    "origin_version": "1.0",
                    "origin_name": "caDSR",
                    "value": "Old Name",
                },
            },
            "value_set": [],
            "CDEFullName": "New CDE Name",
        }

        changesets = convert_annotation_to_changesets(
            annotation_with_name_change,  # type: ignore
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = get_changeset_texts(changesets)

        assert len(actual) == 2

        assert_cde_value_set_merge(
            actual[0],
            handle="12345|1.0",
            expected_url=(
                "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/"
                "api/DataElement/12345?version=1.0"
            ),
        )

        assert "MATCH (t:term" in actual[1]
        assert "origin_id: '12345'" in actual[1]
        assert "toLower(t.origin_name) CONTAINS 'cadsr'" in actual[1]
        assert 'SET t.value = "New CDE Name"' in actual[1]

    def test_convert_annotation_to_changesets_with_name_and_version_change(
    self,
) -> None:
        """A CDE version change uses the new versioned value-set identity."""
        annotation_with_both_changes = {
            "entity": {},
            "annotation": {
                "key": ("Old Name", "caDSR"),
                "attrs": {
                    "origin_id": "12345",
                    "origin_version": "1.0",
                    "origin_name": "caDSR",
                    "value": "Old Name",
                },
            },
            "value_set": [],
            "CDEFullName": "New Name",
            "CDEVersion": "2.0",
        }

        changesets = convert_annotation_to_changesets(
            annotation_with_both_changes,  # type: ignore
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = get_changeset_texts(changesets)

        assert len(actual) == 2

        assert_cde_value_set_merge(
            actual[0],
            handle="12345|2.0",
            expected_url=(
                "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/"
                "api/DataElement/12345?version=2.0"
            ),
        )

        assert 'SET t.value = "New Name"' in actual[1]

    def test_convert_annotation_to_changesets_only_removed_pvs_no_new_pvs(
    self,
) -> None:
        """Removed PVs should unlink even when no new PVs exist."""
        annotation_only_removed = {
            "entity": {},
            "annotation": {
                "key": ("CDE Name", "caDSR"),
                "attrs": {
                    "origin_id": "12345",
                    "origin_version": "1.0",
                    "origin_name": "caDSR",
                    "value": "CDE Name",
                },
            },
            "value_set": [],
            "removed_pvs": [
                {
                    "value": "OldPV1",
                    "origin_id": "2559594",
                    "origin_version": "1",
                },
                {
                    "value": "OldPV2",
                    "origin_id": "2559595",
                    "origin_version": "2",
                },
            ],
        }

        changesets = convert_annotation_to_changesets(
            annotation_only_removed,  # type: ignore
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = get_changeset_texts(changesets)

        assert len(actual) == 3

        assert_cde_value_set_merge(
            actual[0],
            handle="12345|1.0",
            expected_url=(
                "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/"
                "api/DataElement/12345?version=1.0"
            ),
        )

        delete_statements = [
            stmt for stmt in actual
            if stmt.endswith("DELETE r")
        ]

        assert len(delete_statements) == 2
        assert any("2559594" in stmt for stmt in delete_statements)
        assert any("OldPV1" in stmt for stmt in delete_statements)
        assert any("2559595" in stmt for stmt in delete_statements)
        assert any("OldPV2" in stmt for stmt in delete_statements)
        assert all("DELETE r, pv" not in stmt for stmt in delete_statements)

    def test_convert_annotation_to_changesets_skip_removed_pv_without_origin_version(
    self,
) -> None:
        """A removed PV without a version should not be unlinked ambiguously."""
        annotation_only_removed = {
            "entity": {},
            "annotation": {
                "key": ("CDE Name", "caDSR"),
                "attrs": {
                    "origin_id": "12345",
                    "origin_version": "1.0",
                    "origin_name": "caDSR",
                    "value": "CDE Name",
                },
            },
            "value_set": [],
            "removed_pvs": [
                {
                    "value": "OldPV1",
                    "origin_id": "2559594",
                    "origin_version": "",
                },
                {
                    "value": "OldPV2",
                    "origin_id": "2559595",
                    "origin_version": "2",
                },
            ],
        }

        changesets = convert_annotation_to_changesets(
            annotation_only_removed,  # type: ignore
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = get_changeset_texts(changesets)

        assert len(actual) == 2

        assert_cde_value_set_merge(
            actual[0],
            handle="12345|1.0",
            expected_url=(
                "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/"
                "api/DataElement/12345?version=1.0"
            ),
        )

        delete_statements = [
            stmt for stmt in actual
            if stmt.endswith("DELETE r")
        ]

        assert len(delete_statements) == 1
        assert "2559595" in delete_statements[0]
        assert "OldPV2" in delete_statements[0]
        assert "2559594" not in delete_statements[0]
        assert "OldPV1" not in delete_statements[0]

class TestConvertModelCDES:
    def test_convert_model_cdes_to_changelog_id(self):
        changelog = convert_model_cdes_to_changelog(TEST_MODEL_CDE_SPEC)
        expected_ids = range(1, len(changelog.subelements) + 1)
        for expected, changeset in zip(expected_ids, changelog.subelements):
            assert_equal(changeset.id, str(expected))

    def test_convert_model_cdes_to_changelog_no_annotations(self):
        changelog = convert_model_cdes_to_changelog(TEST_MODEL_CDE_SPEC_NO_ANNOTATIONS)
        assert_equal(len(changelog.subelements), 0)

class TestConvertAnnotationToChangesetsEdp:
    """Tests for EDP-backed CDE annotations."""

    def test_edp_annotation_emits_specifies_value_set(self) -> None:
        """An annotation with edp_reference should emit a single specifies_value_set changeset."""
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC_EDP,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        assert len(changesets) == 1
        stmt = changesets[0].change_type.text
        assert "specifies_value_set" in stmt
        assert "11444542" in stmt   # CDE origin_id
        assert "CRDC00005" in stmt  # EDP origin_id
        assert "CRDC" in stmt       # EDP origin_name

    def test_edp_annotation_does_not_emit_value_set_merge(self) -> None:
        """An EDP annotation should not create a value_set node or has_term rels."""
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC_EDP,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        stmt = changesets[0].change_type.text
        assert "has_term" not in stmt
        assert "MERGE (n0:value_set" not in stmt
        
    def test_edp_annotation_cypher_structure(self) -> None:
        """The emitted Cypher should MATCH cde, MATCH edp->vs, MERGE the relationship."""
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC_EDP,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        stmt = changesets[0].change_type.text
        expected = (
            'MATCH (cde:term {origin_id: "11444542"}) '
            "WHERE toLower(cde.origin_name) CONTAINS 'cadsr' "
            'AND cde.origin_version = "2.00" '
            "MATCH (edp:term) "
            'WHERE edp.origin_name = "CRDC" '
            'AND edp.origin_id = "CRDC00005" '
            'AND edp.origin_version = "1" '
            "MATCH (edp)-[:specifies_value_set]->(vs:value_set) "
            "MERGE (cde)-[:specifies_value_set]->(vs)"
        )
        assert_equal(stmt, expected)

    def test_no_edp_reference_follows_normal_path(self) -> None:
        """An annotation without edp_reference should follow the normal PV path."""
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC_NO_VS,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        assert len(changesets) == 0  # no PVs, no EDP, nothing to emit