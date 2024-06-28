"""
Script to generate a Liquibase Changelog from two versions of MDF files.

Takes two MDF files representing different versions of the same
model and produces a Liquibase Changelog with the necessary changes to
an MDB in Neo4J to update the model from the old version to the new one.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import click
from bento_mdf.diff import diff_models
from bento_mdf.mdf import MDF
from bento_meta.entity import Entity
from bento_meta.objects import Concept, Edge, Node, Property, Tag, Term, ValueSet
from liquichange.changelog import Changelog, Changeset, CypherChange, Rollback
from minicypher.clauses import (
    Match,
    Merge,
    Remove,
    Set,
)
from minicypher.entities import N, P, R, T

from src.changelog_utils import (
    Delete,
    DetachDelete,
    Statement,
    changeset_id_generator,
    escape_quotes_in_attr,
    generate_match_clause,
    reset_pg_ent_counter,
    update_config_changeset_id,
)

logger = logging.getLogger(__name__)

ADD_NODE = "add property graph node"
REMOVE_NODE = "remove property graph node"
ADD_RELATIONSHIP = "add property graph relationship"
REMOVE_RELATIONSHIP = "remove property graph relationship"
ADD_PROPERTY = "add property graph property"
REMOVE_PROPERTY = "remove property graph property"


class DiffSplitter:
    """Split model diff into cypher statements that represent one change each."""

    def __init__(
        self,
        diff: dict[str, dict[str, list | dict | None]],
        model_handle: str,
    ) -> None:
        """Initialize DiffSplitter with diff and model handle."""
        self.diff = diff
        self.diff_summary = self.diff.pop("summary", None)
        self.model_handle = model_handle
        # entity_types order matters: earlier types may depend on later types
        # e.g. removing an edge whose src is a removed node
        self.entity_types = ["terms", "props", "edges", "nodes"]
        self.entity_classes: dict[str, type[Entity]] = {
            "nodes": Node,
            "edges": Edge,
            "props": Property,
            "terms": Term,
            "value_set": ValueSet,
            "concept": Concept,
            "tags": Tag,
        }
        self.cypher_stmts = {
            REMOVE_NODE: {"statements": [], "rollbacks": []},
            ADD_NODE: {"statements": [], "rollbacks": []},
            REMOVE_PROPERTY: {"statements": [], "rollbacks": []},
            ADD_PROPERTY: {"statements": [], "rollbacks": []},
            REMOVE_RELATIONSHIP: {"statements": [], "rollbacks": []},
            ADD_RELATIONSHIP: {"statements": [], "rollbacks": []},
        }

    def add_statement(
        self,
        stmt_type: str,
        stmt: Statement,
        rollback: Statement,
    ) -> None:
        """Add cypher statement and its rollback to self.cypher_stmts."""
        self.cypher_stmts[stmt_type]["statements"].append(stmt)
        self.cypher_stmts[stmt_type]["rollbacks"].append(rollback)

    def get_diff_statements(
        self,
    ) -> list[tuple[str, Entity | dict]]:
        """Split diff into segments & return statements & rollbacks in order."""
        for entity_type in self.entity_types:
            self.split_entity_diff(entity_type=entity_type)
        return [
            (stmt, rollback)
            for d in self.cypher_stmts.values()
            if d.get("statements") and d.get("rollbacks")
            for stmt, rollback in zip(d["statements"], d["rollbacks"])
        ]

    def add_node_statement(self, entity: Entity) -> None:
        """Add cypher statement that adds an entity."""
        escape_quotes_in_attr(entity)
        reset_pg_ent_counter()
        ent_c = N(label=entity.get_label(), props=entity.get_attr_dict())
        match_clause = generate_match_clause(entity=entity, ent_c=ent_c)
        stmt = Statement(Merge(ent_c))
        rollback = Statement(match_clause, DetachDelete(ent_c.var()))
        self.add_statement(ADD_NODE, stmt, rollback)

    def remove_node_statement(self, entity: Entity) -> None:
        """Add cypher statement that removes an entity."""
        escape_quotes_in_attr(entity)
        reset_pg_ent_counter()
        ent_c = N(label=entity.get_label(), props=entity.get_attr_dict())
        match_clause = generate_match_clause(entity=entity, ent_c=ent_c)
        stmt = Statement(match_clause, DetachDelete(ent_c.var()))
        rollback = Statement(Merge(ent_c))
        self.add_statement(REMOVE_NODE, stmt, rollback)

    def add_relationship_statement(self, src: Entity, rel: str, dst: Entity) -> None:
        """Add cypher statement that adds a relationship from src to dst entities."""
        for ent in [src, dst]:
            escape_quotes_in_attr(ent)
        reset_pg_ent_counter()
        src_attrs = src.get_attr_dict()
        dst_attrs = dst.get_attr_dict()
        rel_c = R(Type=rel)
        src_c = N(label=src.get_label(), props=src_attrs)
        dst_c = N(label=dst.get_label(), props=dst_attrs)
        src_match_clause = generate_match_clause(entity=src, ent_c=src_c)
        dst_match_clause = generate_match_clause(entity=dst, ent_c=dst_c)
        if (src_attrs and not dst_attrs) or (
            isinstance(src, Property) and isinstance(dst, Tag)  # temp for tags of props
        ):
            stmt_merge_trip = T(src_c.plain_var(), rel_c, dst_c)
            stmt = Statement(src_match_clause, Merge(stmt_merge_trip))
            rollback = Statement(
                src_match_clause,
                ",",
                T(src_c.plain_var(), rel_c, dst_c).pattern(),
                Delete(rel_c.var()),
            )
        elif dst_attrs and not src_attrs:
            stmt_merge_trip = T(src_c, rel_c, dst_c.var())
            stmt = Statement(dst_match_clause, Merge(stmt_merge_trip))
            rollback = Statement(
                dst_match_clause,
                ",",
                T(src_c, rel_c, dst_c.var()).pattern(),
                Delete(rel_c.var()),
            )
        else:
            rlbk_match_trip = T(src_c, rel_c, dst_c)
            stmt = Statement(
                src_match_clause,
                ",",
                dst_c.pattern(),
                Merge(T(src_c.plain_var(), rel_c, dst_c.plain_var()).pattern()),
            )
            rollback = Statement(Match(rlbk_match_trip), DetachDelete(dst_c.var()))

        self.add_statement(ADD_RELATIONSHIP, stmt, rollback)

    def remove_relationship_statement(self, src: Entity, rel: str, dst: Entity) -> None:
        """Add cypher statement that removes a relationship from src to dst entities."""
        for ent in [src, dst]:
            escape_quotes_in_attr(ent)
        reset_pg_ent_counter()
        src_attrs = src.get_attr_dict()
        dst_attrs = dst.get_attr_dict()
        rel_c = R(Type=rel)
        src_c = N(label=src.get_label(), props=src.get_attr_dict())
        dst_c = N(label=dst.get_label(), props=dst.get_attr_dict())
        trip = T(src_c, rel_c, dst_c)
        src_match_clause = generate_match_clause(entity=src, ent_c=src_c)
        dst_match_clause = generate_match_clause(entity=dst, ent_c=dst_c)
        if src_attrs and not dst_attrs:
            stmt = Statement(
                src_match_clause,
                ",",
                T(src_c.plain_var(), rel_c, dst_c),
                Delete(rel_c.plain_var()),
            )
        elif dst_attrs and not src_attrs:
            stmt = Statement(
                dst_match_clause,
                ",",
                T(src_c, rel_c, dst_c.plain_var()),
                Delete(rel_c.plain_var()),
            )
        else:
            stmt = Statement(Match(trip), DetachDelete(dst_c.var()))
            rollback = Statement(
                src_match_clause,
                ",",
                dst_c.pattern(),
                Merge(T(src_c.plain_var(), rel_c, dst_c.plain_var()).pattern()),
            )

        self.add_statement(REMOVE_RELATIONSHIP, stmt, rollback)

    def add_long_relationship_statement(
        self,
        parent: Entity,
        parent_rel: str,
        obj_ent: Entity,
        src: Entity,
        rel: str,
        dst: Entity,
    ) -> None:
        """
        Add cypher statement that adds a relationship from src to dst entities.

        Includes (parent)-[parrel]-(obj) relationship to correctly match ent.
        """
        for ent in [parent, obj_ent, src, dst]:
            escape_quotes_in_attr(ent)
        reset_pg_ent_counter()
        parent_c = N(label=parent.get_label(), props=parent.get_attr_dict())
        parent_rel_c = R(Type=parent_rel)
        rel_c = R(Type=rel)
        src_c = N(label=src.get_label(), props=src.get_attr_dict())
        dst_c = N(label=dst.get_label(), props=dst.get_attr_dict())
        parent_match_clause = generate_match_clause(entity=parent, ent_c=parent_c)
        plain_trip = T(src_c.plain_var(), rel_c, dst_c.plain_var())

        # kludge for concepts - need to clean up rel. direction stuff
        if obj_ent.get_label() == src_c.label:
            parent_trip = T(parent_c.plain_var(), parent_rel_c, src_c)
            match_c = dst_c
            stmt = Statement(
                parent_match_clause,
                ",",
                parent_trip.pattern(),
                ",",
                match_c.pattern(),
                Merge(plain_trip.pattern()),
            )
            rollback = Statement(
                parent_match_clause,
                ",",
                parent_trip.pattern(),
                ",",
                match_c.pattern(),
                ",",
                plain_trip.pattern(),
                Delete(rel_c.var()),
            )
        else:
            parent_trip = T(parent_c.plain_var(), parent_rel_c, dst_c)
            match_c = src_c
            stmt = Statement(
                parent_match_clause,
                ",",
                parent_trip.pattern(),
                ",",
                match_c.pattern(),
                Merge(plain_trip.pattern()),
            )
            rollback = Statement(
                parent_match_clause,
                ",",
                parent_trip.pattern(),
                ",",
                match_c.pattern(),
                ",",
                plain_trip.pattern(),
                Delete(parent_rel_c.var()),
            )
            # adds an additional statement to ensure ent is linked to a concept
            self.add_statement(
                ADD_RELATIONSHIP,
                stmt=Statement(parent_match_clause, Merge(parent_trip.pattern())),
                rollback=Statement(
                    parent_match_clause,
                    ",",
                    parent_trip.pattern(),
                    Delete(parent_rel_c.var()),
                ),
            )

        self.add_statement(ADD_RELATIONSHIP, stmt, rollback)

    def remove_long_relationship_statement(
        self,
        parent: Entity,
        parent_rel: str,
        obj_ent: Entity,
        src: Entity,
        rel: str,
        dst: Entity,
    ) -> None:
        """
        Add cypher statement that removes a relationship from src to dst entities.

        Includes (parent)-[parrel]-(src) relationship to correctly id src ent.
        """
        for ent in [parent, obj_ent, src, dst]:
            escape_quotes_in_attr(ent)
        reset_pg_ent_counter()
        parent_c = N(label=parent.get_label(), props=parent.get_attr_dict())
        parent_rel_c = R(Type=parent_rel)
        rel_c = R(Type=rel)
        src_c = N(label=src.get_label(), props=src.get_attr_dict())
        dst_c = N(label=dst.get_label(), props=dst.get_attr_dict())
        parent_match_clause = generate_match_clause(entity=parent, ent_c=parent_c)

        # kludge for concepts - need to clean up rel. direction stuff
        if obj_ent.get_label() == src_c.label:
            parent_trip = T(parent_c.plain_var(), parent_rel_c, src_c)
            trip = T(src_c.plain_var(), rel_c, dst_c)
            stmt = Statement(
                parent_match_clause,
                ",",
                parent_trip.pattern(),
                ",",
                trip.pattern(),
                Delete(rel_c.var()),
            )
            rollback = Statement(
                parent_match_clause,
                ",",
                parent_trip.pattern(),
                ",",
                dst_c.pattern(),
                Merge(T(src_c.plain_var(), rel_c, dst_c.plain_var()).pattern()),
            )
        else:
            parent_trip = T(parent_c.plain_var(), parent_rel_c, dst_c)
            trip = T(src_c, rel_c, dst_c.plain_var())
            rlbk_trip = T(src_c, rel_c, dst_c)
            stmt = Statement(
                parent_match_clause,
                ",",
                parent_trip.pattern(),
                ",",
                trip.pattern(),
                Delete(parent_rel_c.var()),
            )
            rollback = Statement(
                parent_match_clause,
                ",",
                rlbk_trip.pattern(),
                Merge(
                    T(parent_c.plain_var(), parent_rel_c, dst_c.plain_var()).pattern(),
                ),
            )

        self.add_statement(REMOVE_RELATIONSHIP, stmt, rollback)

    def add_property_statement(
        self,
        entity: Entity,
        prop_handle: str,
        prop_value: Any,
    ) -> None:
        """Add cypher statement that adds a property to an entity."""
        escape_quotes_in_attr(entity)
        reset_pg_ent_counter()
        if isinstance(prop_value, str):
            prop_value = prop_value.replace(r"\'", "'").replace(r"\"", '"')
            prop_value = prop_value.replace("'", r"\'").replace('"', r"\"")

        prop_c = P(handle=prop_handle, value=prop_value)
        ent_c_noprop = N(label=entity.get_label(), props=entity.get_attr_dict())
        ent_c_prop = N(label=entity.get_label(), props=entity.get_attr_dict())
        ent_c_prop._add_props(prop_c)
        ent_c_prop._var = ent_c_noprop._var
        match_clause = generate_match_clause(entity=entity, ent_c=ent_c_noprop)
        stmt = Statement(match_clause, Set(ent_c_prop.props[prop_handle]))
        rollback = Statement(match_clause, Remove(ent_c_prop, prop=prop_handle))

        self.add_statement(ADD_PROPERTY, stmt, rollback)

    def remove_property_statement(
        self,
        entity: Entity,
        prop_handle: str,
        prop_value: Any,
    ) -> None:
        """Add cypher statement that removes a property from an entity."""
        escape_quotes_in_attr(entity)
        reset_pg_ent_counter()
        if isinstance(prop_value, str):
            prop_value = prop_value.replace(r"\'", "'").replace(r"\"", '"')
            prop_value = prop_value.replace("'", r"\'").replace('"', r"\"")

        prop_c = P(handle=prop_handle, value=prop_value)
        ent_c_noprop = N(label=entity.get_label(), props=entity.get_attr_dict())
        ent_c_prop = N(label=entity.get_label(), props=entity.get_attr_dict())
        ent_c_prop._add_props(prop_c)
        ent_c_prop._var = ent_c_noprop._var
        match_clause = generate_match_clause(entity=entity, ent_c=ent_c_noprop)
        stmt = Statement(match_clause, Remove(ent_c_prop, prop=prop_handle))
        rollback = Statement(match_clause, Set(ent_c_prop.props[prop_handle]))

        self.add_statement(REMOVE_PROPERTY, stmt, rollback)

    def update_property_statement(
        self,
        entity: Entity,
        prop_handle: str,
        old_prop_value: Any,
        new_prop_value: Any,
    ) -> None:
        """Add cypher statement that updates a property of an entity."""
        escape_quotes_in_attr(entity)
        reset_pg_ent_counter()
        for prop_value in [old_prop_value, new_prop_value]:
            if not isinstance(prop_value, str):
                continue
            prop_value = prop_value.replace(r"\'", "'").replace(r"\"", '"')
            prop_value = prop_value.replace("'", r"\'").replace('"', r"\"")

        old_prop_c = P(handle=prop_handle, value=old_prop_value)
        new_prop_c = P(handle=prop_handle, value=new_prop_value)
        ent_c_noprop = N(label=entity.get_label(), props=entity.get_attr_dict())
        old_ent_c_prop = N(label=entity.get_label(), props=entity.get_attr_dict())
        new_ent_c_prop = N(label=entity.get_label(), props=entity.get_attr_dict())
        old_ent_c_prop._add_props(old_prop_c)
        new_ent_c_prop._add_props(new_prop_c)
        old_ent_c_prop._var = ent_c_noprop._var
        new_ent_c_prop._var = ent_c_noprop._var
        match_clause = generate_match_clause(entity=entity, ent_c=ent_c_noprop)
        stmt = Statement(match_clause, Set(new_ent_c_prop.props[prop_handle]))
        rollback = Statement(match_clause, Set(old_ent_c_prop.props[prop_handle]))

        self.add_statement(ADD_PROPERTY, stmt, rollback)

    def update_simple_attr_segment(
        self,
        entity: Entity,
        attr: str,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Add segment to update simple attribute."""
        if old_value and not new_value:
            self.remove_property_statement(entity, attr, old_value)
        elif old_value and new_value:
            self.update_property_statement(entity, attr, old_value, new_value)
        else:
            self.add_property_statement(entity, attr, new_value)

    def update_object_attr_segment(
        self,
        entity: Entity,
        attr: str,
        old_values: dict[str, Entity],
        new_values: dict[str, Entity],
    ) -> None:
        """
        Add segment to update object attribute.

        These are 'term containers' like concept & value_set.
        """
        object_attr_class = self.entity_classes.get(attr)
        if not object_attr_class:
            msg = f"{attr} not in self.entity_classes"
            raise AttributeError(msg)
        object_attr = object_attr_class()
        object_attr = self.get_entity_of_type(entity_type=attr)
        parent, parent_rel, obj_ent = self.get_triplet(entity, attr, object_attr)
        if new_values and not old_values:
            # add relationship between entity and object attr if DNE
            self.add_relationship_statement(parent, parent_rel, obj_ent)
            old_values = {}
        for old_value in old_values.values():
            old_entity = self.get_entity_of_type("terms", old_value.get_attr_dict())
            src, rel, dst = self.get_triplet(object_attr, "terms", old_entity)
            self.remove_long_relationship_statement(
                parent=parent,
                parent_rel=parent_rel,
                obj_ent=obj_ent,
                src=src,
                rel=rel,
                dst=dst,
            )
        for new_value in new_values.values():
            new_entity = self.get_entity_of_type("terms", new_value.get_attr_dict())
            src, rel, dst = self.get_triplet(object_attr, "terms", new_entity)
            self.add_long_relationship_statement(
                parent=parent,
                parent_rel=parent_rel,
                obj_ent=obj_ent,
                src=src,
                rel=rel,
                dst=dst,
            )

    def update_collection_attr_segment(
        self,
        entity: Entity,
        attr: str,
        old_values: dict[str, Entity],
        new_values: dict[str, Entity],
    ) -> None:
        """Update collection attr (e.g. list of props/tags/terms of an object attr)."""
        for old_value in old_values.values():
            old_entity = self.get_entity_of_type(attr, old_value.get_attr_dict())
            if isinstance(old_entity, Tag):  # not handled in add/rem
                old_entity._parent = entity
                self.remove_node_statement(old_entity)
            else:
                src, rel, dst = self.get_triplet(entity, attr, old_entity)
                self.remove_relationship_statement(src, rel, dst)
        for new_value in new_values.values():
            new_entity = self.get_entity_of_type(attr, new_value.get_attr_dict())
            if isinstance(new_entity, Tag):  # not handled in add/rem
                new_entity._parent = entity
                self.add_node_statement(new_entity)
            src, rel, dst = self.get_triplet(entity, attr, new_entity)
            self.add_relationship_statement(src, rel, dst)

    def get_triplet(
        self,
        entity: Entity,
        attr: str,
        value: Entity,
    ) -> tuple[Entity, str, Entity]:
        """Use mapspec() to get rel name and direction; returns src, rel, dst."""
        rel_str = entity.mapspec()["relationship"][attr]["rel"]
        rel = rel_str.replace(":", "").replace("<", "").replace(">", "")

        if ">" not in rel_str:  # True unless rel is from left to right
            return (value, rel, entity)
        return (entity, rel, value)

    def get_class_attrs(
        self,
        entity_type: type[Entity],
        *,
        include_generic_attrs: bool = True,
    ) -> dict[str, list[str]]:
        """
        Get class attrs from entity class's attspec_.

        If include_generic_attrs=True, adds Entity.att_spec_ attrs without a '_' prefix.
        """
        class_attrs = entity_type.attspec_

        if include_generic_attrs:
            generic_atts = {x: y for x, y in Entity.attspec_.items() if x[0] != "_"}
            ent_attrs = {**generic_atts, **class_attrs}
        else:
            ent_attrs = class_attrs

        simple_attrs = [x for x, y in ent_attrs.items() if y == "simple"]
        obj_attrs = [x for x, y in ent_attrs.items() if y == "object"]
        coll_attrs = [x for x, y in ent_attrs.items() if y == "collection"]

        return {
            "simple": simple_attrs,
            "object": obj_attrs,
            "collection": coll_attrs,
        }

    def get_entity_of_type(
        self,
        entity_type: str,
        entity_attr_dict: dict[str, Any] | None = None,
    ) -> Entity:
        """Return instantiated entity of given type with given attrs."""
        object_attr_class = self.entity_classes.get(entity_type)
        if not object_attr_class:
            msg = f"{entity_type} not in self.entity_classes"
            raise AttributeError(msg)
        if entity_attr_dict:
            return object_attr_class(entity_attr_dict)
        return object_attr_class()

    def generate_entity_from_key(
        self,
        entity_type: str,
        entity_key: str | tuple[str, str] | tuple[str, str, str],
    ) -> Entity:
        """Generate bento-meta entity from its key."""
        edge_key_len = 3
        prop_key_len = 2
        term_key_len = 2
        if entity_type == "nodes":
            return Node({"handle": entity_key, "model": self.model_handle})
        if entity_type == "edges" and len(entity_key) == edge_key_len:
            return Edge(
                {
                    "handle": entity_key[0],
                    "model": self.model_handle,
                    "src": Node({"handle": entity_key[1], "model": self.model_handle}),
                    "dst": Node({"handle": entity_key[2], "model": self.model_handle}),
                },
            )
        if entity_type == "props" and len(entity_key) == prop_key_len:
            return Property(
                {
                    "handle": entity_key[1],
                    "model": self.model_handle,
                    "_parent_handle": entity_key[0],
                },
            )
        if entity_type == "terms" and len(entity_key) == term_key_len:
            return Term({"value": entity_key[0], "origin_name": entity_key[1]})
        msg = f"Unknown entity type: {entity_type}"
        raise ValueError(msg)

    def set_parent_handle_from_key_if_missing(
        self,
        entity: Entity,
        entity_key: tuple,
    ) -> None:
        """Set parent handle for props that are missing it."""
        if isinstance(entity, Property) and entity._parent_handle is None:  # noqa: SLF001
            entity._parent_handle = entity_key[0]  # noqa: SLF001

    def split_removed_entities(self, entity_diff: dict) -> None:
        """Split removed entities into segments."""
        for entity_key, entity in entity_diff.get("removed", {}).items():
            self.set_parent_handle_from_key_if_missing(entity, entity_key)
            self.remove_node_statement(entity)

    def split_added_entities(self, entity_diff: dict, entity_type: str) -> None:
        """Split added entities into segments."""
        for entity_key, entity in entity_diff.get("added", {}).items():
            self.set_parent_handle_from_key_if_missing(entity, entity_key)
            self.add_node_statement(entity)
            if entity_type == "edges":
                self.add_relationship_statement(entity, "has_src", entity.src)
                self.add_relationship_statement(entity, "has_dst", entity.dst)

    def split_changed_entities(self, entity_diff: dict, entity_type: str) -> None:
        """Split changed entities (i.e. changed non-essential attrs) into segments."""
        class_attrs = self.get_class_attrs(self.entity_classes[entity_type])
        for entity_key, change_dict in entity_diff.get("changed", {}).items():
            entity = self.generate_entity_from_key(entity_type, entity_key)
            for attr, attr_changes in change_dict.items():
                old_val = attr_changes.get("removed", {})
                new_val = attr_changes.get("added", {})
                # change None vals to {}s for .values()
                old_val, new_val = (old_val or {}, new_val or {})
                # update simple attribute (e.g. desc/is_required)
                if attr in class_attrs["simple"]:
                    self.update_simple_attr_segment(entity, attr, old_val, new_val)
                # update object attr (i.e. term container, e.g. concept, value_set)
                elif attr in class_attrs["object"]:
                    self.update_object_attr_segment(entity, attr, old_val, new_val)
                # update collection attr (e.g. list of props, tags)
                elif attr in class_attrs["collection"]:
                    self.update_collection_attr_segment(entity, attr, old_val, new_val)
                else:
                    msg = f"Attribute '{attr}' not found in {class_attrs} for {entity_type}"
                    raise AttributeError(msg)

    def split_entity_diff(self, entity_type: str) -> None:
        """
        Split each each entity type in diff (nodes/edges/props) into segments.

        Segments correspond to individual cypher statements that represent one change,
        i.e. adding/removing an entity or changing its attributes.
        """
        entity_diff = self.diff.get(entity_type)
        if not entity_diff:
            logger.info("No diff for entity type %s", entity_type)
            return
        # change Nones to empty dicts for .items()
        for change in ("removed", "added", "changed"):
            if entity_diff.get(change) is None:
                entity_diff[change] = {}

        self.split_removed_entities(entity_diff)
        self.split_added_entities(entity_diff, entity_type)
        self.split_changed_entities(entity_diff, entity_type)


