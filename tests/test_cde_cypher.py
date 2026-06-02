"""Tests for cde changelog generation script."""

from bento_mdb.cde_cypher import (
    create_delete_pv_cypher,
    convert_annotation_to_changesets,
    convert_model_cdes_to_changelog,
)
from tests.test_utils import (
    TEST_ANNOTATION_SPEC,
    TEST_ANNOTATION_SPEC_MIN,
    TEST_ANNOTATION_SPEC_NO_VS,
    TEST_MODEL_CDE_SPEC,
    TEST_MODEL_CDE_SPEC_NO_ANNOTATIONS,
    assert_equal,
    remove_nanoids_from_str,
)

TEST_COMMIT = "CDEPV-TEST"
TEST_AUTHOR = "TOLKIEN"


def test_create_delete_pv_cypher_escapes_single_quotes() -> None:
    actual = create_delete_pv_cypher("Children's Hospital", "123", "1", "456", "2")
    expected = (
        "MATCH (pv:term)-[r:has_term]-(vs:value_set {handle: '456|2'}) "
        "WHERE toLower(pv.origin_name) CONTAINS 'cadsr' "
        "AND pv.origin_id = '123' "
        "AND pv.value = 'Children''s Hospital' "
        "AND coalesce(pv.origin_version, '') = '1' "
        "DELETE r"
    )
    assert_equal(actual, expected)


