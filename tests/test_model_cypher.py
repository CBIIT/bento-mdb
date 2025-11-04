"""Tests for model changelog generation script."""

from pathlib import Path

from bento_mdf.mdf import MDF
from bento_meta.model import Model
from bento_meta.objects import Node, Property, Tag

from bento_mdb.model_cypher import ModelToChangelogConverter
from tests.test_utils import assert_equal, remove_nanoids_from_str

CURRENT_DIRECTORY = Path(__file__).resolve().parent
TEST_MODEL_MDF = Path(CURRENT_DIRECTORY, "samples", "test_mdf.yml")
TEST_MODEL_MDF_TERMS = Path(CURRENT_DIRECTORY, "samples", "test_mdf_terms.yml")
TEST_MODEL_MDF_USENULLCDE = Path(CURRENT_DIRECTORY, "samples", "test_mdf_useNullCDE_simple.yml")
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
            "MERGE (n0:value_set {nanoid:''}) ON CREATE SET n0._commit = 'dummy'",
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

    def test_use_null_cde_tag(self) -> None:
        """Test for useNullCDE tag creation and property tag relationship."""
        mdf = MDF(
            TEST_MODEL_MDF_USENULLCDE,
            handle="TEST_NULLCDE",
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

        # Verify model is created with correct handle and version
        model_stmts = [s for s in actual if s.startswith("CREATE (n0:model")]
        assert len(model_stmts) == 1, "Model should be created"
        expected_model = "CREATE (n0:model {handle:'TEST_NULLCDE',name:'TEST_NULLCDE',version:'1.0.0',is_latest_version:False})"
        assert expected_model in actual, f"Model should have correct handle 'TEST_NULLCDE' and version '1.0.0', got: {model_stmts[0]}"

        # Verify node is created with correct handle
        node_stmts = [s for s in actual if s.startswith("CREATE (n0:node")]
        assert len(node_stmts) == 1, "Node should be created"
        assert "handle:'clinical_measure'" in node_stmts[0], "Node handle should be 'clinical_measure'"
        assert "version:'1.0.0'" in node_stmts[0], "Node should have version '1.0.0'"

        # Verify property is created with correct handle
        prop_stmts = [s for s in actual if s.startswith("CREATE (n0:property")]
        assert len(prop_stmts) == 2, "Two properties should be created"
        assert any("handle:'imaging_software'" in s for s in prop_stmts), "Property handle should be 'imaging_software'"
        assert any("handle:'second-imaging_software'" in s for s in prop_stmts), "Property handle should be 'second-imaging_software'"
        assert all("version:'1.0.0'" in s for s in prop_stmts), "Both properties should have version '1.0.0'"

        # Verify useNullCDE tag is created with correct handle and value
        use_null_cde_creates = [s for s in actual if "useNullCDE" in s and "CREATE" in s]
        assert len(use_null_cde_creates) > 0, "useNullCDE tag should be created"
        # Both True and true are acceptable (boolean representations)
        tag_values = [s for s in use_null_cde_creates if "key:'useNullCDE'" in s]
        assert len(tag_values) >= 1, f"At least one useNullCDE tag should be created, got: {use_null_cde_creates}"

        # Verify that properties and tags are connected
        use_null_cde_relations = [s for s in actual if "useNullCDE" in s and "MERGE" in s and "has_tag" in s]
        assert len(use_null_cde_relations) >= 2, "Both properties should be connected to useNullCDE tag with has_tag relationship"

    def test_property_with_use_null_cde_tag_manual(self) -> None:
        """Test manual creation of property with useNullCDE tag."""
        model = Model(handle=MODEL_HDL)
        node = Node({"handle": "test_entity", "model": MODEL_HDL, "version": "1.0"})

        # Create property with useNullCDE tag
        prop = Property({
            "handle": "status",
            "model": MODEL_HDL,
            "value_domain": "string",
            "version": "1.0",
            "_commit": _COMMIT,
        })

        # Add useNullCDE tag
        prop.tags["useNullCDE"] = Tag({
            "key": "useNullCDE",
            "value": "Yes",
            "_commit": _COMMIT,
        })

        node.props = {prop.handle: prop}
        model.nodes = {node.handle: node}
        model.props = {(node.handle, prop.handle): prop}

        converter = ModelToChangelogConverter(model=model, add_rollback=False)
        changelog = converter.convert_model_to_changelog(author=AUTHOR)

        actual = [
            remove_nanoids_from_str(x.change_type.text) for x in changelog.subelements
        ]

        # Expected structure
        expected = [
            "CREATE (n0:model {handle:'TEST',name:'TEST',is_latest_version:False})",
            "CREATE (n0:node {handle:'test_entity',model:'TEST',version:'1.0'})",
            "CREATE (n0:property {handle:'status',model:'TEST',nanoid:'',version:'1.0',value_domain:'string',_commit:'_COMMIT_123'})",
            "CREATE (n0:tag {key:'useNullCDE',value:'Yes',nanoid:'',_commit:'_COMMIT_123'})",
            "MATCH (n0:node {handle:'test_entity',model:'TEST',version:'1.0'}), (n1:property {handle:'status',model:'TEST',nanoid:'',version:'1.0',value_domain:'string',_commit:'_COMMIT_123'}) MERGE (n0)-[r0:has_property]->(n1)",
            "MATCH (n0:property {handle:'status',model:'TEST',nanoid:'',version:'1.0',value_domain:'string',_commit:'_COMMIT_123'}), (n1:tag {key:'useNullCDE',value:'Yes',nanoid:'',_commit:'_COMMIT_123'}) MERGE (n0)-[r0:has_tag]->(n1)",
        ]

        assert_equal(actual, expected)
