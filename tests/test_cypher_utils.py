"""Tests for cypher utilities."""

from bento_meta.objects import Node, Property, Term

from bento_mdb.cypher_utils import (
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
            'ON CREATE SET n0._commit = "TEST_COMMIT"'
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
            create_relationship_cypher_stmt(self.node, "has_prop", self.prop)[0],
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
                self.term1,
                self.term2,
                "NCIt",
                "CDEPV-TEST",
            ),
        )

        # Both exact term identities must be matched.
        assert "MATCH (n0:term {value:'test_term1'})" in actual
        assert "MATCH (n1:term {value:'test_term2'})" in actual
        assert "WHERE (n0) <> (n1)" in actual

        # An existing concept is eligible only for this mapping source.
        assert "OPTIONAL MATCH" in actual
        assert "(candidate:concept)-[:has_tag]->(:tag {" in actual
        assert 'key: "mapping_source"' in actual
        assert 'value: "NCIt"' in actual

        # Either term may locate the existing source-specific concept.
        assert "(left)-[:represents]->(candidate)" in actual
        assert "(right)-[:represents]->(candidate)" in actual

        # If found, both terms reuse it.
        assert "MERGE (left)-[:represents]->(existing)" in actual
        assert "MERGE (right)-[:represents]->(existing)" in actual

        # A new concept is created only when no matching concept exists.
        assert "WHEN existing IS NULL THEN [1]" in actual
        assert "CREATE (created:concept {" in actual
        assert '_commit: "CDEPV-TEST"' in actual
        assert "CREATE (left)-[:represents]->(created)" in actual
        assert "CREATE (right)-[:represents]->(created)" in actual