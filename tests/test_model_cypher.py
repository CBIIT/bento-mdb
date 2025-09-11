"""Tests for model changelog generation script."""

from pathlib import Path

from bento_mdf.mdf import MDF
from bento_meta.model import Model
from bento_meta.objects import Node, Property

from bento_mdb_updates.model_cypher import ModelToChangelogConverter
from tests.test_utils import assert_equal, remove_nanoids_from_str

CURRENT_DIRECTORY = Path(__file__).resolve().parent
TEST_MODEL_MDF = Path(CURRENT_DIRECTORY, "samples", "test_mdf.yml")
TEST_MODEL_MDF_TERMS = Path(CURRENT_DIRECTORY, "samples", "test_mdf_terms.yml")
TEST_CHANGELOG_CONFIG = Path(CURRENT_DIRECTORY, "samples", "test_changelog.ini")
AUTHOR = "Tolkien"
MODEL_HDL = "TEST"
_COMMIT = "_COMMIT_123"


class TestMakeModelChangelog:
    """Tests for model changelog generation script."""

    def test_make_model_changelog_length(self) -> None:
        """Test for length of changelog generated from model MDF."""
        mdf = MDF(TEST_MODEL_MDF, handle=MODEL_HDL, _commit=_COMMIT, raise_error=True)
        converter = ModelToChangelogConverter(model=mdf.model, add_rollback=False)
        changelog = converter.convert_model_to_changelog(
            author=AUTHOR,
        )
        actual = len(changelog.subelements)
        expected = 52
        assert_equal(actual, expected)

    def test_make_model_changelog_shared_props(self) -> None:
        """Test for multiple nodes share property with the same handle."""
        model = Model(handle=MODEL_HDL)
        node_1 = Node({"handle": "cell_line", "model": MODEL_HDL})
        node_2 = Node({"handle": "clinical_measure_file", "model": MODEL_HDL})
        prop_1 = Property(
            {
                "handle": "id",
                "model": "TEST",
                "value_domain": "string",
                "desc": "desc of id",
            },
        )
        node_1.props = {prop_1.handle: prop_1}
        node_2.props = {prop_1.handle: prop_1}
        model.nodes = {node_1.handle: node_1, node_2.handle: node_2}
        model.props = {
            (node_1.handle, prop_1.handle): prop_1,
            (node_2.handle, prop_1.handle): prop_1,
        }
        converter = ModelToChangelogConverter(model=model, add_rollback=False)
        changelog = converter.convert_model_to_changelog(
            author=AUTHOR,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) for x in changelog.subelements
        ]
        expected = [
            "CREATE (n0:model {handle:'TEST',name:'TEST',is_latest_version:False})",
            "CREATE (n0:node {handle:'cell_line',model:'TEST'})",
            "CREATE (n0:property "
            "{handle:'id',model:'TEST',nanoid:'',value_domain:'string',desc:'desc of "
            "id'})",
            "CREATE (n0:node {handle:'clinical_measure_file',model:'TEST'})",
            "CREATE (n0:property "
            "{handle:'id',model:'TEST',nanoid:'',value_domain:'string',desc:'desc of "
            "id'})",
            "MATCH (n0:node {handle:'cell_line',model:'TEST'}), (n1:property "
            "{handle:'id',model:'TEST',nanoid:'',value_domain:'string',desc:'desc of "
            "id'}) MERGE (n0)-[r0:has_property]->(n1)",
            "MATCH (n0:node {handle:'clinical_measure_file',model:'TEST'}), "
            "(n1:property {handle:'id',model:'TEST',nanoid:'',value_domain:'string',"
            "desc:'desc of id'}) MERGE (n0)-[r0:has_property]->(n1)",
        ]
        assert_equal(actual, expected)

    def test_shared_props_with_value_set(self) -> None:
        """Test for shared properties with value_set."""
        mdf = MDF(
            TEST_MODEL_MDF_TERMS,
            handle=MODEL_HDL,
            _commit=_COMMIT,
            raise_error=True,
        )
        converter = ModelToChangelogConverter(model=mdf.model, add_rollback=False)
        changelog = converter.convert_model_to_changelog(
            author=AUTHOR,
        )
        actual = [
            remove_nanoids_from_str(x.change_type.text) for x in changelog.subelements
        ]
        expected = [
            "CREATE (n0:model {handle:'TEST',name:'TEST',version:'1.2.3',"
            "is_latest_version:False})",
            "CREATE (n0:node {handle:'file',model:'TEST',version:'1.2.3',"
            "_commit:'_COMMIT_123'})",
            "CREATE (n0:property {handle:'file_type',model:'TEST',nanoid:'',"
            "version:'1.2.3',value_domain:'value_set',is_required:False,"
            "is_key:False,is_nullable:False,is_strict:True,"
            "_commit:'_COMMIT_123'})",
            "MERGE (n0:concept {nanoid:''}) ON CREATE SET n0._commit = '_COMMIT_123'",
            "CREATE (n0:tag {key:'mapping_source',value:'TEST',nanoid:''})",
            "MERGE (n0:term {handle:'file_type',value:'File Type',origin_name:'caDSR'})"
            " ON CREATE SET n0._commit = '_COMMIT_123'",
            "MERGE (n0:value_set {nanoid:''}) ON CREATE SET n0._commit = 'dummy'",
            "MERGE (n0:term {handle:'bam',value:'bam',origin_name:'TEST'})",
            "MERGE (n0:term {handle:'cram',value:'cram',origin_name:'TEST'})",
            "MERGE (n0:term {handle:'dict',value:'dict',origin_name:'TEST'})",
            "CREATE (n0:node {handle:'other_file',model:'TEST',version:'1.2.3',"
            "_commit:'_COMMIT_123'})",
            "CREATE (n0:property {handle:'file_type',model:'TEST',nanoid:'',"
            "version:'1.2.3',value_domain:'value_set',is_required:False,"
            "is_key:False,is_nullable:False,is_strict:True,"
            "_commit:'_COMMIT_123'})",
            "MERGE (n0:value_set {nanoid:''})",
            "MATCH (n0:node {handle:'file',model:'TEST',version:'1.2.3'"
            ",_commit:'_COMMIT_123'}), "
            "(n1:property {handle:'file_type',model:'TEST',nanoid:'',"
            "version:'1.2.3',value_domain:'value_set',is_required:False,"
            "is_key:False,is_nullable:False,is_strict:True,"
            "_commit:'_COMMIT_123'}) "
            "MERGE (n0)-[r0:has_property]->(n1)",
            "MATCH (n0:property {handle:'file_type',model:'TEST',nanoid:'',"
            "version:'1.2.3',value_domain:'value_set',is_required:False,"
            "is_key:False,is_nullable:False,is_strict:True"
            ",_commit:'_COMMIT_123'}), "
            "(n1:concept {nanoid:'',_commit:'_COMMIT_123'}) "
            "MERGE (n0)-[r0:has_concept]->(n1)",
            "MATCH (n0:concept {nanoid:'',_commit:'_COMMIT_123'}), "
            "(n1:tag {key:'mapping_source',value:'TEST',nanoid:''}) "
            "MERGE (n0)-[r0:has_tag]->(n1)",
            "MATCH (n0:term {handle:'file_type',value:'File Type',origin_name:'caDSR'})"
            ", (n1:concept {nanoid:'',_commit:'_COMMIT_123'}) "
            "MERGE (n0)-[r0:represents]->(n1)",
            "MATCH (n0:property {handle:'file_type',model:'TEST',nanoid:'',"
            "version:'1.2.3',value_domain:'value_set',is_required:False,"
            "is_key:False,is_nullable:False,is_strict:True,"
            "_commit:'_COMMIT_123'}), "
            "(n1:value_set {nanoid:''}) MERGE (n0)-[r0:has_value_set]->(n1)",
            "MATCH (n0:value_set {nanoid:''}), (n1:term {handle:'bam',value:'bam',"
            "origin_name:'TEST'}) MERGE (n0)-[r0:has_term]->(n1)",
            "MATCH (n0:value_set {nanoid:''}), (n1:term {handle:'cram',value:'cram',"
            "origin_name:'TEST'}) MERGE (n0)-[r0:has_term]->(n1)",
            "MATCH (n0:value_set {nanoid:''}), (n1:term {handle:'dict',value:'dict',"
            "origin_name:'TEST'}) MERGE (n0)-[r0:has_term]->(n1)",
            "MATCH (n0:node {handle:'other_file',model:'TEST',version:'1.2.3'"
            ",_commit:'_COMMIT_123'}), "
            "(n1:property {handle:'file_type',model:'TEST',nanoid:'',"
            "version:'1.2.3',value_domain:'value_set',is_required:False,"
            "is_key:False,is_nullable:False,is_strict:True,"
            "_commit:'_COMMIT_123'}) "
            "MERGE (n0)-[r0:has_property]->(n1)",
            "MATCH (n0:property {handle:'file_type',model:'TEST',nanoid:'',"
            "version:'1.2.3',value_domain:'value_set',is_required:False,"
            "is_key:False,is_nullable:False,is_strict:True,"
            "_commit:'_COMMIT_123'}), "
            "(n1:concept {nanoid:'',_commit:'_COMMIT_123'}) "
            "MERGE (n0)-[r0:has_concept]->(n1)",
            "MATCH (n0:concept {nanoid:'',_commit:'_COMMIT_123'}), "
            "(n1:tag {key:'mapping_source',value:'TEST',nanoid:''}) "
            "MERGE (n0)-[r0:has_tag]->(n1)",
            "MATCH (n0:term {handle:'file_type',value:'File Type',"
            "origin_name:'caDSR'}), (n1:concept {nanoid:'',_commit:'_COMMIT_123'}) "
            "MERGE (n0)-[r0:represents]->(n1)",
            "MATCH (n0:property {handle:'file_type',model:'TEST',nanoid:'',"
            "version:'1.2.3',value_domain:'value_set',is_required:False,"
            "is_key:False,is_nullable:False,is_strict:True,"
            "_commit:'_COMMIT_123'}), "
            "(n1:value_set {nanoid:''}) MERGE (n0)-[r0:has_value_set]->(n1)",
            "MATCH (n0:value_set {nanoid:''}), (n1:term {handle:'bam',value:'bam',"
            "origin_name:'TEST'}) MERGE (n0)-[r0:has_term]->(n1)",
            "MATCH (n0:value_set {nanoid:''}), (n1:term {handle:'cram',value:'cram',"
            "origin_name:'TEST'}) MERGE (n0)-[r0:has_term]->(n1)",
            "MATCH (n0:value_set {nanoid:''}), (n1:term {handle:'dict',value:'dict',"
            "origin_name:'TEST'}) MERGE (n0)-[r0:has_term]->(n1)",
        ]
        assert_equal(actual, expected)
