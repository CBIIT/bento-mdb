"""Tests for model changelog generation script."""

import re
from pathlib import Path

from bento_mdf.mdf import MDF
from bento_meta.model import Model
from bento_meta.objects import Node, Property

from src.changelog_utils import update_config_changeset_id
from src.make_model_changelog import ModelToChangelogConverter

CURRENT_DIRECTORY = Path(__file__).resolve().parent
TEST_MODEL_MDF = Path(CURRENT_DIRECTORY, "samples", "test_mdf.yml")
TEST_CHANGELOG_CONFIG = Path(CURRENT_DIRECTORY, "samples", "test_changelog.ini")
AUTHOR = "Tolkien"
MODEL_HDL = "TEST"
_COMMIT = "_COMMIT_123"


def remove_nanoids_from_str(statement: str) -> str:
    """Remove values for 'nanoid' attr from string if present."""
    return re.sub(r"nanoid:'[^']*'", "nanoid:''", statement)


class TestMakeModelChangelog:
    """Tests for model changelog generation script."""

    def test_make_model_changelog_length(self) -> None:
        """Test for length of changelog generated from model MDF."""
        mdf = MDF(TEST_MODEL_MDF, handle=MODEL_HDL, _commit=_COMMIT, raiseError=True)
        converter = ModelToChangelogConverter(model=mdf.model, add_rollback=False)
        changelog = converter.convert_model_to_changelog(
            author=AUTHOR,
            config_file_path=TEST_CHANGELOG_CONFIG,
        )
        update_config_changeset_id(TEST_CHANGELOG_CONFIG, 1)
        actual = len(changelog.subelements)
        expected = 51
        assert actual == expected

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
            config_file_path=TEST_CHANGELOG_CONFIG,
        )
        update_config_changeset_id(TEST_CHANGELOG_CONFIG, 1)
        actual = [
            remove_nanoids_from_str(x.change_type.text) for x in changelog.subelements
        ]
        expected = [
            "CREATE (n0:node {handle:'cell_line',model:'TEST'})",
            "CREATE (n0:property "
            "{handle:'id',model:'TEST',value_domain:'string',desc:'desc of "
            "id',nanoid:''})",
            "CREATE (n0:node {handle:'clinical_measure_file',model:'TEST'})",
            "CREATE (n0:property "
            "{handle:'id',model:'TEST',value_domain:'string',desc:'desc of "
            "id',nanoid:''})",
            "MATCH (n0:node {handle:'cell_line',model:'TEST'}), (n1:property "
            "{handle:'id',model:'TEST',value_domain:'string',desc:'desc of "
            "id',nanoid:''}) MERGE (n0)-[r0:has_property]->(n1)",
            "MATCH (n0:node {handle:'clinical_measure_file',model:'TEST'}), (n1:property "
            "{handle:'id',model:'TEST',value_domain:'string',desc:'desc of "
            "id',nanoid:''}) MERGE (n0)-[r0:has_property]->(n1)",
        ]
        assert actual == expected

    # def test_make_model_changelog_terms(self):
    #     """Terms only mdf with tags + nested terms"""
    #     model = Model(handle=MODEL_HDL)
    #     term_1 = Term({"handle": "term_1", "value": "Term 1", "origin_name": "TEST"})
    #     concept = Concept()
    #     term_2 = Term({"handle": "term_2", "value": "Term 2", "origin_name": "TEST"})
    #     term_3 = Term({"handle": "term_3", "value": "Term 3", "origin_name": "TEST"})
    #     tag_1 = Tag({"key": "origin_preferred_term", "value": "origin_preferred_term"})
    #     concept.terms[(term_2.handle, term_2.origin_name)] = term_2
    #     concept.terms[(term_3.handle, term_3.origin_name)] = term_3
    #     term_1.concept = concept
    #     term_1.tags[tag_1.key] = tag_1
    #     model.terms[(term_1.handle, term_1.origin_name)] = term_1
    #     converter = ModelToChangelogConverter(model=model, add_rollback=False)
    #     changelog = converter.convert_model_to_changelog(
    #         author=AUTHOR,
    #         config_file_path=TEST_CHANGELOG_CONFIG,
    #     )
    #     update_config_changeset_id(TEST_CHANGELOG_CONFIG, 1)
    #     actual = [
    #         remove_nanoids_from_str(x.change_type.text) for x in changelog.subelements
    #     ]
    #     expected = [
    #     ]
    #     print(f"{actual=}\n{expected=}")
    #     assert actual == expected
