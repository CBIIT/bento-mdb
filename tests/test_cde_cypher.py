"""Tests for cde changelog generation script."""

from bento_mdb_updates.cde_cypher import (
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
            "MERGE (n0:term {value:'Adult - legal age',origin_id:'11524542',origin_version:'1',origin_definition:'A person of legal age to consent to a procedure as specifed by local regulation.',origin_name:'caDSR'}) ON CREATE SET n0._commit = 'CDEPV-TEST'",
            "MATCH (n0:value_set {handle:'11524549|',url:'https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/11524549'}), (n1:term {value:'Adult - legal age',origin_id:'11524542',origin_version:'1',origin_definition:'A person of legal age to consent to a procedure as specifed by local regulation.',origin_name:'caDSR'}) MERGE (n0)-[r0:has_term]->(n1)",
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


class TestConvertModelCDES:
    def test_convert_model_cdes_to_changelog_id(self):
        changelog = convert_model_cdes_to_changelog(TEST_MODEL_CDE_SPEC)
        expected_ids = range(1, len(changelog.subelements) + 1)
        for expected, changeset in zip(expected_ids, changelog.subelements):
            assert_equal(changeset.id, str(expected))

    def test_convert_model_cdes_to_changelog_no_annotations(self):
        changelog = convert_model_cdes_to_changelog(TEST_MODEL_CDE_SPEC_NO_ANNOTATIONS)
        assert_equal(len(changelog.subelements), 0)
