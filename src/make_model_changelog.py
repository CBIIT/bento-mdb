"""
Script to take one MDF file representing a model and produce a Liquibase Changelog.

This contains the necessary cypher statements to add the model to an MDB.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import click
from bento_mdf.mdf import MDF
from bento_meta.mdb.mdb import make_nanoid
from bento_meta.objects import Concept, Property, Tag, Term, ValueSet
from liquichange.changelog import Changelog, Changeset, CypherChange, Rollback
from minicypher.clauses import (
    Create,
    Match,
    Merge,
    OnCreateSet,
)
from minicypher.entities import N, R, T

from src.changelog_utils import (
    Delete,
    DetachDelete,
    Statement,
    changeset_id_generator,
    escape_quotes_in_attr,
    reset_pg_ent_counter,
    update_config_changeset_id,
)

if TYPE_CHECKING:
    from bento_meta.entity import Entity
    from bento_meta.model import Model

logger = logging.getLogger(__name__)


class ModelToChangelogConverter:
    """Class to convert bento-meta model object to a liquibase changelog."""

    def __init__(
        self,
        model: Model,
        add_rollback: bool = True,
        terms_only: bool = False,
    ) -> None:
        self.add_rollback = add_rollback
        self.terms_only = terms_only
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
            logger.warning(msg)
            return
        escape_quotes_in_attr(entity)
        reset_pg_ent_counter()
        cypher_ent = cypherize_entity(entity)
        if isinstance(entity, Property) and "_parent_handle" in cypher_ent.props:
            cypher_ent.props.pop("_parent_handle")
        if isinstance(entity, (Term, ValueSet)):
            if "_commit" not in cypher_ent.props:
                stmt = Statement(Merge(cypher_ent))
            # remove _commit prop of Term/VS cypher_ent for Merge
            else:
                commit = cypher_ent.props.pop("_commit")
                stmt = Statement(Merge(cypher_ent), OnCreateSet(commit))
        if isinstance(entity, Term):
            rollback = Statement("empty")
        else:
            stmt = Statement(Create(cypher_ent))
            rollback = Statement(
                Match(cypher_ent),
                DetachDelete(cypher_ent.plain_var()),
            )
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
        reset_pg_ent_counter()
        cypher_src = cypherize_entity(src)
        cypher_dst = cypherize_entity(dst)
        cypher_rel = R(Type=rel)
        # remove _commit attr from Term and VS ents
        for cypher_ent in (cypher_src, cypher_dst):
            if (
                cypher_ent.label in ("term", "value_set")
                and "_commit" in cypher_ent.props
            ):
                cypher_ent.props.pop("_commit")
            if cypher_ent.label == "property" and "_parent_handle" in cypher_ent.props:
                cypher_ent.props.pop("_parent_handle")
        stmt_merge_trip = T(cypher_src.plain_var(), cypher_rel, cypher_dst.plain_var())
        rlbk_match_trip = T(cypher_src, cypher_rel, cypher_dst)
        self.add_statement(
            stmt_type,
            stmt=Statement(Match(cypher_src, cypher_dst), Merge(stmt_merge_trip)),
            rollback=Statement(Match(rlbk_match_trip), Delete(cypher_rel.plain_var())),
        )

    def process_tags(self, entity: Entity) -> None:
        """Generate cypher statements to create/merge an entity's tag attributes."""
        if not entity.tags:
            return
        for tag in entity.tags.values():
            if not tag.nanoid:
                tag.nanoid = make_nanoid()
            if not tag._parent:
                tag._parent = entity
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
        entity.concept.tags["mapping_source"] = Tag(
            {"key": "mapping_source", "value": self.model.handle},
        )
        self.generate_cypher_to_add_entity(entity.concept)
        self.generate_cypher_to_add_relationship(entity, "has_concept", entity.concept)
        self.process_tags(entity.concept)
        self.process_terms(entity.concept)

    def process_value_set(self, entity: Entity) -> None:
        """Generate cypher statements to create/merge an entity's value_set attribute."""
        if not entity.value_set:
            return
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
            if not prop._parent_handle:
                prop._parent_handle = entity.handle
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

    def convert_model_to_changelog(
        self,
        author: str,
        config_file_path: str | Path,
    ) -> Changelog:
        """
        Convert a bento meta model to a Liquibase Changelog.

        Parameters:
        model (Model): The bento meta model to convert
        author (str): The author for the changesets
        config_file_path (str): The path to the changeset config file

        Returns:
        Changelog: The generated Liquibase Changelog

        Functionality:
        - Generates Cypher statements to add entities and relationships from the model
        - Appends Changesets with the Cypher statements to a Changelog
        - Updates the changeset ID in the config file after generating each Changeset
        - Returns the completed Changelog
        """
        # if property shared by multiple nodes/edges,
        separate_shared_props(self.model)

        if not self.terms_only:
            self.process_model_nodes()
            self.process_model_edges()
        else:
            self.process_terms_model()

        changeset_id = changeset_id_generator(config_file_path)
        changelog = Changelog()

        for stmts in self.cypher_stmts.values():
            for stmt, rollback in zip(stmts["statements"], stmts["rollbacks"]):
                changeset = Changeset(
                    id=str(next(changeset_id)),
                    author=author,
                    change_type=CypherChange(text=str(stmt)),
                )
                if self.add_rollback:
                    changeset.set_rollback(Rollback(text=str(rollback)))
                changelog.add_changeset(changeset)

        update_config_changeset_id(config_file_path, next(changeset_id))

        return changelog


