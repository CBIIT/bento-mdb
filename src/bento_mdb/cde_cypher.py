"""Cypher generation for CDE PVs and Synonyms."""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, cast

from bento_meta.model import make_nanoid
from bento_meta.objects import Term, ValueSet
from liquichange.changelog import Changelog, Changeset, CypherChange
from tqdm import tqdm

from bento_mdb.cypher_utils import (
    DEFAULT_AUTHOR,
    DEFAULT_COMMIT,
    Statement,
    create_entity_cypher_stmt,
    create_relationship_cypher_stmt,
    cypher_string_literal,
    generate_cypher_to_link_term_alternates,
    generate_cypher_to_link_term_synonyms,
    normalize_identity_text,
    normalize_optional_version,
)

if TYPE_CHECKING:
    from bento_mdb.cypher_utils import Statement
    from bento_mdb.datatypes import AnnotationSpec, ModelCDESpec

logger = logging.getLogger(__name__)

CDE_BASE_URL = (
    "https://cadsrapi.cancer.gov/rad/NCIAPI/1.0/api/DataElement/"
)

def get_cde_value_set_handle(
    cde_id: object | None,
    cde_version: object | None,
) -> str:
    """Return the canonical CDE value-set handle."""
    normalized_id = normalize_identity_text(cde_id)
    normalized_version = normalize_optional_version(cde_version)

    if not normalized_id:
        msg = "Cannot create a CDE value set without a CDE ID."
        raise ValueError(msg)

    return f"{normalized_id}|{normalized_version}"


def get_cde_value_set_url(
    cde_id: object | None,
    cde_version: object | None,
) -> str:
    """Return a caDSR URL without null-like version parameters."""
    normalized_id = normalize_identity_text(cde_id)
    normalized_version = normalize_optional_version(cde_version)

    if not normalized_id:
        msg = "Cannot create a CDE value-set URL without a CDE ID."
        raise ValueError(msg)

    url = f"{CDE_BASE_URL}{normalized_id}"
    if normalized_version:
        url += f"?version={normalized_version}"

    return url

def create_cde_value_set_cypher(
    cde_id: object | None,
    cde_version: object | None,
    _commit: str | None,
) -> Statement:
    """Merge a CDE value set using only CDE ID and version identity."""
    handle = get_cde_value_set_handle(cde_id, cde_version)
    url = get_cde_value_set_url(cde_id, cde_version)

    return Statement(
        " ".join(
            [
                "MERGE (vs:value_set "
                f"{{handle: {cypher_string_literal(handle)}}})",
                "ON CREATE SET "
                f"vs.nanoid = {cypher_string_literal(make_nanoid())}, "
                f"vs._commit = {cypher_string_literal(_commit)}",
                f"SET vs.url = {cypher_string_literal(url)}",
            ],
        ),
    )

def create_delete_pv_cypher(
    pv_value: str,
    pv_origin_id: str,
    pv_origin_version: str,
    cde_id: str,
    cde_ver: str,
) -> str:
    """Delete only the CDE value-set-to-PV relationship."""
    handle = get_cde_value_set_handle(cde_id, cde_ver)

    return (
        f"MATCH (vs:value_set {{handle: {cypher_string_literal(handle)}}})"
        "-[r:has_term]->(pv:term) "
        "WHERE toLower(coalesce(pv.origin_name, '')) CONTAINS 'cadsr' "
        f"AND coalesce(pv.origin_id, '') = "
        f"{cypher_string_literal(pv_origin_id)} "
        f"AND coalesce(pv.value, '') = "
        f"{cypher_string_literal(pv_value)} "
        f"AND coalesce(pv.origin_version, '') = "
        f"{cypher_string_literal(pv_origin_version)} "
        "DELETE r"
    )


