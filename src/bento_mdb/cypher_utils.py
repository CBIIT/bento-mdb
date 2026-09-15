"""Common functions shared by cypher generation scripts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from string import Template
from typing import TYPE_CHECKING

from bento_meta.objects import Concept, Edge, Property, Tag, Term, ValueSet
from minicypher.clauses import (
    Clause,
    Create,
    Match,
    Merge,
    OnCreateSet,
    OptionalMatch,
    Where,
)
from minicypher.entities import G, N, R, T, _condition, _return
from minicypher.functions import Func
from minicypher.statement import Statement

if TYPE_CHECKING:
    from bento_meta.entity import Entity

DEFAULT_COMMIT = f"CDEPV-{datetime.now(tz=UTC).strftime('%Y%m%d')}"
DEFAULT_AUTHOR = "DEFAULT"

def normalize_identity_text(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_optional_version(value: object | None) -> str:
    normalized = normalize_identity_text(value)
    if normalized.lower() in {"null", "none"}:
        return ""
    return normalized


def cypher_string_literal(value: object | None) -> str:
    """Return a safe double-quoted Cypher string literal."""
    return json.dumps(
        normalize_identity_text(value),
        ensure_ascii=False,
    )


def hash_identity(value: object) -> str:
    """Return a deterministic SHA-256 hash for an identity structure."""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_term_identity(term: Entity) -> tuple[str, str, str, str]:
    """Return the semantic identity of an ordinary MDB term."""
    return (
        normalize_identity_text(getattr(term, "origin_name", None)),
        normalize_identity_text(getattr(term, "origin_id", None)),
        normalize_optional_version(
            getattr(term, "origin_version", None),
        ),
        normalize_identity_text(getattr(term, "value", None)),
    )


def get_term_identity_props(term: Entity) -> dict[str, str]:
    """
    Return properties used to match an ordinary term.

    Empty optional properties are omitted so an incoming empty value matches
    legacy nodes where that property is absent.
    """
    origin_name, origin_id, origin_version, value = get_term_identity(term)

    if not value:
        msg = "Cannot generate stable term identity without a term value."
        raise ValueError(msg)

    props = {"value": value}

    if origin_name:
        props["origin_name"] = origin_name
    if origin_id:
        props["origin_id"] = origin_id
    if origin_version:
        props["origin_version"] = origin_version

    return props


def get_term_set_hash(terms: Iterable[Entity]) -> str | None:
    """Return a stable membership hash for a non-empty term collection."""
    identities = sorted(get_term_identity(term) for term in terms)

    if not identities:
        return None

    return hash_identity(identities)


def get_mapping_source(concept: Concept) -> str:
    """Return the concept's mapping-source tag value."""
    mapping_source = concept.tags.get("mapping_source")
    if not mapping_source:
        return ""

    return normalize_identity_text(mapping_source.value)


def get_concept_identity_hash(concept: Concept) -> str | None:
    """Return mapping-source plus term-set identity for a model concept."""
    mapping_source = get_mapping_source(concept)
    terms = list(concept.terms.values())

    if not mapping_source or not terms:
        return None

    return hash_identity(
        {
            "mapping_source": mapping_source,
            "terms": sorted(get_term_identity(term) for term in terms),
        },
    )


def get_value_set_identity_props(value_set: ValueSet) -> dict[str, str]:
    """Return explicit value-set identity properties."""
    handle = normalize_identity_text(value_set.handle)
    if handle:
        return {"handle": handle}

    set_hash = get_term_set_hash(value_set.terms.values())
    if set_hash:
        return {"set_hash": set_hash}

    # Empty value sets must not all merge into one node.
    nanoid = normalize_identity_text(value_set.nanoid)
    if not nanoid:
        msg = "Empty value sets require a nanoid."
        raise ValueError(msg)

    return {"nanoid": nanoid}


def get_entity_identity_props(entity: Entity) -> dict[str, str | bool]:
    """Return the properties that determine an entity's database identity."""
    if isinstance(entity, Term):
        return get_term_identity_props(entity)

    if isinstance(entity, ValueSet):
        return get_value_set_identity_props(entity)

    if isinstance(entity, Concept):
        concept_hash = get_concept_identity_hash(entity)
        if concept_hash:
            return {"concept_hash": concept_hash}

        nanoid = normalize_identity_text(entity.nanoid)
        if not nanoid:
            msg = "A concept without stable term identity requires a nanoid."
            raise ValueError(msg)

        return {"nanoid": nanoid}

    return {
        key: (
            value
            if isinstance(value, bool)
            else normalize_identity_text(value)
        )
        for key, kind in entity.attspec.items()
        if kind == "simple"
        and (value := getattr(entity, key, None)) is not None
    }