def convert_diff_to_changelog(
    diff: dict[str, dict[str, list | dict | None]],
    model_handle: str,
    author: str,
    config_file_path: str | Path,
) -> Changelog:
    """Convert diff beween two models to a changelog."""
    changeset_id = changeset_id_generator(config_file_path)
    changelog = Changelog()
    diff_splitter = DiffSplitter(diff, model_handle)
    diff_statements = diff_splitter.get_diff_statements()

    for stmt, rollback in diff_statements:
        changeset = Changeset(
            id=str(next(changeset_id)),
            author=author,
            change_type=CypherChange(text=str(stmt)),
        )
        changeset.set_rollback(Rollback(text=str(rollback)))
        changelog.add_changeset(changeset)

    update_config_changeset_id(config_file_path, next(changeset_id))

    return changelog


@click.command()
@click.option(
    "--model_handle",
    required=True,
    type=str,
    prompt=True,
    help="CRDC Model Handle (e.g. 'GDC')",
)
@click.option(
    "--old_mdf_files",
    required=True,
    type=click.Path(exists=True),
    prompt=True,
    multiple=True,
    help="Older version of MDF file(s)",
)
@click.option(
    "--new_mdf_files",
    required=True,
    type=click.Path(exists=True),
    prompt=True,
    multiple=True,
    help="Newer version of MDF file(s)",
)
@click.option(
    "--output_file_path",
    required=True,
    type=click.Path(),
    prompt=True,
    help="File path for output changelog",
)
@click.option(
    "--config_file_path",
    required=True,
    type=click.Path(exists=True),
    help="Changeset config file path",
)
@click.option(
    "--author",
    required=True,
    type=str,
    help="author for changeset. default=MDB_ADMIN",
)
@click.option(
    "--_commit",
    required=False,
    type=str,
    help="commit string",
)
def main(
    model_handle: str,
    old_mdf_files: str | list[str],
    new_mdf_files: str | list[str],
    output_file_path: str | Path,
    config_file_path: str | Path,
    author: str,
    _commit: str | None,
) -> None:
    """Get liquibase changelog from different versions of mdf files for a model."""
    mdf_old = MDF(*old_mdf_files, handle=model_handle, raiseError=True)
    mdf_new = MDF(*new_mdf_files, handle=model_handle, _commit=_commit, raiseError=True)
    if not mdf_old.model or not mdf_new.model:
        msg = "Error getting model from MDF"
        raise RuntimeError(msg)

    model_old = mdf_old.model
    model_new = mdf_new.model

    diff = diff_models(mdl_a=model_old, mdl_b=model_new)
    changelog = convert_diff_to_changelog(diff, model_handle, author, config_file_path)
    path = Path(output_file_path)
    changelog.save_to_file(file_path=str(path), encoding="UTF-8")


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
