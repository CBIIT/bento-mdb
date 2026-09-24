"""Tests for stable MDB Cypher identities."""

from bento_meta.objects import Concept, Tag, Term, ValueSet

from bento_mdb.cypher_utils import (
    create_entity_cypher_stmt,
    create_relationship_cypher_stmt,
    get_concept_identity_hash,
    get_term_identity,
    get_term_set_hash,
    normalize_identity_text,
    normalize_optional_version,
)


def make_term(
    *,
    value: str,
    origin_name: str = "caDSR",
    origin_id: str = "123",
    origin_version: str | None = "1.00",
    nanoid: str | None = None,
    definition: str | None = None,
) -> Term:
    attrs = {
        "value": value,
        "origin_name": origin_name,
        "origin_id": origin_id,
        "origin_version": origin_version,
    }
    if nanoid is not None:
        attrs["nanoid"] = nanoid
    if definition is not None:
        attrs["origin_definition"] = definition

    return Term(attrs)


def test_normalize_identity_text_preserves_literal_values() -> None:
    assert normalize_identity_text(None) == ""
    assert normalize_identity_text("null") == "null"
    assert normalize_identity_text(" None ") == "None"
    assert normalize_identity_text(" 1.00 ") == "1.00"


def test_normalize_optional_version_removes_nullish_values() -> None:
    assert normalize_optional_version(None) == ""
    assert normalize_optional_version("null") == ""
    assert normalize_optional_version("NULL") == ""
    assert normalize_optional_version(" None ") == ""
    assert normalize_optional_version(" 1.00 ") == "1.00"


def test_nullish_words_remain_real_term_values() -> None:
    none_term = make_term(value="None")
    null_term = make_term(value="null")

    assert get_term_identity(none_term)[3] == "None"
    assert get_term_identity(null_term)[3] == "null"
    assert get_term_identity(none_term) != get_term_identity(null_term)


def test_versions_are_not_numerically_normalized() -> None:
    assert normalize_optional_version("1") != normalize_optional_version(
        "1.0",
    )
    assert normalize_optional_version("1.0") != normalize_optional_version(
        "1.00",
    )

def test_term_merge_excludes_generated_metadata() -> None:
    term = make_term(
        value="Yes",
        nanoid="new-id",
        definition="New definition",
    )
    term._commit = "commit-1"  # noqa: SLF001

    statement, _ = create_entity_cypher_stmt(term)
    text = str(statement)

    merge_text = text.split("ON CREATE SET", maxsplit=1)[0]

    assert "origin_name" in merge_text
    assert "origin_id" in merge_text
    assert "origin_version" in merge_text
    assert "value" in merge_text
    assert "nanoid" not in merge_text
    assert "origin_definition" not in merge_text
    assert "_commit" not in merge_text


def test_term_metadata_does_not_change_identity() -> None:
    first = make_term(
        value="Yes",
        nanoid="first",
        definition="First definition",
    )
    second = make_term(
        value="Yes",
        nanoid="second",
        definition="Second definition",
    )

    first_statement, _ = create_entity_cypher_stmt(first)
    second_statement, _ = create_entity_cypher_stmt(second)

    first_merge = str(first_statement).split(
        "ON CREATE SET",
        maxsplit=1,
    )[0]
    second_merge = str(second_statement).split(
        "ON CREATE SET",
        maxsplit=1,
    )[0]

    assert first_merge == second_merge


def test_term_versions_have_different_identity() -> None:
    first = make_term(value="Yes", origin_version="1")
    second = make_term(value="Yes", origin_version="1.00")

    first_statement, _ = create_entity_cypher_stmt(first)
    second_statement, _ = create_entity_cypher_stmt(second)

    assert str(first_statement) != str(second_statement)


def test_relationship_uses_stable_term_identity() -> None:
    value_set = ValueSet({"handle": "123|1.00"})
    term = make_term(
        value="Yes",
        nanoid="generated",
        definition="Definition",
    )

    statement, _ = create_relationship_cypher_stmt(
        value_set,
        "has_term",
        term,
    )
    text = str(statement)

    assert "nanoid:'generated'" not in text
    assert "origin_definition" not in text
    assert "handle:'123|1.00'" in text


def test_term_set_hash_is_order_independent() -> None:
    yes = make_term(value="Yes", origin_id="1")
    no = make_term(value="No", origin_id="2")

    assert get_term_set_hash([yes, no]) == get_term_set_hash(
        [no, yes],
    )


def test_different_term_sets_have_different_hashes() -> None:
    yes = make_term(value="Yes", origin_id="1")
    no = make_term(value="No", origin_id="2")
    unknown = make_term(value="Unknown", origin_id="3")

    assert get_term_set_hash([yes, no]) != get_term_set_hash(
        [yes, no, unknown],
    )


def test_empty_term_set_has_no_shared_hash() -> None:
    assert get_term_set_hash([]) is None


def test_model_concept_hash_reuses_same_source_and_terms() -> None:
    first = Concept()
    first.tags["mapping_source"] = Tag(
        {"key": "mapping_source", "value": "CTDC"},
    )
    first.terms["first"] = make_term(value="CDE", origin_id="100")

    second = Concept()
    second.tags["mapping_source"] = Tag(
        {"key": "mapping_source", "value": "CTDC"},
    )
    second.terms["second"] = make_term(value="CDE", origin_id="100")

    assert get_concept_identity_hash(first) == get_concept_identity_hash(
        second,
    )


def test_model_concept_hash_preserves_mapping_source() -> None:
    ctdc = Concept()
    ctdc.tags["mapping_source"] = Tag(
        {"key": "mapping_source", "value": "CTDC"},
    )
    ctdc.terms["term"] = make_term(value="CDE", origin_id="100")

    cds = Concept()
    cds.tags["mapping_source"] = Tag(
        {"key": "mapping_source", "value": "CDS"},
    )
    cds.terms["term"] = make_term(value="CDE", origin_id="100")

    assert get_concept_identity_hash(ctdc) != get_concept_identity_hash(
        cds,
    )


def test_term_handle_is_only_set_when_created() -> None:
    term = make_term(value="Yes")
    term.handle = "generated-handle"

    statement, _ = create_entity_cypher_stmt(term)
    text = str(statement)

    assert "ON CREATE SET" in text
    assert 'n0.handle = "generated-handle"' in text

    regular_set = text.split("ON CREATE SET", maxsplit=1)[1]
    assert regular_set.count("n0.handle") == 1


def test_term_definition_remains_mutable_metadata() -> None:
    term = make_term(
        value="Yes",
        definition="Updated definition",
    )

    statement, _ = create_entity_cypher_stmt(term)
    text = str(statement)

    assert 'SET n0.origin_definition = "Updated definition"' in text