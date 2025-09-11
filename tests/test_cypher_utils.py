"""Tests for cypher utilities."""

from bento_meta.objects import Node, Property, Term

from bento_mdb_updates.cypher_utils import (
    create_entity_cypher_stmt,
    create_relationship_cypher_stmt,
    escape_quotes_in_attr,
    generate_cypher_to_link_term_synonyms,
)
from tests.test_utils import assert_equal


def test_escape_quotes_in_attr() -> None:
    prop = Property(
        {"handle": "Quote's Handle", "desc": """quote's quote\'s "quotes\""""},
    )
    escape_quotes_in_attr(prop)
    assert prop.handle == r"""Quote\'s Handle"""
    assert prop.desc == r"""quote\'s quote\'s \"quotes\""""


class TestCreateEntityCypherStmt:
    """Tests for create_entity_cypher_stmt."""

    node = Node({"handle": "test_node"})
    term = Term({"value": "test_term"})
    prop = Property({"handle": "test_prop"})

    def test_create_node_cypher(self) -> None:
        actual = str(create_entity_cypher_stmt(self.node)[0])
        expected = "CREATE (n0:node {handle:'test_node'})"
        assert_equal(actual, expected)

    def test_create_term_cypher(self) -> None:
        actual = str(create_entity_cypher_stmt(self.term)[0])
        expected = "MERGE (n0:term {value:'test_term'})"
        assert_equal(actual, expected)

    def test_create_term_with_commit_cypher(self) -> None:
        termc = Term(self.term)
        termc._commit = "TEST_COMMIT"
        actual = str(create_entity_cypher_stmt(termc)[0])
        expected = (
            "MERGE (n0:term {value:'test_term'}) "
            "ON CREATE SET n0._commit = 'TEST_COMMIT'"
        )
        assert_equal(actual, expected)

    def test_create_prop_cypher(self) -> None:
        actual = str(create_entity_cypher_stmt(self.prop)[0])
        expected = "CREATE (n0:property {handle:'test_prop'})"
        assert_equal(actual, expected)


class TestCreateRelationshipCypherStmt:
    """Tests for create_relationship_cypher_stmt."""

    node = Node({"handle": "test_node"})
    prop = Property({"handle": "test_prop"})

    def test_create_relationship_cypher(self) -> None:
        actual = str(
            create_relationship_cypher_stmt(self.node, "has_prop", self.prop)[0]
        )
        expected = (
            "MATCH (n0:node {handle:'test_node'}), (n1:property {handle:'test_prop'}) "
            "MERGE (n0)-[r0:has_prop]->(n1)"
        )
        assert_equal(actual, expected)


class TestGenerateCypherToLinkTermSynonyms:
    """Tests for generate_cypher_to_link_term_synonyms."""

    term1 = Term({"value": "test_term1", "_commit": "CDEPV-TEST"})
    term2 = Term({"value": "test_term2"})

    def test_generate_cypher_to_link_term_synonyms(self) -> None:
        actual = str(
            generate_cypher_to_link_term_synonyms(
                self.term1, self.term2, "NCIt", "CDEPV-TEST"
            )
        )
        expected = (
            "MATCH (n0:term {value:'test_term1'}), (n1:term {value:'test_term2'}) "
            "WHERE (n0)  <>  (n1) WITH (n0), (n1) OPTIONAL MATCH (n0)-[r0:represents]->"
            "(n2:concept)-[r2:has_tag]->(n4:tag {key:'mapping_source',value:'NCIt'}) "
            "WITH (n0), (n1), (n2) LIMIT 1 OPTIONAL MATCH (n1)-[r1:represents]->"
            "(n3:concept)-[r3:has_tag]->(n5:tag {key:'mapping_source',value:'NCIt'}) "
            "WITH (n0), (n1), (n2), (n3) LIMIT 1 WITH (n0), (n1) , "
            "CASE WHEN (n2) IS NOT NULL THEN (n2) WHEN (n3) IS NOT NULL THEN (n3) "
            "ELSE NULL END AS existing_concept  FOREACH  "
            "(_ IN CASE WHEN existing_concept IS NOT NULL THEN [1] ELSE [] END | "
            "MERGE (n0)-[:represents]->(existing_concept) MERGE (n1)-[:represents]->"
            "(existing_concept) ) FOREACH  (_ IN CASE WHEN existing_concept IS NULL "
            "THEN [1] ELSE [] END | CREATE (n6:concept {_commit:'CDEPV-TEST'}) "
            "CREATE (n6)-[r4:has_tag]->(n7:tag {key:'mapping_source',value:'NCIt'}) "
            "CREATE (n0)-[r5:represents]->(n6) CREATE (n1)-[r6:represents]->(n6) )"
        )
        assert_equal(actual, expected)
