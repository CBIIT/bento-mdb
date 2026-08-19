"""Cypher generation for bento-meta Models."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bento_mdb.model_cdes import get_edp_enum_term
from bento_meta.model import Model, make_nanoid
from bento_meta.objects import Concept, Tag
from bento_meta.objects import Model as ModelEnt

from liquichange.changelog import Changelog, Changeset, CypherChange, Rollback

from bento_mdb.cypher_utils import (
    Statement,
    create_entity_cypher_stmt,
    create_relationship_cypher_stmt,
    deprecate_old_model_nodes_cypher_stmt,
)

if TYPE_CHECKING:
    from bento_meta.entity import Entity

logger = logging.getLogger(__name__)


def _cypher_string_literal(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def add_version_to_model_ents(model: Model) -> None:
    """Set model version for entities in model."""
    for node in model.nodes.values():
        if node.version:
            continue
        node.version = model.version
    for edge in model.edges.values():
        if edge.version:
            continue
        edge.version = model.version
    for prop in model.props.values():
        if prop.version:
            continue
        prop.version = model.version


def separate_shared_props(model: Model) -> None:
    """
    Duplicate properties shared by > 1 entity with new nanoid.

    This ensures each entity has its own copy.
    """
    initial_props = set()

    for key, prop in model.props.items():
        if prop in initial_props:
            new_prop = prop.dup()
            if new_prop.nanoid:
                new_prop.nanoid = make_nanoid()
            if prop._commit:  # noqa: SLF001
                new_prop._commit = prop._commit  # noqa: SLF001
            if prop.value_set:
                new_prop.value_set = prop.value_set.dup()

            # bento-meta keys node properties as (node, prop) and relationship
            # properties as (relationship, src, dst, prop). Use that key to
            # replace the shared property on the exact node or relationship.
            if len(key) == 2 and key[0] in model.nodes:
                owner = model.nodes[key[0]]
                prop_handle = key[1]
            elif len(key) == 4 and key[:3] in model.edges:
                owner = model.edges[key[:3]]
                prop_handle = key[3]
            else:
                msg = f"Property owner not found for key: {key}"
                raise ValueError(msg)

            owner.props[prop_handle] = new_prop
            model.props[key] = new_prop
        else:
            initial_props.add(prop)


class ModelToChangelogConverter:
    """Class to convert bento-meta model object to a liquibase changelog."""

    def __init__(
        self,
        model: Model,
        *,
        add_rollback: bool = True,
        terms_only: bool = False,
        _commit: str | None = None,
    ) -> None:
        """Initialize converter and structures to hold cypher stmts & added entities."""
        self.add_rollback = add_rollback
        self.terms_only = terms_only
        self._commit = _commit
        self.value_sets_by_term_key = {}
        self.model = model
        self.cypher_stmts: dict[str, dict[str, list[Statement]]] = {
            "add_ents": {"statements": [], "rollbacks": []},
            "add_rels": {"statements": [], "rollbacks": []},
        }
        self.added_entities = []

    def add_statement(
        self,
        stmt_type: str,
        stmt: Statement,
        rollback: Statement,
    ) -> None:
        """Add cypher statement and its rollback to self.cypher_stmts."""
        self.cypher_stmts[stmt_type]["statements"].append(stmt)
        self.cypher_stmts[stmt_type]["rollbacks"].append(rollback)

    def generate_cypher_to_add_entity(
        self,
        entity: Entity,
    ) -> None:
        """Generate cypher statement to create or merge Entity."""
        stmt_type = "add_ents"
        if entity in self.added_entities:
            msg = f"Entity with attrs: {entity.get_attr_dict()} already added."
            logger.info(msg)
            return
        stmt, rollback = create_entity_cypher_stmt(entity)
        self.add_statement(stmt_type, stmt, rollback)
        self.added_entities.append(entity)

    def generate_cypher_to_add_relationship(
        self,
        src: Entity,
        rel: str,
        dst: Entity,
    ) -> None:
        """Generate cypher statement to create relationship from src to dst entity."""
        stmt_type = "add_rels"
        stmt, rollback = create_relationship_cypher_stmt(src, rel, dst)
        self.add_statement(stmt_type, stmt, rollback)

    def process_tags(self, entity: Entity) -> None:
        """Generate cypher statements to create/merge an entity's tag attributes."""
        if not entity.tags:
            return
        for tag in entity.tags.values():
            if not tag.nanoid:
                tag.nanoid = make_nanoid()
            if not tag._parent:  # noqa: SLF001
                tag._parent = entity  # noqa: SLF001
            self.generate_cypher_to_add_entity(tag)
            self.generate_cypher_to_add_relationship(entity, "has_tag", tag)

    def process_origin(self, entity: Entity) -> None:
        """Generate cypher statements to create/merge an entity's origin attribute."""
        if not entity.origin:
            return
        self.generate_cypher_to_add_entity(entity.origin)
        self.generate_cypher_to_add_relationship(entity, "has_origin", entity.origin)
        self.process_tags(entity.origin)

    def process_terms(self, entity: Entity) -> None:
        """Generate cypher statements to create/merge an entity's term attributes."""
        if not entity.terms:
            return
        for term in entity.terms.values():
            self.generate_cypher_to_add_entity(term)
            if isinstance(entity, Concept):
                self.generate_cypher_to_add_relationship(term, "represents", entity)
            else:
                self.generate_cypher_to_add_relationship(entity, "has_term", term)
            self.process_tags(term)
            self.process_origin(term)
            self.process_concept(term)

    def process_concept(self, entity: Entity) -> None:
        """Generate cypher statements to create/merge an entity's concept attribute."""
        if not entity.concept:
            return
        if not entity.concept.tags.get("mapping_source"):
            entity.concept.tags["mapping_source"] = Tag(
                {"key": "mapping_source", "value": self.model.handle},
            )
        self.generate_cypher_to_add_entity(entity.concept)
        self.generate_cypher_to_add_relationship(entity, "has_concept", entity.concept)
        self.process_tags(entity.concept)
        self.process_terms(entity.concept)

    def generate_cypher_to_link_edp_value_set(self, entity: Entity) -> None:
        """Generate cypher to link a model property to an EDP value set."""
        edp_term = get_edp_enum_term(entity)
        if not edp_term:
            return

        prop_attrs = entity.get_attr_dict()
        prop_filters = [
            f"handle: {_cypher_string_literal(prop_attrs['handle'])}",
            f"model: {_cypher_string_literal(prop_attrs['model'])}",
        ]
        if prop_attrs.get("version"):
            prop_filters.append(
                f"version: {_cypher_string_literal(prop_attrs['version'])}",
            )

        edp_filters = [
            f"edp.origin_name = {_cypher_string_literal(edp_term.origin_name)}",
            f"edp.origin_id = {_cypher_string_literal(edp_term.origin_id)}",
        ]
        if getattr(edp_term, "origin_version", None):
            edp_filters.append(
                f"edp.origin_version = {_cypher_string_literal(edp_term.origin_version)}",
            )

        stmt = (
            f"MATCH (prop:property {{{', '.join(prop_filters)}}}) "
            f"MATCH (edp:term) "
            f"WHERE {' AND '.join(edp_filters)} "
            f"MATCH (edp)-[:specifies_value_set]->(vs:value_set) "
            f"MERGE (prop)-[:has_value_set]->(vs)"
        )
        rollback = (
            f"MATCH (prop:property {{{', '.join(prop_filters)}}})"
            f"-[r:has_value_set]->(vs:value_set)<-[:specifies_value_set]-(edp:term) "
            f"WHERE {' AND '.join(edp_filters)} "
            f"DELETE r"
        )
        self.add_statement("add_rels", stmt, rollback)

    def get_value_set_term_key(self, value_set: Entity) -> tuple:
        """Return a stable identity key for a value set's attached terms."""
        terms = getattr(value_set, "terms", None)
        if not terms:
            return ()

        return tuple(
            sorted(
                (
                    getattr(term, "origin_name", None) or "",
                    getattr(term, "origin_id", None) or "",
                    getattr(term, "origin_version", None) or "",
                    getattr(term, "value", None) or "",
                )
                for term in terms.values()
            ),
        )

    def set_value_set_commit(self, value_set: Entity) -> None:
        """Replace missing/dummy value_set commit with the changelog commit."""
        if self._commit and (
            not getattr(value_set, "_commit", None)
            or getattr(value_set, "_commit", None) == "dummy"
        ):
            value_set._commit = self._commit  # noqa: SLF001

    def process_value_set(self, entity: Entity) -> None:
        """Generate cypher statements to merge an entity's value_set attribute."""
        if not entity.value_set:
            return

        if get_edp_enum_term(entity):
            self.generate_cypher_to_link_edp_value_set(entity)
            return

        term_key = self.get_value_set_term_key(entity.value_set)
        canonical_value_set = (
            self.value_sets_by_term_key.get(term_key) if term_key else None
        )

        if canonical_value_set:
            self.generate_cypher_to_add_relationship(
                entity,
                "has_value_set",
                canonical_value_set,
            )
            return

        self.set_value_set_commit(entity.value_set)

        if not entity.value_set.nanoid:
            entity.value_set.nanoid = make_nanoid()

        if term_key:
            self.value_sets_by_term_key[term_key] = entity.value_set

        self.generate_cypher_to_add_entity(entity.value_set)
        self.generate_cypher_to_add_relationship(
            entity,
            "has_value_set",
            entity.value_set,
        )
        self.process_tags(entity.value_set)
        self.process_origin(entity.value_set)
        self.process_terms(entity.value_set)

    def process_props(self, entity: Entity) -> None:
        """Generate cypher statements to create/merge an entity's props attribute."""
        if not entity.props:
            return
        for prop in entity.props.values():
            if not prop.nanoid:
                prop.nanoid = make_nanoid()
            if not prop._parent_handle:  # noqa: SLF001
                prop._parent_handle = entity.handle  # noqa: SLF001
            self.generate_cypher_to_add_entity(prop)
            self.generate_cypher_to_add_relationship(entity, "has_property", prop)
            self.process_tags(prop)
            self.process_concept(prop)
            self.process_value_set(prop)

    def process_model_nodes(self) -> None:
        """Generate cypher statements to create/merge an model's nodes."""
        for node in self.model.nodes.values():
            self.generate_cypher_to_add_entity(node)
            self.process_tags(node)
            self.process_concept(node)
            self.process_props(node)

    def process_model_edges(self) -> None:
        """Generate cypher statements to create/merge an model's edges."""
        for edge in self.model.edges.values():
            if not edge.nanoid:
                edge.nanoid = make_nanoid()
            self.generate_cypher_to_add_entity(edge)
            self.generate_cypher_to_add_relationship(edge, "has_src", edge.src)
            self.generate_cypher_to_add_relationship(edge, "has_dst", edge.dst)
            self.process_tags(edge)
            self.process_concept(edge)
            self.process_props(edge)

    def process_terms_model(self) -> None:
        """
        Generate cypher statements to create/merge a model's terms.

        Used for large term sets w/o model structure.
        Does not process placeholder node/relationship/props.
        """
        logger.info("Processing terms-only model.")
        prop_terms = [p.terms for p in self.model.props.values()]
        flat_prop_terms = [v for d in prop_terms for v in d.values()]
        for term in flat_prop_terms + list(self.model.terms.values()):
            self.generate_cypher_to_add_entity(term)
            self.process_tags(term)
            self.process_origin(term)
            self.process_concept(term)

    def set_model_version(
        self,
        *,
        latest_version: bool = False,
    ) -> None:
        """Create model node and set model version for other entities."""
        model_ent = ModelEnt(
            {
                "is_latest_version": latest_version,
                "repository": self.model.uri,
                "handle": self.model.handle,
                "version": self.model.version,
                "name": self.model.handle,
            },
        )
        if latest_version:
            stmt, rollback = deprecate_old_model_nodes_cypher_stmt(
                str(model_ent.handle),
            )
            self.add_statement("add_ents", stmt, rollback)
        self.generate_cypher_to_add_entity(model_ent)
        if model_ent.version is not None:
            add_version_to_model_ents(self.model)

    def convert_model_to_changelog(
        self,
        author: str,
        model_version: str | None = None,
        *,
        latest_version: bool = False,
    ) -> Changelog:
        """
        Convert a bento meta model to a Liquibase Changelog.

        Parameters:
        model (Model): The bento meta model to convert
        author (str): The author for the changesets

        Returns:
        Changelog: The generated Liquibase Changelog

        Functionality:
        - Generates Cypher statements to add entities and relationships from the model
        - Appends Changesets with the Cypher statements to a Changelog
        - Returns the completed Changelog
        """
        # if property shared by multiple nodes/edges,
        separate_shared_props(self.model)

        # create model node and add model version to other entities
        if model_version is not None:
            self.model.version = model_version
        self.set_model_version(latest_version=latest_version)

        if not self.terms_only:
            self.process_model_nodes()
            self.process_model_edges()
        else:
            self.process_terms_model()

        changeset_id = 1
        changelog = Changelog()

        for stmts in self.cypher_stmts.values():
            for stmt, rollback in zip(stmts["statements"], stmts["rollbacks"]):
                # testing replacing poorly escaped quotes
                str_stmt = str(stmt).replace("\\'", "'")
                changeset = Changeset(
                    id=str(changeset_id),
                    author=author,
                    change_type=CypherChange(text=str_stmt),
                )
                if self.add_rollback:
                    changeset.set_rollback(Rollback(text=str(rollback)))
                changelog.add_changeset(changeset)
                changeset_id += 1

        return changelog
