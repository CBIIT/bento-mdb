"""Tests for diff changelog generation script."""

from __future__ import annotations

from pathlib import Path

from bento_mdf.diff import diff_models
from bento_mdf.mdf import MDF
from bento_meta.objects import Concept, Property, Tag, Term, ValueSet

from src.changelog_utils import update_config_changeset_id
from src.make_diff_changelog import DiffSplitter, convert_diff_to_changelog

CURRENT_DIRECTORY = Path(__file__).resolve().parent
TEST_MDF = Path(CURRENT_DIRECTORY, "samples", "test_mdf.yml")
TEST_MDF_DIFF = Path(CURRENT_DIRECTORY, "samples", "test_mdf_diff.yml")
TEST_MAPPING_MDF = Path(CURRENT_DIRECTORY, "samples", "test_mapping_mdf.yml")
TEST_CHANGELOG_CONFIG = Path(CURRENT_DIRECTORY, "samples", "test_changelog.ini")
AUTHOR = "Tolkien"
MODEL_HDL = "TEST"
_COMMIT = "_COMMIT_123"
NODES = "nodes"
EDGES = "edges"
PROPS = "props"
TERMS = "terms"
NODE_HANDLE_1 = "subject"
NODE_HANDLE_2 = "diagnosis"
EDGE_HANDLE = "of_subject"
EDGE_KEY = (EDGE_HANDLE, NODE_HANDLE_2, NODE_HANDLE_1)
PROP_HANDLE_1 = "primary_disease_site"
PROP_KEY = (PROP_HANDLE_1, NODE_HANDLE_2)
PROP_HANDLE_2 = "id"
TERM_VALUE_1 = "Lung"
TERM_ORIGIN_1 = "NCIt"
TERM_KEY = (TERM_VALUE_1, TERM_ORIGIN_1)
TERM_VALUE_2 = "Kidney"
TERM_ORIGIN_2 = "NCIm"
TERM_KEY = (TERM_VALUE_2, TERM_ORIGIN_2)


def test_make_diff_changelog_length() -> None:
    mdf_old = MDF(TEST_MDF, handle=MODEL_HDL, _commit=_COMMIT, raiseError=True)
    mdf_new = MDF(TEST_MDF_DIFF, handle=MODEL_HDL, _commit=_COMMIT, raiseError=True)
    diff = diff_models(mdl_a=mdf_old.model, mdl_b=mdf_new.model)
    changelog = convert_diff_to_changelog(
        diff=diff,
        model_handle=MODEL_HDL,
        author=AUTHOR,
        config_file_path=TEST_CHANGELOG_CONFIG,
    )
    update_config_changeset_id(TEST_CHANGELOG_CONFIG, 1)
    actual_changelog_length = len(changelog.subelements)
    expected_changelog_length = 39
    assert actual_changelog_length == expected_changelog_length


