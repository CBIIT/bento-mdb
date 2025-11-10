"""Cypher generation for CDE PVs and Synonyms."""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, cast

from bento_meta.objects import Term, ValueSet
from liquichange.changelog import Changelog, Changeset, CypherChange
from tqdm import tqdm

from bento_mdb.cypher_utils import (
    DEFAULT_AUTHOR,
    DEFAULT_COMMIT,
    create_entity_cypher_stmt,
    create_relationship_cypher_stmt,
    generate_cypher_to_link_term_synonyms,
)

if TYPE_CHECKING:
    from bento_mdb.cypher_utils import Statement
    from bento_mdb.datatypes import AnnotationSpec, ModelCDESpec

logger = logging.getLogger(__name__)


def create_delete_pv_cypher(
    pv_origin_id: str,
    pv_origin_version: str,
    cde_id: str,
    cde_ver: str,
) -> str:
    """Create Cypher DELETE statement for a removed PV.
    
    Deletes only the relationship between PV and ValueSet, not the PV node itself.
    This is safer in case the PV is used by other ValueSets.
    """
    return (
        f"MATCH (pv:term {{origin_id: '{pv_origin_id}', origin_version: '{pv_origin_version}'}})"
        f"-[r:has_term]-"
        f"(vs:value_set {{handle: '{cde_id}|{cde_ver}'}}) "
        f"WHERE toLower(pv.origin_name) CONTAINS 'cadsr' "
        f"DELETE r"
    )


def convert_annotation_to_changesets(
    annotation: AnnotationSpec,
    changeset_id: int,
    author: str | None = None,
    _commit: str | None = DEFAULT_COMMIT,
) -> list[Changeset]:
    """Convert annotation to list of Liquibase Changesets."""
    # Check if there are any changes to process
    has_new_pvs = annotation.get("value_set") and len(annotation.get("value_set", [])) > 0
    has_removed_pvs = annotation.get("removed_pvs") and len(annotation.get("removed_pvs", [])) > 0
    has_metadata_changes = annotation.get("CDEFullName") or annotation.get("CDEVersion")
    
    if not (has_new_pvs or has_removed_pvs or has_metadata_changes):
        return []
    statements: list[Statement] = []
    changesets = []
    cde_attrs = annotation["annotation"]["attrs"]
    base_url = "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/"
    cde_id = cde_attrs.get("origin_id", "")
    
    # Get old and new versions
    old_ver = cde_attrs.get("origin_version", "")
    if old_ver is None:
        old_ver = ""
    new_ver = annotation.get("CDEVersion")  # New version if changed, None otherwise
    
    # Use new version for ValueSet if version changed, otherwise use old version
    target_ver = new_ver if new_ver else old_ver
    
    # MERGE ValueSet node with target version (new if changed, old if not)
    cde_vs = ValueSet(
        {
            "url": f"{base_url}{cde_id}{f'?version={target_ver}' if target_ver else ''}",
            "handle": f"{cde_id}|{target_ver}",
            "_commit": _commit,
        },
    )
    statements.append(create_entity_cypher_stmt(cde_vs)[0])
    
    # Handle removed PVs (delete relationship from the OLD value set)
    removed_pvs = annotation.get("removed_pvs", [])
    if removed_pvs:
        logger.info("Removing %d PVs from %s", len(removed_pvs), cde_id)
        for pv_obj in removed_pvs:
            pv_origin_id = pv_obj["origin_id"]
            pv_origin_version = pv_obj.get("origin_version", "")
            delete_stmt = create_delete_pv_cypher(pv_origin_id, pv_origin_version, cde_id, old_ver)
            statements.append(delete_stmt)  # type: ignore

    # Update annotation term if CDE name or version changed
    cde_full_name = annotation.get("CDEFullName")
    cde_version = annotation.get("CDEVersion")

    if cde_full_name or cde_version:
        # Match by origin_id only (version may have changed)
        match_clause = (
            f"MATCH (t:term {{origin_id: '{cde_id}'}}) "
            f"WHERE toLower(t.origin_name) CONTAINS 'cadsr' "
        )
        set_clauses = []

        if cde_full_name:
            logger.info("Updating CDE name for %s to: %s", cde_id, cde_full_name)
            escaped_name = cde_full_name.replace("'", "\\'")
            set_clauses.append(f"t.value = '{escaped_name}'")

        if cde_version:
            old_ver = cde_attrs.get("origin_version", "")
            logger.info("Updating CDE version for %s: '%s' -> '%s'", cde_id, old_ver, cde_version)
            escaped_version = cde_version.replace("'", "\\'")
            set_clauses.append(f"t.origin_version = '{escaped_version}'")

        if set_clauses:
            update_term_stmt = match_clause + "SET " + ", ".join(set_clauses)
            statements.append(update_term_stmt)  # type: ignore
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
