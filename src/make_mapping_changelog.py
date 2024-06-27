"""Script to convert mapping MDF to a Liquibase Changelog."""

from __future__ import annotations

from ast import literal_eval
from pathlib import Path

import click
import yaml
from liquichange.changelog import Changelog, Changeset, CypherChange
from minicypher.clauses import (
    Create,
    Match,
    Merge,
    OptionalMatch,
)
from minicypher.entities import G, N, R, T

from src.changelog_utils import (
    Case,
    ForEach,
    Statement,
    When,
    With,
    changeset_id_generator,
    update_config_changeset_id,
)


def load_yaml(
    file: str,
) -> dict[
    str,
    str
    | list[str]
    | dict[
        str,
        dict[str, dict[str, dict[str, list[dict[str, dict[str, str | bool]]]]]],
    ],
]:
    """Load mapping Dict from yaml."""
    with Path(file).open(encoding="UTF8") as stream:
        try:
            data = yaml.safe_load(stream)
            return data
        except yaml.YAMLError as exc:
            print(exc)
            raise exc


def get_mapping_source(mapping_dict: dict) -> str:
    """Return source of cross-model mappings."""
    return mapping_dict.get("Source", "")


def get_target_models(mapping_dict: dict) -> dict[str, str]:
    """Return target models."""
    return mapping_dict.get("Models", {})


def get_parents_as_list(parent_str: str) -> list[str]:
    """Return parent nodes as a list."""
    if not parent_str or not isinstance(parent_str, str):
        msg = "Input must be a non-empty string."
        raise ValueError(msg)
    if parent_str.startswith("[") and parent_str.endswith("]"):
        return literal_eval(parent_str)
    if "." in parent_str:
        return parent_str.split(".")
    return [parent_str]


def generate_mapping_cypher(
    src_ent: N,
    dst_ent: N,
    src_parent: N,
    dst_parent: N,
    parent_child_rel: R,
    mapping_source: str,
    _commit: str | None = None,
) -> Statement:
    """
    Generate cypher query to link synonymous entities via a Concept node.

    Matches existing src_ent & dst_ent with given parents/ancestors.

    Adds Tag node {mapping_source: src_model} to generated concept.

    _commit will be added to newly created nodes
    """
    src_triple = T(src_parent, parent_child_rel.anon(), src_ent)
    dst_triple = T(dst_parent, parent_child_rel.anon(), dst_ent)
    src_concept = N(label="concept")
    dst_concept = N(label="concept")
    src_concept_path = G(
        T(src_ent.plain_var(), R(Type="has_concept"), src_concept),
        T(
            src_concept.plain_var(),
            R(Type="has_tag"),
            N(label="tag", props={"key": "mapping_source", "value": mapping_source}),
        ),
    )
    dst_concept_path = G(
        T(dst_ent.plain_var(), R(Type="has_concept"), dst_concept),
        T(
            dst_concept.plain_var(),
            R(Type="has_tag"),
            N(label="tag", props={"key": "mapping_source", "value": mapping_source}),
        ),
    )
    new_concept = N(label="concept", props={"_commit": _commit})
    new_tag = N(
        label="tag",
        props={"key": "mapping_source", "value": mapping_source, "_commit": _commit},
    )
    return Statement(
        # find src & dst entities using parent triples
        Match(src_triple, dst_triple),
        # check if src or dst ents have a concept tagged by the mapping src
        OptionalMatch(src_concept_path),
        OptionalMatch(dst_concept_path),
        With(src_ent.var(), dst_ent.var(), src_concept.var(), dst_concept.var()),
        # src ent has existing concept tagged by mapping src, link dst ent to it
        ForEach(),
        f"(_ IN {Case()}{When(f'{src_concept.var()} IS NOT NULL', f'{dst_concept.var()} IS NULL')} ",
        "THEN [1] ELSE [] END |",
        Merge(
            T(
                dst_ent.plain_var(),
                R(Type="has_concept"),
                src_concept.plain_var(),
            ).pattern(),
        ),
        ")",
        # dst ent has existing concept tagged by mapping src, link src ent to it
        ForEach(),
        f"(_ IN {Case()}{When(f'{src_concept.var()} IS NULL', f'{dst_concept.var()} IS NOT NULL')} ",
        "THEN [1] ELSE [] END |",
        Merge(
            T(
                src_ent.plain_var(),
                R(Type="has_concept"),
                dst_concept.plain_var(),
            ).pattern(),
        ),
        ")",
        # neither ent has a concept, create a new one, tag it, link ents to it
        ForEach(),
        f"(_ IN {Case()}{When(f'{src_concept.var()} IS NULL', f'{dst_concept.var()} IS NULL')} ",
        "THEN [1] ELSE [] END |",
        Create(T(new_concept, R(Type="has_tag"), new_tag)),
        Create(
            T(
                src_ent.plain_var(),
                R(Type="has_concept", props={"_commit": _commit}),
                new_concept.plain_var(),
            ).pattern(),
        ),
        Create(
            T(
                dst_ent.plain_var(),
                R(Type="has_concept", props={"_commit": _commit}),
                new_concept.plain_var(),
            ).pattern(),
        ),
        ")",
    )