class TestGetDiffStatements:
    """Test diff statements generation."""

    SIMP_ATT = "nanoid"
    SIMP_ATT_1 = "abc123"
    SIMP_ATT_2 = "def456"
    OBJ_ATT_C = "concept"
    OBJ_ATT_C1 = Concept({"nanoid": "abc123"})
    OBJ_ATT_C2 = Concept({"nanoid": "def456"})
    OBJ_ATT_V = "value_set"
    OBJ_ATT_V1 = ValueSet({"handle": "vs252"})
    OBJ_ATT_V2 = ValueSet({"handle": "vs596"})
    TERM_1 = Term({"value": TERM_VALUE_1, "origin_name": TERM_ORIGIN_1})
    TERM_2 = Term({"value": TERM_VALUE_2, "origin_name": TERM_ORIGIN_2})
    OBJ_ATT_C1.terms[TERM_VALUE_1] = TERM_1  # type: ignore reportOptionalSubscript
    OBJ_ATT_C2.terms[TERM_VALUE_2] = TERM_2  # type: ignore reportOptionalSubscript
    OBJ_ATT_V1.terms[TERM_VALUE_1] = TERM_1  # type: ignore reportOptionalSubscript
    OBJ_ATT_V2.terms[TERM_VALUE_2] = TERM_2  # type: ignore reportOptionalSubscript
    COLL_ATT_P = "props"
    COLL_ATT_P1 = Property({"handle": PROP_HANDLE_1, "_parent_handle": NODE_HANDLE_2})
    COLL_ATT_P2 = Property({"handle": PROP_HANDLE_2, "_parent_handle": NODE_HANDLE_1})
    COLL_ATT_T = "tags"
    COLL_ATT_T1 = Tag({"key": "class", "value": "primary"})
    COLL_ATT_T2 = Tag({"key": "class", "value": "secondary"})

    def assert_diff_as_expected(
        self,
        diff: dict,
        expected: list[tuple[str, str]],
    ) -> None:
        """Test diff statements generation."""
        splitter = DiffSplitter(diff=diff, model_handle=MODEL_HDL)
        actual = [
            (str(stmt), str(rlbk)) for (stmt, rlbk) in splitter.get_diff_statements()
        ]
        print(f"{actual=}\n{expected=}")  # noqa: T201
        assert actual == expected

    def test_add_node_nanoid(self) -> None:
        """Test adding nanoid to a node."""
        self.assert_diff_as_expected(
            diff={
                NODES: {
                    "changed": {
                        NODE_HANDLE_1: {
                            self.SIMP_ATT: {"added": self.SIMP_ATT_2, "removed": None},
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n0:node {handle:'subject',model:'TEST'}) "
                        "SET n0.nanoid = 'def456'"
                    ),
                    "MATCH (n0:node {handle:'subject',model:'TEST'}) REMOVE n0.nanoid",
                ),
            ],
        )

    def test_remove_edge_nanoid(self) -> None:
        """Test removing nanoid from an edge."""
        self.assert_diff_as_expected(
            diff={
                EDGES: {
                    "changed": {
                        EDGE_KEY: {
                            self.SIMP_ATT: {"added": None, "removed": self.SIMP_ATT_1},
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n3:node {handle:'subject',model:'TEST'})<-[r1:has_dst]-"
                        "(n0:relationship {handle:'of_subject',model:'TEST'})"
                        "-[r0:has_src]->(n2:node {handle:'diagnosis',model:'TEST'}) "
                        "REMOVE n0.nanoid"
                    ),
                    (
                        "MATCH (n3:node {handle:'subject',model:'TEST'})<-[r1:has_dst]-"
                        "(n0:relationship {handle:'of_subject',model:'TEST'})"
                        "-[r0:has_src]->(n2:node {handle:'diagnosis',model:'TEST'}) "
                        "SET n0.nanoid = 'abc123'"
                    ),
                ),
            ],
        )

    def test_change_prop_nanoid(self) -> None:
        """Test changing nanoid of a property."""
        self.assert_diff_as_expected(
            diff={
                PROPS: {
                    "changed": {
                        PROP_KEY: {
                            self.SIMP_ATT: {
                                "added": self.SIMP_ATT_2,
                                "removed": self.SIMP_ATT_1,
                            },
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r0:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) "
                        "SET n0.nanoid = 'def456'"
                    ),
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r0:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) "
                        "SET n0.nanoid = 'abc123'"
                    ),
                ),
            ],
        )

    def test_add_prop_value_set(self) -> None:
        """Test adding term to value set to a property."""
        self.assert_diff_as_expected(
            diff={
                PROPS: {
                    "changed": {
                        PROP_KEY: {
                            self.OBJ_ATT_V: {
                                "added": {self.TERM_2.value: self.TERM_2},
                                "removed": None,
                            },
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n2 {handle:'primary_disease_site'})-[r1:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) "
                        "MERGE (n0)-[r0:has_value_set]->(n1:value_set)"
                    ),
                    (
                        "MATCH (n2 {handle:'primary_disease_site'})-[r1:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) DELETE r0"
                    ),
                ),
                (
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Kidney',origin_name:'NCIm'}) "
                        "MERGE (n1)-[r1:has_term]->(n2)"
                    ),
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Kidney',origin_name:'NCIm'}) , "
                        "(n1)-[r1:has_term]->(n2) "
                        "DELETE r1"
                    ),
                ),
            ],
        )

    def test_add_two_terms_to_prop(self) -> None:
        """Test adding two terms to a property's value set."""
        self.assert_diff_as_expected(
            diff={
                PROPS: {
                    "changed": {
                        PROP_KEY: {
                            self.OBJ_ATT_V: {
                                "added": {
                                    self.TERM_1.value: self.TERM_1,
                                    self.TERM_2.value: self.TERM_2,
                                },
                                "removed": None,
                            },
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n2 {handle:'primary_disease_site'})-[r1:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) "
                        "MERGE (n0)-[r0:has_value_set]->(n1:value_set)"
                    ),
                    (
                        "MATCH (n2 {handle:'primary_disease_site'})-[r1:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) DELETE r0"
                    ),
                ),
                (
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Lung',origin_name:'NCIt'}) "
                        "MERGE (n1)-[r1:has_term]->(n2)"
                    ),
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Lung',origin_name:'NCIt'}) , "
                        "(n1)-[r1:has_term]->(n2) "
                        "DELETE r1"
                    ),
                ),
                (
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Kidney',origin_name:'NCIm'}) "
                        "MERGE (n1)-[r1:has_term]->(n2)"
                    ),
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Kidney',origin_name:'NCIm'}) , "
                        "(n1)-[r1:has_term]->(n2) "
                        "DELETE r1"
                    ),
                ),
            ],
        )

    def test_remove_node_concept(self) -> None:
        """Test removing concept (term annotation) from a node."""
        self.assert_diff_as_expected(
            diff={
                NODES: {
                    "changed": {
                        NODE_HANDLE_1: {
                            self.OBJ_ATT_C: {
                                "added": None,
                                "removed": {self.TERM_1.value: self.TERM_1},
                            },
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n0:node {handle:'subject',model:'TEST'}) , "
                        "(n0)-[r0:has_concept]->(n2:concept) , "
                        "(n1:term {value:'Lung',origin_name:'NCIt'})-[r1:represents]->"
                        "(n2) DELETE r0"
                    ),
                    (
                        "MATCH (n0:node {handle:'subject',model:'TEST'}) , "
                        "(n1:term {value:'Lung',origin_name:'NCIt'})-[r1:represents]->"
                        "(n2:concept) MERGE (n0)-[r0:has_concept]->(n2)"
                    ),
                ),
            ],
        )

    def test_change_edge_concept(self) -> None:
        """Test changing concept (term annotation) of an edge."""
        self.assert_diff_as_expected(
            diff={
                EDGES: {
                    "changed": {
                        EDGE_KEY: {
                            self.OBJ_ATT_C: {
                                "added": {self.TERM_2.value: self.TERM_2},
                                "removed": {self.TERM_1.value: self.TERM_1},
                            },
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n4:node {handle:'subject',model:'TEST'})<-[r3:has_dst]-"
                        "(n0:relationship {handle:'of_subject',model:'TEST'})-"
                        "[r2:has_src]->(n3:node {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_concept]->(n2:concept) , "
                        "(n1:term {value:'Lung',origin_name:'NCIt'})-[r1:represents]->"
                        "(n2) DELETE r0"
                    ),
                    (
                        "MATCH (n4:node {handle:'subject',model:'TEST'})<-[r3:has_dst]-"
                        "(n0:relationship {handle:'of_subject',model:'TEST'})-"
                        "[r2:has_src]->(n3:node {handle:'diagnosis',model:'TEST'}) , "
                        "(n1:term {value:'Lung',origin_name:'NCIt'})-[r1:represents]->"
                        "(n2:concept) MERGE (n0)-[r0:has_concept]->(n2)"
                    ),
                ),
                (
                    (
                        "MATCH (n4:node {handle:'subject',model:'TEST'})<-[r3:has_dst]-"
                        "(n0:relationship {handle:'of_subject',model:'TEST'})-"
                        "[r2:has_src]->(n3:node {handle:'diagnosis',model:'TEST'}) "
                        "MERGE (n0)-[r0:has_concept]->(n2:concept)"
                    ),
                    (
                        "MATCH (n4:node {handle:'subject',model:'TEST'})<-[r3:has_dst]-"
                        "(n0:relationship {handle:'of_subject',model:'TEST'})-"
                        "[r2:has_src]->(n3:node {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_concept]->(n2:concept) DELETE r0"
                    ),
                ),
                (
                    (
                        "MATCH (n4:node {handle:'subject',model:'TEST'})<-[r3:has_dst]-"
                        "(n0:relationship {handle:'of_subject',model:'TEST'})-"
                        "[r2:has_src]->(n3:node {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_concept]->(n2:concept) , "
                        "(n1:term {value:'Kidney',origin_name:'NCIm'}) "
                        "MERGE (n1)-[r1:represents]->(n2)"
                    ),
                    (
                        "MATCH (n4:node {handle:'subject',model:'TEST'})<-[r3:has_dst]-"
                        "(n0:relationship {handle:'of_subject',model:'TEST'})-"
                        "[r2:has_src]->(n3:node {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_concept]->(n2:concept) , "
                        "(n1:term {value:'Kidney',origin_name:'NCIm'}) , "
                        "(n1)-[r1:represents]->(n2) DELETE r0"
                    ),
                ),
            ],
        )

    def test_change_prop_value_set(self) -> None:
        """Test changing terms in value set of a property."""
        self.assert_diff_as_expected(
            diff={
                PROPS: {
                    "changed": {
                        PROP_KEY: {
                            self.OBJ_ATT_V: {
                                "added": {self.TERM_2.value: self.TERM_2},
                                "removed": {self.TERM_1.value: self.TERM_1},
                            },
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n1)-[r1:has_term]->(n2:term "
                        "{value:'Lung',origin_name:'NCIt'}) DELETE r1"
                    ),
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Lung',origin_name:'NCIt'}) "
                        "MERGE (n1)-[r1:has_term]->(n2)"
                    ),
                ),
                (
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Kidney',origin_name:'NCIm'}) "
                        "MERGE (n1)-[r1:has_term]->(n2)"
                    ),
                    (
                        "MATCH (n3 {handle:'primary_disease_site'})-[r2:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_value_set]->(n1:value_set) , "
                        "(n2:term {value:'Kidney',origin_name:'NCIm'}) , "
                        "(n1)-[r1:has_term]->(n2) "
                        "DELETE r1"
                    ),
                ),
            ],
        )

    def test_change_node_prop(self) -> None:
        """Test changing properties of a node."""
        self.assert_diff_as_expected(
            diff={
                NODES: {
                    "changed": {
                        NODE_HANDLE_1: {
                            self.COLL_ATT_P: {
                                "added": {PROP_HANDLE_2: self.COLL_ATT_P2},
                                "removed": {PROP_HANDLE_1: self.COLL_ATT_P1},
                            },
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n0:node {handle:'subject',model:'TEST'})-"
                        "[r0:has_property]->(n1:property "
                        "{handle:'primary_disease_site'}) DETACH DELETE n1"
                    ),
                    (
                        "MATCH (n0:node {handle:'subject',model:'TEST'}) , "
                        "(n1:property {handle:'primary_disease_site'}) "
                        "MERGE (n0)-[r0:has_property]->(n1)"
                    ),
                ),
                (
                    (
                        "MATCH (n0:node {handle:'subject',model:'TEST'}) , "
                        "(n1:property {handle:'id'}) "
                        "MERGE (n0)-[r0:has_property]->(n1)"
                    ),
                    (
                        "MATCH (n0:node {handle:'subject',model:'TEST'})-"
                        "[r0:has_property]->(n1:property {handle:'id'}) "
                        "DETACH DELETE n1"
                    ),
                ),
            ],
        )

    def test_change_prop_tag(self) -> None:
        """Test changing tags of a property."""
        self.assert_diff_as_expected(
            diff={
                PROPS: {
                    "changed": {
                        PROP_KEY: {
                            self.COLL_ATT_T: {
                                "added": {self.COLL_ATT_T2.key: self.COLL_ATT_T2},
                                "removed": {self.COLL_ATT_T1.key: self.COLL_ATT_T1},
                            },
                        },
                    },
                },
            },
            expected=[
                (
                    (
                        "MATCH (n2 {handle:'primary_disease_site'})-[r0:has_property]->"
                        "(n1:property {handle:'diagnosis',model:'TEST'}), "
                        "(n1)-[r1:has_tag]->(n0:tag {key:'class',value:'primary'}) "
                        "DETACH DELETE n0"
                    ),
                    "MERGE (n0:tag {key:'class',value:'primary'})",
                ),
                (
                    "MERGE (n0:tag {key:'class',value:'secondary'})",
                    "MATCH (n2 {handle:'primary_disease_site'})-[r0:has_property]->"
                    "(n1:property {handle:'diagnosis',model:'TEST'}), "
                    "(n1)-[r1:has_tag]->(n0:tag {key:'class',value:'secondary'}) "
                    "DETACH DELETE n0",
                ),
                (
                    (
                        "MATCH (n2 {handle:'primary_disease_site'})-[r1:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) "
                        "MERGE (n0)-[r0:has_tag]->"
                        "(n1:tag {key:'class',value:'secondary'})"
                    ),
                    (
                        "MATCH (n2 {handle:'primary_disease_site'})-[r1:has_property]->"
                        "(n0:property {handle:'diagnosis',model:'TEST'}) , "
                        "(n0)-[r0:has_tag]->(n1:tag {key:'class',value:'secondary'}) "
                        "DELETE r0"
                    ),
                ),
            ],
        )