def cypherize_entity_identity(entity: Entity) -> N:
    """Represent an entity using only its stable identity properties."""
    return N(
        label=entity.get_label(),
        props=get_entity_identity_props(entity),
    )


def _cypher_set_assignments(
    variable: str,
    attrs: dict[str, object],
) -> str:
    """Create comma-separated Cypher property assignments."""
    assignments = []

    for key, value in attrs.items():
        if value is None:
            continue

        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int | float):
            rendered = str(value)
        else:
            rendered = cypher_string_literal(value)

        assignments.append(f"{variable}.{key} = {rendered}")

    return ", ".join(assignments)


def _simple_entity_attrs(entity: Entity) -> dict[str, object]:
    """Return declared, non-null, simple attributes."""
    return {
        key: getattr(entity, key)
        for key, kind in entity.attspec.items()
        if kind == "simple" and getattr(entity, key, None) is not None
    }


def cypherize_entity(entity: Entity) -> N:
    """Represent metamodel Entity object as a property graph Node."""

    # TODO: remove custom get_attr_dict when original preserves boolean values
    def get_attr_dict_with_bool(entity: Entity) -> dict[str, str | bool]:
        """Temporary workaround to preserve boolean values in get_attr_dict."""
        return {
            k: str(getattr(entity, k))
            if not isinstance(getattr(entity, k), bool)
            else getattr(entity, k)
            for k in entity.attspec
            if entity.attspec[k] == "simple" and getattr(entity, k) is not None
        }

    return N(label=entity.get_label(), props=get_attr_dict_with_bool(entity))  # type: ignore reportArgumentType


def escape_quotes_in_attr(entity: Entity) -> None:
    """
    Escapes quotes in entity attributes.

    Quotes in string attributes may or may not already be escaped, so this function
    unescapes all previously escaped ' and " characters and replaces them with
    """
    for attr in entity.attspec:
        val = getattr(entity, attr, None)
        if val is not None and isinstance(val, str):
            # First unescape any previously escaped quotes
            unescape_val = val.replace(r"\'", "'").replace(r"\"", '"')

            # Escape all quotes, use utf-8 encoded versions of backslash and quotes
            # so extra backslash isn't added to the string
            escape_val = unescape_val.replace(
                r"'",
                "\u005c\u0027",
            ).replace(
                r'"',
                "\u005c\u0022",
            )

            setattr(entity, attr, escape_val)


def reset_pg_ent_counter() -> None:
    """Reset property graph entity variable counters to 0."""
    N._reset_counter()  # noqa: SLF001
    R._reset_counter()  # noqa: SLF001


def generate_match_clause(entity: Entity, ent_c: N) -> Match:
    """Generate Match clause for entity."""
    if isinstance(entity, Edge):
        return match_edge(edge=entity, ent_c=ent_c)
    if isinstance(entity, Property):  # remove '_parent_handle' from ent_c property
        ent_c.props.pop("_parent_handle", None)
        return match_prop(prop=entity, ent_c=ent_c)
    if isinstance(entity, Tag):
        return match_tag(tag=entity, ent_c=ent_c)
    return Match(ent_c)


def match_edge(edge: Edge, ent_c: N) -> Match:
    """Add MATCH statement for edge."""
    src_c = N(label="node", props=edge.src.get_attr_dict())
    dst_c = N(label="node", props=edge.dst.get_attr_dict())
    src_trip = T(ent_c, R(Type="has_src"), src_c)
    dst_trip = T(ent_c, R(Type="has_dst"), dst_c)
    path = G(src_trip, dst_trip)
    return Match(path)


def match_prop(prop: Property, ent_c: N) -> Match:
    """Add MATCH statement for property."""
    if not prop._parent_handle:
        msg = f"Property missing parent handle {prop.get_attr_dict()}"
        raise AttributeError(msg)
    par_c = N(props={"handle": prop._parent_handle})
    prop_trip = T(par_c, R(Type="has_property"), ent_c)
    return Match(prop_trip)


