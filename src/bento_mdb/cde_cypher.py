"""Cypher generation for CDE PVs and Synonyms."""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, cast

from bento_meta.objects import Term, ValueSet
from liquichange.changelog import Changelog, Changeset, CypherChange
from tqdm import tqdm

from bento_mdb_updates.cypher_utils import (
    DEFAULT_AUTHOR,
    DEFAULT_COMMIT,
    create_entity_cypher_stmt,
    create_relationship_cypher_stmt,
    generate_cypher_to_link_term_synonyms,
)

if TYPE_CHECKING:
    from bento_mdb_updates.cypher_utils import Statement
    from bento_mdb_updates.datatypes import AnnotationSpec, ModelCDESpec

logger = logging.getLogger(__name__)


def convert_annotation_to_changesets(
    annotation: AnnotationSpec,
    changeset_id: int,
    author: str | None = None,
    _commit: str | None = DEFAULT_COMMIT,
) -> list[Changeset]:
    """Convert annotation to list of Liquibase Changesets."""
    if not annotation.get("value_set") or annotation.get("value_set") == []:
        return []
    statements: list[Statement] = []
    changesets = []
    cde_attrs = annotation["annotation"]["attrs"]
    base_url = "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/"
    cde_id = cde_attrs.get("origin_id", "")
    cde_ver = cde_attrs.get("origin_version", "")
    if cde_ver is None:
        cde_ver = ""
    cde_vs = ValueSet(
        {
            "url": f"{base_url}{cde_id}{f'?version={cde_ver}' if cde_ver else ''}",
            "handle": f"{cde_id}|{cde_ver}",
            "_commit": _commit,
        },
    )
    statements.append(create_entity_cypher_stmt(cde_vs)[0])
    for pv in tqdm(
        annotation["value_set"],
        desc="PVs",
        total=len(annotation["value_set"]),
    ):
        if not pv:
            continue
        pv_copy = copy.deepcopy(pv)
        # separate synonyms dict from pv attrs
        synonyms = cast("list[dict[str, str | None]]", pv_copy.pop("synonyms"))
        pv_term = Term(pv_copy)
        pv_term._commit = _commit  # noqa: SLF001
        statements.append(create_entity_cypher_stmt(pv_term)[0])
        statements.append(
            create_relationship_cypher_stmt(cde_vs, "has_term", pv_term)[0],
        )
        if not synonyms:
            continue
        ncit_term = Term(synonyms[0])  # first synonym is NCIt concept from caDSR
        statements.append(create_entity_cypher_stmt(ncit_term)[0])
        statements.append(
            generate_cypher_to_link_term_synonyms(
                pv_term,
                ncit_term,
                "caDSR",
                _commit,
            ),
        )
        for syn_attrs in synonyms[1:]:  # rest from NCIm mappings
            syn_term = Term(syn_attrs)
            statements.append(create_entity_cypher_stmt(syn_term)[0])
            statements.append(
                generate_cypher_to_link_term_synonyms(
                    ncit_term,
                    syn_term,
                    "NCIm",
                    _commit,
                ),
            )

    # create changesets for each statement
    cs_id = changeset_id
    for stmt in statements:
        str_stmt = str(stmt).replace("\\'", "'")
        changesets.append(
            Changeset(
                id=str(cs_id),
                author=author,
                change_type=CypherChange(text=str_stmt),
            ),
        )
        cs_id += 1

    del statements  # garbage collection
    return changesets


def convert_model_cdes_to_changelog(
    model_cdes: ModelCDESpec,
    author: str | None = None,
    _commit: str | None = None,
) -> Changelog:
    """Convert model cde annotations with PVs and synonyms to Liquibase Changelog."""
    changelog = Changelog()
    changeset_id = 1
    if not author:
        author = DEFAULT_AUTHOR
    if not _commit:
        _commit = DEFAULT_COMMIT
    for annotation in tqdm(model_cdes["annotations"], desc="Annotations"):
        msg = f"Annotation: {annotation['entity'].get('key', '')}"
        logger.info(msg)
        changesets = convert_annotation_to_changesets(
            annotation,
            changeset_id,
            author,
            _commit,
        )
        if not changesets:
            continue
        changeset_id += len(changesets)
        for changeset in tqdm(changesets, desc="Changesets", total=len(changesets)):
            changelog.add_changeset(changeset)
        del changesets  # garbage collection
    return changelog