class TestConvertAnnotationToChangesets:
    """Tests for convert_annotation_to_changesets."""

    def test_convert_annotation_to_changesets(self) -> None:
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) if x.change_type else ""
            for x in changesets
        ]
        expected = [
            "MERGE (n0:value_set {handle:'6118266|1.00',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/6118266?version=1.00'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MERGE (n0:term {value:'Mouse',origin_id:'2578400',origin_version:'1',origin_definition:'Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.',origin_name:'caDSR'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (n0:value_set {handle:'6118266|1.00',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/6118266?version=1.00'}), (n1:term {value:'Mouse',origin_id:'2578400',origin_version:'1',origin_definition:'Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.',origin_name:'caDSR'}) MERGE (n0)-[r0:has_term]->(n1)",
            "MERGE (n0:term {value:'Mouse',origin_id:'C14238',origin_definition:'Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.',origin_name:'NCIt'})",
            "MATCH (n0:term {value:'Mouse',origin_id:'2578400',origin_version:'1',origin_definition:'Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.',origin_name:'caDSR'}), (n1:term {value:'Mouse',origin_id:'C14238',origin_definition:'Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.',origin_name:'NCIt'}) WHERE (n0)  <>  (n1) WITH (n0), (n1) OPTIONAL MATCH (n0)-[r0:represents]->(n2:concept)-[r2:has_tag]->(n4:tag {key:'mapping_source',value:'caDSR'}) WITH (n0), (n1), (n2) LIMIT 1 OPTIONAL MATCH (n1)-[r1:represents]->(n3:concept)-[r3:has_tag]->(n5:tag {key:'mapping_source',value:'caDSR'}) WITH (n0), (n1), (n2), (n3) LIMIT 1 WITH (n0), (n1) , CASE WHEN (n2) IS NOT NULL THEN (n2) WHEN (n3) IS NOT NULL THEN (n3) ELSE NULL END AS existing_concept  FOREACH  (_ IN CASE WHEN existing_concept IS NOT NULL THEN [1] ELSE [] END | MERGE (n0)-[:represents]->(existing_concept) MERGE (n1)-[:represents]->(existing_concept) ) FOREACH  (_ IN CASE WHEN existing_concept IS NULL THEN [1] ELSE [] END | CREATE (n6:concept {_commit:'CDEPV-TEST'}) CREATE (n6)-[r4:has_tag]->(n7:tag {key:'mapping_source',value:'caDSR'}) CREATE (n0)-[r5:represents]->(n6) CREATE (n1)-[r6:represents]->(n6) )",
            "MERGE (n0:term {value:'Mus',origin_id:'447482001',origin_version:'2024_03_01',origin_name:'SNOMEDCT_US'})",
            "MATCH (n0:term {value:'Mouse',origin_id:'C14238',origin_definition:'Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.',origin_name:'NCIt'}), (n1:term {value:'Mus',origin_id:'447482001',origin_version:'2024_03_01',origin_name:'SNOMEDCT_US'}) WHERE (n0)  <>  (n1) WITH (n0), (n1) OPTIONAL MATCH (n0)-[r0:represents]->(n2:concept)-[r2:has_tag]->(n4:tag {key:'mapping_source',value:'NCIm'}) WITH (n0), (n1), (n2) LIMIT 1 OPTIONAL MATCH (n1)-[r1:represents]->(n3:concept)-[r3:has_tag]->(n5:tag {key:'mapping_source',value:'NCIm'}) WITH (n0), (n1), (n2), (n3) LIMIT 1 WITH (n0), (n1) , CASE WHEN (n2) IS NOT NULL THEN (n2) WHEN (n3) IS NOT NULL THEN (n3) ELSE NULL END AS existing_concept  FOREACH  (_ IN CASE WHEN existing_concept IS NOT NULL THEN [1] ELSE [] END | MERGE (n0)-[:represents]->(existing_concept) MERGE (n1)-[:represents]->(existing_concept) ) FOREACH  (_ IN CASE WHEN existing_concept IS NULL THEN [1] ELSE [] END | CREATE (n6:concept {_commit:'CDEPV-TEST'}) CREATE (n6)-[r4:has_tag]->(n7:tag {key:'mapping_source',value:'NCIm'}) CREATE (n0)-[r5:represents]->(n6) CREATE (n1)-[r6:represents]->(n6) )",
            # Alternates for PV (nanoid field removed from source implementation)
            "MERGE (n0:term {value:'Murine',origin_id:'2578400',origin_version:'1',origin_name:'caDSR_alternates'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (n0:term {value:'Mouse',origin_id:'2578400',origin_version:'1',origin_definition:'Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.',origin_name:'caDSR'}), (n1:term {value:'Murine',origin_id:'2578400',origin_version:'1',origin_name:'caDSR_alternates'}) WHERE (n0)  <>  (n1) WITH (n0), (n1) OPTIONAL MATCH (n0)-[r0:represents]->(n2:concept)-[r1:has_tag]->(n3:tag {key:'mapping_source',value:'alternate_name'}) WITH (n0), (n1), (n2) LIMIT 1 WITH (n0), (n1) , CASE WHEN (n2) IS NOT NULL THEN (n2) ELSE NULL END AS existing_concept  FOREACH  (_ IN CASE WHEN existing_concept IS NOT NULL THEN [1] ELSE [] END | MERGE (n0)-[:represents]->(existing_concept) MERGE (n1)-[:represents]->(existing_concept) ) FOREACH  (_ IN CASE WHEN existing_concept IS NULL THEN [1] ELSE [] END | CREATE (n4:concept {_commit:'CDEPV-TEST'}) CREATE (n4)-[r2:has_tag]->(n5:tag {key:'mapping_source',value:'alternate_name'}) CREATE (n0)-[r3:represents]->(n4) CREATE (n1)-[r4:represents]->(n4) )",
            "MERGE (n0:term {value:'Rodent',origin_id:'2578400',origin_version:'1',origin_name:'caDSR_alternates'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (n0:term {value:'Mouse',origin_id:'2578400',origin_version:'1',origin_definition:'Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.',origin_name:'caDSR'}), (n1:term {value:'Rodent',origin_id:'2578400',origin_version:'1',origin_name:'caDSR_alternates'}) WHERE (n0)  <>  (n1) WITH (n0), (n1) OPTIONAL MATCH (n0)-[r0:represents]->(n2:concept)-[r1:has_tag]->(n3:tag {key:'mapping_source',value:'alternate_name'}) WITH (n0), (n1), (n2) LIMIT 1 WITH (n0), (n1) , CASE WHEN (n2) IS NOT NULL THEN (n2) ELSE NULL END AS existing_concept  FOREACH  (_ IN CASE WHEN existing_concept IS NOT NULL THEN [1] ELSE [] END | MERGE (n0)-[:represents]->(existing_concept) MERGE (n1)-[:represents]->(existing_concept) ) FOREACH  (_ IN CASE WHEN existing_concept IS NULL THEN [1] ELSE [] END | CREATE (n4:concept {_commit:'CDEPV-TEST'}) CREATE (n4)-[r2:has_tag]->(n5:tag {key:'mapping_source',value:'alternate_name'}) CREATE (n0)-[r3:represents]->(n4) CREATE (n1)-[r4:represents]->(n4) )",
            "MERGE (n0:term {value:'Human',origin_id:'2620875',origin_version:'1',origin_definition:'The bipedal primate mammal, Homo sapiens; belonging to man or mankind; pertaining to man or to the race of man; use of man as experimental subject or unit of analysis in research.',origin_name:'caDSR'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (n0:value_set {handle:'6118266|1.00',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/6118266?version=1.00'}), (n1:term {value:'Human',origin_id:'2620875',origin_version:'1',origin_definition:'The bipedal primate mammal, Homo sapiens; belonging to man or mankind; pertaining to man or to the race of man; use of man as experimental subject or unit of analysis in research.',origin_name:'caDSR'}) MERGE (n0)-[r0:has_term]->(n1)",
            "MERGE (n0:term {value:'Human',origin_id:'C14225',origin_definition:'The bipedal primate mammal, Homo sapiens; belonging to man or mankind; pertaining to man or to the race of man; use of man as experimental subject or unit of analysis in research.',origin_name:'NCIt'})",
            "MATCH (n0:term {value:'Human',origin_id:'2620875',origin_version:'1',origin_definition:'The bipedal primate mammal, Homo sapiens; belonging to man or mankind; pertaining to man or to the race of man; use of man as experimental subject or unit of analysis in research.',origin_name:'caDSR'}), (n1:term {value:'Human',origin_id:'C14225',origin_definition:'The bipedal primate mammal, Homo sapiens; belonging to man or mankind; pertaining to man or to the race of man; use of man as experimental subject or unit of analysis in research.',origin_name:'NCIt'}) WHERE (n0)  <>  (n1) WITH (n0), (n1) OPTIONAL MATCH (n0)-[r0:represents]->(n2:concept)-[r2:has_tag]->(n4:tag {key:'mapping_source',value:'caDSR'}) WITH (n0), (n1), (n2) LIMIT 1 OPTIONAL MATCH (n1)-[r1:represents]->(n3:concept)-[r3:has_tag]->(n5:tag {key:'mapping_source',value:'caDSR'}) WITH (n0), (n1), (n2), (n3) LIMIT 1 WITH (n0), (n1) , CASE WHEN (n2) IS NOT NULL THEN (n2) WHEN (n3) IS NOT NULL THEN (n3) ELSE NULL END AS existing_concept  FOREACH  (_ IN CASE WHEN existing_concept IS NOT NULL THEN [1] ELSE [] END | MERGE (n0)-[:represents]->(existing_concept) MERGE (n1)-[:represents]->(existing_concept) ) FOREACH  (_ IN CASE WHEN existing_concept IS NULL THEN [1] ELSE [] END | CREATE (n6:concept {_commit:'CDEPV-TEST'}) CREATE (n6)-[r4:has_tag]->(n7:tag {key:'mapping_source',value:'caDSR'}) CREATE (n0)-[r5:represents]->(n6) CREATE (n1)-[r6:represents]->(n6) )",
            "MERGE (n0:term {value:'Dog',origin_id:'5729587',origin_version:'1',origin_definition:'The domestic dog, Canis familiaris.',origin_name:'caDSR'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (n0:value_set {handle:'6118266|1.00',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/6118266?version=1.00'}), (n1:term {value:'Dog',origin_id:'5729587',origin_version:'1',origin_definition:'The domestic dog, Canis familiaris.',origin_name:'caDSR'}) MERGE (n0)-[r0:has_term]->(n1)",
        ]
        assert_equal(actual, expected)

    def test_convert_annotation_to_changesets_min(self) -> None:
        changesets = convert_annotation_to_changesets(
            TEST_ANNOTATION_SPEC_MIN,
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) if x.change_type else ""
            for x in changesets
        ]
        expected = [
            "MERGE (n0:value_set {handle:'11524549|',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/11524549'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MERGE (n0:term {value:'Pediatric',origin_id:'2597927',origin_version:'1',origin_definition:'Having to do with children.',origin_name:'caDSR'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (n0:value_set {handle:'11524549|',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/11524549'}), (n1:term {value:'Pediatric',origin_id:'2597927',origin_version:'1',origin_definition:'Having to do with children.',origin_name:'caDSR'}) MERGE (n0)-[r0:has_term]->(n1)",
            "MERGE (n0:term {value:'Adult - legal age',origin_id:'11524542',origin_version:'1',origin_definition:'A person of legal age to consent to a procedure as specified by local regulation.',origin_name:'caDSR'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (n0:value_set {handle:'11524549|',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/11524549'}), (n1:term {value:'Adult - legal age',origin_id:'11524542',origin_version:'1',origin_definition:'A person of legal age to consent to a procedure as specified by local regulation.',origin_name:'caDSR'}) MERGE (n0)-[r0:has_term]->(n1)",
        ]
        assert_equal(actual, expected)

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
        assert len(delete_statements) >= 2
        assert any("pv.origin_id = '2578400'" in stmt for stmt in delete_statements)
        assert any("pv.origin_id = '5729587'" in stmt for stmt in delete_statements)
        assert any("pv.value = 'Mouse'" in stmt for stmt in delete_statements)
        assert any("pv.value = 'Dog'" in stmt for stmt in delete_statements)
        assert all("coalesce(pv.origin_version, '')" in stmt for stmt in delete_statements)
        # Verify it has origin_name check
        assert all("toLower(pv.origin_name) CONTAINS 'cadsr'" in stmt for stmt in delete_statements)
        # Verify it's not deleting the node itself
        assert not any("DELETE r, pv" in stmt for stmt in delete_statements)

    def test_convert_annotation_to_changesets_with_cde_name_change(self) -> None:
        """Test that CDEFullName change generates UPDATE statement for Term."""
        # Create annotation with only CDEFullName change (no new PVs)
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
            "CDEFullName": "New CDE Name",  # type: ignore
        }
        
        changesets = convert_annotation_to_changesets(
            annotation_with_name_change,  # type: ignore
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) if x.change_type else ""
            for x in changesets
        ]
        
        expected = [
            "MERGE (n0:value_set {handle:'12345|1.0',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/12345?version=1.0'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (t:term {origin_id: '12345'}) WHERE toLower(t.origin_name) CONTAINS 'cadsr' SET t.value = 'New CDE Name'",
        ]
        assert_equal(actual, expected)

    def test_convert_annotation_to_changesets_with_name_and_version_change(self) -> None:
        """Test that both CDEFullName and CDEVersion changes update Term correctly."""
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
            "CDEFullName": "New Name",  # type: ignore
            "CDEVersion": "2.0",  # type: ignore
        }
        
        changesets = convert_annotation_to_changesets(
            annotation_with_both_changes,  # type: ignore
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) if x.change_type else ""
            for x in changesets
        ]
        
        expected = [
            "MERGE (n0:value_set {handle:'12345|2.0',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/12345?version=2.0'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (t:term {origin_id: '12345'}) WHERE toLower(t.origin_name) CONTAINS 'cadsr' SET t.value = 'New Name'",
        ]
        assert_equal(actual, expected)

    def test_convert_annotation_to_changesets_only_removed_pvs_no_new_pvs(self) -> None:
        """Test that removed PVs without new PVs still generates changesets."""
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
            "value_set": [],  # No new PVs
            "removed_pvs": [  # type: ignore
                {"value": "OldPV1", "origin_id": "2559594", "origin_version": "1"},
                {"value": "OldPV2", "origin_id": "2559595", "origin_version": "2"},
            ],
        }
        
        changesets = convert_annotation_to_changesets(
            annotation_only_removed,  # type: ignore
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) if x.change_type else ""
            for x in changesets
        ]
        
        expected = [
            "MERGE (n0:value_set {handle:'12345|1.0',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/12345?version=1.0'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (pv:term)-[r:has_term]-(vs:value_set {handle: '12345|1.0'}) WHERE toLower(pv.origin_name) CONTAINS 'cadsr' AND pv.origin_id = '2559594' AND pv.value = 'OldPV1' AND coalesce(pv.origin_version, '') = '1' DELETE r",
            "MATCH (pv:term)-[r:has_term]-(vs:value_set {handle: '12345|1.0'}) WHERE toLower(pv.origin_name) CONTAINS 'cadsr' AND pv.origin_id = '2559595' AND pv.value = 'OldPV2' AND coalesce(pv.origin_version, '') = '2' DELETE r",
        ]
        assert_equal(actual, expected)

    def test_convert_annotation_to_changesets_skip_removed_pv_without_origin_version(self) -> None:
        """Removed PV with empty origin_version should be skipped for unlink."""
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
            "removed_pvs": [  # type: ignore
                {"value": "OldPV1", "origin_id": "2559594", "origin_version": ""},
                {"value": "OldPV2", "origin_id": "2559595", "origin_version": "2"},
            ],
        }

        changesets = convert_annotation_to_changesets(
            annotation_only_removed,  # type: ignore
            1,
            TEST_AUTHOR,
            TEST_COMMIT,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) if x.change_type else ""
            for x in changesets
        ]

        expected = [
            "MERGE (n0:value_set {handle:'12345|1.0',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/12345?version=1.0'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (pv:term)-[r:has_term]-(vs:value_set {handle: '12345|1.0'}) WHERE toLower(pv.origin_name) CONTAINS 'cadsr' AND pv.origin_id = '2559595' AND pv.value = 'OldPV2' AND coalesce(pv.origin_version, '') = '2' DELETE r",
        ]
        assert_equal(actual, expected)


class TestConvertModelCDES:
    def test_convert_model_cdes_to_changelog_id(self):
        changelog = convert_model_cdes_to_changelog(TEST_MODEL_CDE_SPEC)
        expected_ids = range(1, len(changelog.subelements) + 1)
        for expected, changeset in zip(expected_ids, changelog.subelements):
            assert_equal(changeset.id, str(expected))

    def test_convert_model_cdes_to_changelog_no_annotations(self):
        changelog = convert_model_cdes_to_changelog(TEST_MODEL_CDE_SPEC_NO_ANNOTATIONS)
        assert_equal(len(changelog.subelements), 0)