def match_tag(tag: Tag, ent_c: N) -> Match:
    """Add MATCH statement for tag."""
    if not tag._parent:  # noqa: SLF001
        msg = f"Tag missing parent {tag.get_attr_dict()}"
        raise AttributeError(msg)
    parent = tag._parent  # noqa: SLF001
    par_c = (
    cypherize_entity_identity(parent)
    if isinstance(parent, Term | ValueSet | Concept)
    else cypherize_entity(parent)
    )
    par_c.props.pop("_parent_handle", None)
    # temp workaround for long matches
    par_match_clause = generate_match_clause(entity=parent, ent_c=par_c)
    par_match_str = str(par_match_clause)[6:]
    tag_trip = T(par_c.plain_var(), R(Type="has_tag"), ent_c)
    return Match(par_match_str, tag_trip)


class Case(Clause):
    """Create a CASE clause with the arguments."""

    template = Template("CASE $slot1")

    def __init__(self, *args):
        super().__init__(*args)


class Delete(Clause):
    """Create a DELETE clause with the arguments."""

    template = Template("DELETE $slot1")

    def __init__(self, *args):
        super().__init__(*args)


class DetachDelete(Clause):
    """Create a DETACH DELETE clause with the arguments."""

    template = Template("DETACH DELETE $slot1")

    def __init__(self, *args):
        super().__init__(*args)


class ForEach(Clause):
    """Create an FOREACH clause with the arguments."""

    template = Template("FOREACH $slot1")

    def __init__(self, *args):
        super().__init__(*args)


class With(Clause):
    """Create a WITH clause with the arguments."""

    template = Template("WITH $slot1")

    def __init__(self, *args):
        super().__init__(*args)

    @staticmethod
    def context(arg: object) -> str:
        return _return(arg)


class When(Clause):
    """Create a WHEN clause with the arguments."""

    template = Template("WHEN $slot1")
    joiner = " {} "

    @staticmethod
    def context(arg):
        return _condition(arg)

    def __init__(self, *args, op="AND"):
        super().__init__(*args, op=op)
        self.op = op

    def __str__(self):
        values = []
        for c in [self.context(x) for x in self.args]:
            if isinstance(c, str):
                values.append(c)
            elif isinstance(c, Func):
                values.append(str(c))
            elif isinstance(c, list):
                values.extend([str(x) for x in c])
            else:
                values.append(str(c))
        return self.template.substitute(slot1=self.joiner.format(self.op).join(values))


def create_entity_cypher_stmt(
entity: Entity,
) -> tuple[Statement, Statement]:
    """
    Generate Cypher for an MDB entity.

    Terms, value sets, and concepts are merged using their stable semantic
    identities. Generated identifiers and creation metadata are assigned only
    when a node is first created. Other entity types preserve their existing
    CREATE behavior.
    """
    reset_pg_ent_counter()

    if isinstance(entity, Term | ValueSet | Concept):
        identity_props = get_entity_identity_props(entity)
        identity_node = cypherize_entity_identity(entity)
        variable = identity_node.plain_var().pattern().strip("()")
        attrs = _simple_entity_attrs(entity)

        # Identity fields already appear in the MERGE pattern and must not
        # also be emitted as metadata assignments.
        for identity_key in identity_props:
            attrs.pop(identity_key, None)

        # These properties describe the initially created physical node.
        # Finding the same semantic identity later must not overwrite them.
        on_create_keys = {
            "handle",
            "nanoid",
            "_commit",
        }

        on_create_attrs = {
            key: attrs.pop(key)
            for key in tuple(attrs)
            if key in on_create_keys
            and attrs[key] not in (None, "")
        }

        # Remaining nonempty attributes are descriptive source metadata.
        # They may be refreshed when the source supplies updated metadata,
        # but they are not part of node identity.
        mutable_metadata_attrs = {
            key: value
            for key, value in attrs.items()
            if value not in (None, "")
        }

        query_parts = [f"MERGE {identity_node.pattern()}"]

        if on_create_attrs:
            query_parts.append(
                "ON CREATE SET "
                + _cypher_set_assignments(
                    variable,
                    on_create_attrs,
                ),
            )

        if mutable_metadata_attrs:
            query_parts.append(
                "SET "
                + _cypher_set_assignments(
                    variable,
                    mutable_metadata_attrs,
                ),
            )

        return (
            Statement(" ".join(query_parts)),
            Statement("empty"),
        )

    # Preserve the previous behavior for model, node, relationship,
    # property, tag, and other non-deduplicated entity types.
    cypher_ent = cypherize_entity(entity)

    if isinstance(entity, Property):
        cypher_ent.props.pop("_parent_handle", None)

    return (
        Statement(
            Create(cypher_ent),
        ),
        Statement(
            Match(cypher_ent),
            DetachDelete(cypher_ent.plain_var()),
        ),
    )


