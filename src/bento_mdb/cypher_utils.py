"""Common functions shared by cypher generation scripts."""

from __future__ import annotations

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
    dst_c = N(label="node", props=edge.dst.get_attr_dict())  # type:
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
    par_c = N(label=parent.get_label(), props=parent.get_attr_dict())
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
    """Generate cypher statement to create or merge Entity."""
    escape_quotes_in_attr(entity)
    reset_pg_ent_counter()
    cypher_ent = cypherize_entity(entity)
    if isinstance(entity, Property) and "_parent_handle" in cypher_ent.props:
        cypher_ent.props.pop("_parent_handle")
    if isinstance(entity, Term | ValueSet | Concept):
        if "_commit" not in cypher_ent.props:
            stmt = Statement(Merge(cypher_ent))
        # remove _commit prop of Term/VS cypher_ent for Merge
        else:
            commit = cypher_ent.props.pop("_commit", DEFAULT_COMMIT)
            stmt = Statement(Merge(cypher_ent), OnCreateSet(commit))
        rollback = Statement("empty")
    else:
        stmt = Statement(Create(cypher_ent))
        rollback = Statement(
            Match(cypher_ent),
            DetachDelete(cypher_ent.plain_var()),
        )
    return stmt, rollback


def create_relationship_cypher_stmt(
    src: Entity,
    rel: str,
    dst: Entity,
) -> tuple[Statement, Statement]:
    """Generate cypher statement to create relationship from src to dst entity."""
    reset_pg_ent_counter()
    cypher_src = cypherize_entity(src)
    cypher_dst = cypherize_entity(dst)
    cypher_rel = R(Type=rel)
    # remove _commit attr from Term and VS ents
    for cypher_ent in (cypher_src, cypher_dst):
        if cypher_ent.label in ("term", "value_set") and "_commit" in cypher_ent.props:
            cypher_ent.props.pop("_commit", DEFAULT_COMMIT)
        if cypher_ent.label == "property" and "_parent_handle" in cypher_ent.props:
            cypher_ent.props.pop("_parent_handle")
    stmt_merge_trip = T(cypher_src.plain_var(), cypher_rel, cypher_dst.plain_var())
    rlbk_match_trip = T(cypher_src, cypher_rel, cypher_dst)
    return (
        Statement(Match(cypher_src, cypher_dst), Merge(stmt_merge_trip)),
        Statement(Match(rlbk_match_trip), Delete(cypher_rel.plain_var())),
    )


def generate_cypher_to_link_term_synonyms(
    entity_1: Entity,
    entity_2: Entity,
    mapping_source: str,
    _commit: str | None = DEFAULT_COMMIT,
) -> Statement:
    """
    Generate cypher statement to link two terms via a Concept node.

    Finds or creates one Concept node and ensures both Terms connected to it via the
    'represents' relationship. If either Term is already connected to a Concept tagged
    by the given mapping source, that concept is used instead.
    """
    reset_pg_ent_counter()
    cypher_ent_1 = cypherize_entity(entity_1)
    cypher_ent_2 = cypherize_entity(entity_2)
    cypher_concept_1 = N(label="concept")
    cypher_concept_2 = N(label="concept")
    ent_1_trip = T(cypher_ent_1.plain_var(), R(Type="represents"), cypher_concept_1)
    ent_2_trip = T(cypher_ent_2.plain_var(), R(Type="represents"), cypher_concept_2)
    concept_tag_trip_1 = T(
        cypher_concept_1,
        R(Type="has_tag"),
        N(
            label="tag",
            props={"key": "mapping_source", "value": mapping_source},
        ),
    )
    concept_tag_trip_2 = T(
        cypher_concept_2,
        R(Type="has_tag"),
        N(
            label="tag",
            props={"key": "mapping_source", "value": mapping_source},
        ),
    )
    ent_1_concept_path = G(ent_1_trip, concept_tag_trip_1)
    ent_2_concept_path = G(ent_2_trip, concept_tag_trip_2)
    cypher_ent_1_var = cypher_ent_1.plain_var().pattern()
    cypher_ent_2_var = cypher_ent_2.plain_var().pattern()
    cypher_concept_1_var = cypher_concept_1.plain_var().pattern()
    cypher_concept_2_var = cypher_concept_2.plain_var().pattern()
    new_concept = N(label="concept", props={"_commit": _commit})
    for cypher_ent in (cypher_ent_1, cypher_ent_2):
        if "_commit" in cypher_ent.props:
            cypher_ent.props.pop("_commit", DEFAULT_COMMIT)
    return Statement(
        Match(cypher_ent_1, cypher_ent_2),
        Where(cypher_ent_1_var, "<>", cypher_ent_2_var, op=""),
        With(cypher_ent_1_var, cypher_ent_2_var),
        OptionalMatch(ent_1_concept_path),
        With(cypher_ent_1_var, cypher_ent_2_var, cypher_concept_1_var),
        "LIMIT 1",
        OptionalMatch(ent_2_concept_path),
        With(
            cypher_ent_1_var,
            cypher_ent_2_var,
            cypher_concept_1_var,
            cypher_concept_2_var,
        ),
        "LIMIT 1",
        With(cypher_ent_1_var, cypher_ent_2_var),
        ",",
        f"{Case()}{When(cypher_concept_1_var)} IS NOT NULL THEN {cypher_concept_1_var}",
        f"{When(cypher_concept_2_var)} IS NOT NULL THEN {cypher_concept_2_var}",
        "ELSE NULL END AS existing_concept ",
        ForEach(),
        f"(_ IN {Case()}{When('existing_concept')} IS NOT NULL THEN [1] ELSE [] END |",
        Merge(f"{cypher_ent_1_var}-[:represents]->(existing_concept)"),
        Merge(f"{cypher_ent_2_var}-[:represents]->(existing_concept)"),
        ")",
        ForEach(),
        f"(_ IN {Case()}{When('existing_concept')} IS NULL THEN [1] ELSE [] END |",
        Create(new_concept),
        Create(
            T(
                new_concept.plain_var(),
                R("has_tag"),
                N(
                    label="tag",
                    props={"key": "mapping_source", "value": mapping_source},
                ),
            ),
        ),
        Create(T(cypher_ent_1.plain_var(), R("represents"), new_concept.plain_var())),
        Create(T(cypher_ent_2.plain_var(), R("represents"), new_concept.plain_var())),
        ")",
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