def cypherize_entity(entity: Entity) -> N:
    """Represent metamodel Entity object as a property graph Node."""
    return N(label=entity.get_label(), props=entity.get_attr_dict())


def separate_shared_props(model: Model) -> None:
    """
    Duplicate properties shared by > 1 entity with new nanoid.

    This ensures each entity has its own copy.
    """
    initial_props = set()

    for key, prop in model.props.items():
        if prop in initial_props:
            new_prop = Property(prop.get_attr_dict())
            if new_prop.nanoid:
                new_prop.nanoid = make_nanoid()
            model.nodes[key[0]].props[key[1]] = new_prop
            model.props[(key[0], key[1])] = new_prop
        else:
            initial_props.add(prop)


@click.command()
@click.option(
    "--model_handle",
    required=True,
    type=str,
    prompt=True,
    help="CRDC Model Handle (e.g. 'GDC')",
)
@click.option(
    "--mdf_files",
    required=True,
    type=click.Path(exists=True),
    prompt=True,
    multiple=True,
    help="MDF file(s)",
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
    help="Author for changeset",
)
@click.option(
    "--_commit",
    required=False,
    type=str,
    help="Commit string",
)
@click.option(
    "--add_rollback",
    required=False,
    type=bool,
    help="Add cypher stmts with rollback to changesets",
)
@click.option(
    "--terms_only",
    required=False,
    type=bool,
    help="MDF is only terms with empty nodes/rels/propdefs",
)
def main(
    model_handle: str,
    mdf_files: str | list[str],
    output_file_path: str | Path,
    config_file_path: str | Path,
    author: str,
    _commit: str | None,
    add_rollback: bool,
    terms_only: bool,
) -> None:
    """Get liquibase changelog from mdf files for a model."""
    logger.info("Script started")

    mdf = MDF(*mdf_files, handle=model_handle, _commit=_commit, raiseError=True)
    if not mdf.model:
        msg = "Error getting model from MDF"
        raise RuntimeError(msg)
    logger.info("Model MDF loaded successfully")

    converter = ModelToChangelogConverter(
        model=mdf.model,
        add_rollback=add_rollback,
        terms_only=terms_only,
    )
    changelog = converter.convert_model_to_changelog(author, config_file_path)
    logger.info("Changelog converted from MDF successfully")

    changelog.save_to_file(str(Path(output_file_path)), encoding="UTF-8")
    logger.info("Changelog saved at: {output_file_path}")


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