def create_relationship_cypher_stmt(
    src: Entity,
    rel: str,
    dst: Entity,
) -> tuple[Statement, Statement]:
    """Create a relationship using the same identities as node creation."""
    reset_pg_ent_counter()

    cypher_src = (
        cypherize_entity_identity(src)
        if isinstance(src, Term | ValueSet | Concept)
        else cypherize_entity(src)
    )
    cypher_dst = (
        cypherize_entity_identity(dst)
        if isinstance(dst, Term | ValueSet | Concept)
        else cypherize_entity(dst)
    )

    for cypher_ent in (cypher_src, cypher_dst):
        if cypher_ent.label == "property":
            cypher_ent.props.pop("_parent_handle", None)

    cypher_rel = R(Type=rel)
    merge_triplet = T(
        cypher_src.plain_var(),
        cypher_rel,
        cypher_dst.plain_var(),
    )
    rollback_triplet = T(cypher_src, cypher_rel, cypher_dst)

    return (
        Statement(
            Match(cypher_src, cypher_dst),
            Merge(merge_triplet),
        ),
        Statement(
            Match(rollback_triplet),
            Delete(cypher_rel.plain_var()),
        ),
    )


def generate_cypher_to_link_term_synonyms(
    entity_1: Entity,
    entity_2: Entity,
    mapping_source: str,
    _commit: str | None = DEFAULT_COMMIT,
) -> Statement:
    """Reuse or create one source-specific concept for two synonymous terms."""
    if not isinstance(entity_1, Term) or not isinstance(entity_2, Term):
        msg = "Synonym linking requires two Term entities."
        raise TypeError(msg)

    reset_pg_ent_counter()

    left_node = N(
        label="term",
        props=get_term_identity_props(entity_1),
    )
    right_node = N(
        label="term",
        props=get_term_identity_props(entity_2),
    )

    left_var = left_node.plain_var().pattern()
    right_var = right_node.plain_var().pattern()
    source_literal = cypher_string_literal(mapping_source)
    commit_literal = cypher_string_literal(_commit)

    return Statement(
        f"""
        MATCH {left_node.pattern()}
        MATCH {right_node.pattern()}
        WHERE {left_var} <> {right_var}
        WITH {left_var} AS left, {right_var} AS right

        OPTIONAL MATCH
          (candidate:concept)-[:has_tag]->(:tag {{
            key: "mapping_source",
            value: {source_literal}
          }})
        WHERE
          (left)-[:represents]->(candidate)
          OR (right)-[:represents]->(candidate)

        WITH left, right, candidate
        ORDER BY id(candidate)
        WITH left, right, head(collect(candidate)) AS existing

        FOREACH (
          _ IN CASE
            WHEN existing IS NOT NULL THEN [1]
            ELSE []
          END |
          MERGE (left)-[:represents]->(existing)
          MERGE (right)-[:represents]->(existing)
        )

        FOREACH (
          _ IN CASE
            WHEN existing IS NULL THEN [1]
            ELSE []
          END |
          CREATE (created:concept {{
            _commit: {commit_literal}
          }})
          CREATE (created)-[:has_tag]->(:tag {{
            key: "mapping_source",
            value: {source_literal}
          }})
          CREATE (left)-[:represents]->(created)
          CREATE (right)-[:represents]->(created)
        )
        """.strip(),
    )


def deprecate_old_model_nodes_cypher_stmt(
    model_handle: str,
) -> tuple[Statement, Statement]:
    """Generate cypher statement to deprecate old model node versions."""
    return (
        Statement(
            f"MATCH (n0:model {{handle: '{model_handle}'}})",
            "WHERE n0.is_latest_version = true",
            "SET n0.is_latest_version = false",
        ),
        Statement(),
    )


def generate_cypher_to_link_term_alternates(
    pv_term: Entity,
    alt_term: Entity,
    _commit: str | None = DEFAULT_COMMIT,
) -> Statement:
    """Link a PV and alternate through one alternate-name concept."""
    return generate_cypher_to_link_term_synonyms(
        pv_term,
        alt_term,
        "alternate_name",
        _commit,
    )