def _generate_edp_link_cypher(
    cde_id: str,
    cde_version: str | None,
    edp_origin_id: str,
    edp_origin_name: str,
    edp_origin_version: str | None = None,
) -> str:
    """Cypher to link a CDE term to its EDP value_set via specifies_value_set."""
    cde_id_literal = cypher_string_literal(cde_id)
    edp_origin_id_literal = cypher_string_literal(edp_origin_id)
    edp_origin_name_literal = cypher_string_literal(edp_origin_name)

    edp_filters = [
    f"edp.origin_name = {edp_origin_name_literal}",
    f"edp.origin_id = {edp_origin_id_literal}",
    ]
    if edp_origin_version:
        edp_filters.append(f"edp.origin_version = {cypher_string_literal(edp_origin_version)}")

    cde_filters = [
        "toLower(cde.origin_name) CONTAINS 'cadsr'",
    ]
    if cde_version:
        cde_filters.append(f"cde.origin_version = {cypher_string_literal(cde_version)}")

    return (
        f"MATCH (cde:term {{origin_id: {cde_id_literal}}}) "
        f"WHERE {' AND '.join(cde_filters)} "
        f"MATCH (edp:term) "
        f"WHERE {' AND '.join(edp_filters)} "
        f"MATCH (edp)-[:specifies_value_set]->(vs:value_set) "
        f"MERGE (cde)-[:specifies_value_set]->(vs)"
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
    
    # Check for EDP reference, then if it exists, emit only the specifies_value_set relationship
    edp_ref = annotation.get("edp_reference")
    if edp_ref:
        cde_attrs = annotation["annotation"]["attrs"]
        cde_id = cde_attrs.get("origin_id", "")
        cde_version = cde_attrs.get("origin_version")
        stmt = _generate_edp_link_cypher(
            cde_id,
            cde_version,
            edp_ref["origin_id"],
            edp_ref["origin_name"],
            edp_ref.get("origin_version"),
        )
        return [Changeset(id=str(changeset_id), author=author, change_type=CypherChange(text=stmt))]
    
    if not (has_new_pvs or has_removed_pvs or has_metadata_changes):
        return []
    
    statements: list[Statement] = []
    changesets = []
    cde_attrs = annotation["annotation"]["attrs"]
    cde_id = normalize_identity_text(cde_attrs.get("origin_id"))
    if not cde_id:
        raise ValueError("Cannot process a CDE annotation without a CDE ID.")
    
    # Get old and new versions
    old_ver = normalize_optional_version(
        cde_attrs.get("origin_version"),
    )
    new_ver = normalize_optional_version(
        annotation.get("CDEVersion"),
    )
    target_ver = new_ver or old_ver
    
    # MERGE ValueSet node with target version (new if changed, old if not)
    cde_vs = ValueSet(
    {
        "handle": get_cde_value_set_handle(cde_id, target_ver),
        "url": get_cde_value_set_url(cde_id, target_ver),
        "_commit": _commit,
    },
    )
    statements.append(
        create_cde_value_set_cypher(
            cde_id,
            target_ver,
            _commit,
        ),
    )
    
    # Handle removed PVs (delete relationship from the OLD value set)
    removed_pvs = annotation.get("removed_pvs", [])
    if removed_pvs:
        logger.info("Removing %d PVs from %s", len(removed_pvs), cde_id)
        for pv_obj in removed_pvs:
            pv_value = pv_obj["value"]
            pv_origin_id = pv_obj["origin_id"]
            pv_origin_version = pv_obj.get("origin_version", "")
            # Skip when origin_version is missing to avoid ambiguous unlink.
            if not pv_origin_version:
                logger.warning(
                    "Skip unlink for removed PV due to empty origin_version: cde=%s version=%s pv_origin_id=%s pv_value=%s",
                    cde_id,
                    old_ver,
                    pv_origin_id,
                    pv_value,
                )
                continue
            delete_stmt = create_delete_pv_cypher(
                pv_value,
                pv_origin_id,
                pv_origin_version,
                cde_id,
                old_ver,
            )
            statements.append(delete_stmt)  # type: ignore
            logger.info(
                "Unlinked removed PV from value set: cde=%s version=%s pv_origin_id=%s pv_origin_version=%s pv_value=%s",
                cde_id,
                old_ver,
                pv_origin_id,
                pv_origin_version,
                pv_value,
            )

    # Update annotation term if CDE name changed
    cde_full_name = annotation.get("CDEFullName")

    if cde_full_name:
        # Match by origin_id only
        match_clause = (
            f"MATCH (t:term {{origin_id: '{cde_id}'}}) "
            f"WHERE toLower(t.origin_name) CONTAINS 'cadsr' "
        )
        set_clauses = []

        logger.info("Updating CDE name for %s to: %s", cde_id, cde_full_name)
        escaped_name = cypher_string_literal(cde_full_name)
        set_clauses.append(f"t.value = {escaped_name}")

        # Note: The CADsr CDE version is not updated; it should be determined by the data model.
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
        # separate synonyms and alternates from pv attrs
        synonyms = cast("list[dict[str, str | None]]", pv_copy.pop("synonyms"))
        pv_alternates = cast("list[dict[str, str]]", pv_copy.pop("alternates", []))
        pv_term = Term(pv_copy)
        pv_term._commit = _commit  # noqa: SLF001
        statements.append(create_entity_cypher_stmt(pv_term)[0])
        statements.append(
            create_relationship_cypher_stmt(cde_vs, "has_term", pv_term)[0],
        )

        if synonyms:
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
        
        # PV - alternate names as concepts via represents relationship
        if pv_alternates:
            for alt_dict in pv_alternates:
                alt_name = alt_dict.get("value", "")
                if not alt_name:
                    continue
                alt_attrs = {
                    "value": alt_name,
                    "origin_id": pv_term.origin_id,
                    "origin_version": pv_term.origin_version,
                    "origin_name": "caDSR_alternates",
                    "_commit": _commit,
                }
                alt_term = Term(alt_attrs)
                statements.append(create_entity_cypher_stmt(alt_term)[0])
                statements.append(
                    generate_cypher_to_link_term_alternates(
                        pv_term,
                        alt_term,
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