def process_props(mapping_dict: dict, _commit: str | None = None) -> list[Statement]:
    """Process mappings between model Property entities."""
    cypher_stmts = []
    src_model = get_mapping_source(mapping_dict)
    prop_map = mapping_dict.get("Props")
    if not prop_map:
        msg = "Mapping MDF must contain 'Props' key."
        raise RuntimeError(msg)
    for src_parent, src_prop_dict in prop_map.items():
        for src_prop, dst_model_dict in src_prop_dict.items():
            for dst_model, dst_prop_list in dst_model_dict.items():
                for dst_prop_dict in dst_prop_list:
                    dst_prop = next(iter(dst_prop_dict))
                    dst_parents = dst_prop_dict.get(dst_prop).get("Parents", "CONST")
                    cypher_stmts.append(
                        generate_mapping_cypher(
                            src_ent=N(
                                label="property",
                                props={"handle": src_prop, "model": src_model},
                            ),
                            dst_ent=N(
                                label="property",
                                props={"handle": dst_prop, "model": dst_model},
                            ),
                            src_parent=N(
                                props={
                                    "handle": get_parents_as_list(src_parent)[-1],
                                    "model": src_model,
                                },
                            ),
                            dst_parent=N(
                                props={
                                    "handle": get_parents_as_list(dst_parents)[-1],
                                    "model": dst_model,
                                },
                            ),
                            parent_child_rel=R(Type="has_property"),
                            mapping_source=src_model,
                            _commit=_commit,
                        ),
                    )
    return cypher_stmts


def convert_mappings_to_changelog(
    mapping_mdf: str | Path,
    config_file_path: str | Path,
    author: str,
    _commit: str | None = None,
) -> Changelog:
    """Convert mapping MDF to liquibase changelog."""
    changeset_id = changeset_id_generator(config_file_path)
    changelog = Changelog()

    mapping_dict = load_yaml(str(mapping_mdf))
    cypher_stmts = process_props(mapping_dict, _commit)
    for stmt in cypher_stmts:
        # troubleshooting
        for clause in stmt.clauses:
            print(clause)
        # troubleshooting
        changeset = Changeset(
            id=str(next(changeset_id)),
            author=author,
            run_always=True,
            change_type=CypherChange(text=str(stmt)),
        )
        changelog.add_changeset(changeset)

    update_config_changeset_id(config_file_path, next(changeset_id))

    return changelog


@click.command()
@click.option(
    "--mapping_mdf",
    required=True,
    type=click.Path(exists=True),
    prompt=True,
    help="Mapping MDF File to be converted to changelog",
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
    help="author for changeset",
)
@click.option(
    "--_commit",
    required=False,
    type=str,
    help="commit string",
)
def main(
    mapping_mdf: str | Path,
    output_file_path: str,
    config_file_path: str,
    author: str,
    _commit: str,
) -> None:
    """Convert mapping MDF file to changelog."""
    changelog = convert_mappings_to_changelog(
        mapping_mdf=mapping_mdf,
        config_file_path=config_file_path,
        author=author,
        _commit=_commit,
    )
    changelog.save_to_file(str(Path(output_file_path)), encoding="UTF-8")


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
