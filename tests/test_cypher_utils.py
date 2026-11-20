"""Tests for cypher utilities."""

import pytest
from bento_meta.cmp_objects import (
    CompositionOp,
    VSComposition,
    VSCompositionStep,
)
from bento_meta.objects import Node, Property, Term, ValueSet

from bento_mdb.cypher_utils import (
    create_entity_cypher_stmt,
    create_relationship_cypher_stmt,
    escape_quotes_in_attr,
    generate_cypher_to_link_term_synonyms,
    get_edp_reference_identity,
    get_value_set_composition_recipe,
    get_value_set_union_operands,
    union_edp_value_set_cypher,
)
from tests.test_utils import assert_equal


def _edp_term(code: str, version: str = "1") -> Term:
    return Term(
        {
            "handle": f"edp_{code}",
            "value": f"EDP {code}",
            "origin_name": "CRDC",
            "origin_id": code,
            "origin_version": version,
        },
    )


def _composition_step(value_set: ValueSet, operator: str = "Union"):
    return VSCompositionStep(
        operator=CompositionOp(operator),
        value_set=value_set,
    )


class TestValueSetUnion:
    """Tests for shared value-set Union evaluation."""

    def test_operands_and_recipe_preserve_order(self) -> None:
        source_edp = _edp_term("CRDC0001")
        source_operand = ValueSet()
        source_operand.edp_terms[source_edp.handle] = source_edp

        explicit_term = Term({"handle": "other", "value": "Other"})
        explicit_operand = ValueSet()
        explicit_operand.terms[explicit_term.handle] = explicit_term

        composition = VSComposition(
            steps=[
                _composition_step(source_operand),
                _composition_step(explicit_operand),
            ],
        )

        operands = get_value_set_union_operands(composition)

        assert operands == [source_operand, explicit_operand]
        assert get_value_set_composition_recipe(operands) == (
            '[{"Op":"Union","Enum":[{"Origin":"CRDC",'
            '"Code":"CRDC0001","Version":"1"}]},'
            '{"Op":"Union","Enum":[{"Value":"Other"}]}]'
        )

    def test_edp_reference_requires_exact_identity(self) -> None:
        term = _edp_term("CRDC0001", "1.00")
        assert get_edp_reference_identity(term) == (
            "CRDC",
            "CRDC0001",
            "1.00",
        )

        term.origin_version = None
        with pytest.raises(ValueError, match="Origin, Code, and Version"):
            get_edp_reference_identity(term)

    def test_unsupported_operator_fails(self) -> None:
        operand = ValueSet()
        operand.terms["term"] = Term({"value": "Term"})
        composition = VSComposition(steps=[])
        composition.steps.append(
            VSCompositionStep(
                value_set=operand,
                operator="Difference",  # type: ignore[arg-type]
            ),
        )
        with pytest.raises(ValueError, match="Unsupported"):
            get_value_set_union_operands(composition)

    def test_union_cypher_uses_exact_edp_identity(self) -> None:
        actual = union_edp_value_set_cypher(
            'MATCH (target_vs:value_set {handle: "TARGET|1"})',
            _edp_term("CRDC0001", "1.00"),
        )

        assert 'origin_name: "CRDC"' in actual
        assert 'origin_id: "CRDC0001"' in actual
        assert 'origin_version: "1.00"' in actual
        assert "(source_vs)-[:has_term]->(pv:term)" in actual
        assert "MERGE (target_vs)-[:has_term]->(pv)" in actual


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
