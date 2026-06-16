"""Generate Liquibase changelog for EDP definitions."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import click
from bento_mdf.mdf import MDFReader
from liquichange.changelog import Changelog, Changeset, CypherChange

from bento_mdb.cypher_utils import DEFAULT_AUTHOR, DEFAULT_COMMIT
from bento_mdb.model_cdes import get_edp_enum_term

logger = logging.getLogger(__name__)


def _to_snake_case(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _escape(value: str) -> str:
    return value.replace("'", "\\'")


def _generate_edp_changesets(
    prop,
    author: str,
    _commit: str,
    start_id: int,
) -> list[Changeset]:
    """Generate all changesets for a single EDP property (bento-meta Property object)."""
    edp_term = get_edp_enum_term(prop)
    if not edp_term:
        return []

    origin_name = edp_term.origin_name or ""
    origin_id = edp_term.origin_id or ""
    origin_version = edp_term.origin_version or ""
    value = edp_term.value or ""
    definition = edp_term.origin_definition or ""
    handle = _to_snake_case(value) if value else _to_snake_case(prop.handle)

    changesets = []
    cs_id = start_id

    # 1. MERGE the EDP term node
    edp_term_stmt = (
        f"MERGE (edp:term {{origin_name: '{_escape(origin_name)}', origin_id: '{_escape(origin_id)}'}}) "
        f"SET edp.handle = '{_escape(handle)}', "
        f"edp.value = '{_escape(value)}', "
        f"edp.origin_version = '{_escape(origin_version)}', "
        f"edp.origin_definition = '{_escape(definition)}', "
        f"edp._commit = '{_escape(_commit)}'"
    )
    changesets.append(
        Changeset(id=str(cs_id), author=author, change_type=CypherChange(text=edp_term_stmt))
    )
    cs_id += 1

    # 2. MERGE value_set and link to EDP term via specifies_value_set
    vs_handle = f"{origin_id}|{origin_version}"
    vs_stmt = (
        f"MATCH (edp:term {{origin_name: '{_escape(origin_name)}', origin_id: '{_escape(origin_id)}'}}) "
        f"MERGE (vs:value_set {{handle: '{_escape(vs_handle)}'}}) "
        f"SET vs._commit = '{_escape(_commit)}' "
        f"MERGE (edp)-[:specifies_value_set]->(vs)"
    )
    changesets.append(
        Changeset(id=str(cs_id), author=author, change_type=CypherChange(text=vs_stmt))
    )
    cs_id += 1
    pv_terms = prop.value_set.terms if prop.value_set else {}
    # 3. MERGE each PV term from the value_set and link via has_term
    # bento-mdf merges Terms section definitions into value_set.terms by value
    for pv_term in pv_terms.values():
        pv_origin = pv_term.origin_name or ""
        pv_code = pv_term.origin_id or ""
        pv_value = pv_term.value or ""
        pv_version = pv_term.origin_version or ""
        pv_definition = pv_term.origin_definition or ""
        pv_handle = _to_snake_case(pv_value) if pv_value else pv_code

        if not pv_code:
            logger.warning("PV term '%s' has no origin_id, skipping", pv_value)
            continue

        pv_stmt = (
            f"MERGE (pv:term {{origin_name: '{_escape(pv_origin)}', origin_id: '{_escape(pv_code)}'}}) "
            f"SET pv.handle = '{_escape(pv_handle)}', "
            f"pv.value = '{_escape(pv_value)}', "
            f"pv.origin_version = '{_escape(pv_version)}', "
            f"pv.origin_definition = '{_escape(pv_definition)}', "
            f"pv._commit = '{_escape(_commit)}'"
        )
        changesets.append(
            Changeset(id=str(cs_id), author=author, change_type=CypherChange(text=pv_stmt))
        )
        cs_id += 1

        link_stmt = (
            f"MATCH (vs:value_set {{handle: '{_escape(vs_handle)}'}}) "
            f"MATCH (pv:term {{origin_name: '{_escape(pv_origin)}', origin_id: '{_escape(pv_code)}'}}) "
            f"MERGE (vs)-[:has_term]->(pv)"
        )
        changesets.append(
            Changeset(id=str(cs_id), author=author, change_type=CypherChange(text=link_stmt))
        )
        cs_id += 1

    return changesets


def generate_edp_changelog(
    edp_yaml_files: list[Path],
    terms_files: list[Path],
    author: str = DEFAULT_AUTHOR,
    _commit: str = DEFAULT_COMMIT,
) -> Changelog:
    """Parse EDP YAML files via bento-mdf and generate a Liquibase changelog."""
    # Pass all files to MDFReader — it handles merging Terms into value_set.terms
    all_files = list(edp_yaml_files) + list(terms_files)
    logger.info("Loading EDP files via MDFReader: %s", [str(f) for f in all_files])
    mdf = MDFReader(*all_files)
    model = mdf.model

    changelog = Changelog()
    cs_id = 1

    for prop_key, prop in model.props.items():
        edp_term = get_edp_enum_term(prop)
        if not edp_term:
            continue

        logger.info("Generating changesets for EDP property: %s", prop_key)
        changesets = _generate_edp_changesets(prop, author, _commit, cs_id)
        for cs in changesets:
            changelog.add_changeset(cs)
        cs_id += len(changesets)

    if cs_id == 1:
        logger.warning("No EDP properties found in provided files.")

    return changelog


@click.command()
@click.option(
    "--edp_yaml_files",
    multiple=True,
    required=True,
    help="Paths to EDP props YAML files (e.g. edp-props.yml).",
)
@click.option(
    "--terms_files",
    multiple=True,
    required=True,
    help="Paths to terms YAML files (e.g. obib-terms.yml).",
)
@click.option("--output_file", required=True, help="Output Liquibase XML changelog path.")
@click.option("--author", default=DEFAULT_AUTHOR, help="Author for changesets.")
@click.option("--_commit", default=DEFAULT_COMMIT, help="Commit SHA for changesets.")
def main(
    edp_yaml_files: tuple[str, ...],
    terms_files: tuple[str, ...],
    output_file: str,
    author: str,
    _commit: str,
) -> None:
    """CLI entry point: generate EDP changelog from YAML files."""
    edp_paths = [Path(f) for f in edp_yaml_files]
    terms_paths = [Path(f) for f in terms_files]
    changelog = generate_edp_changelog(edp_paths, terms_paths, author=author, _commit=_commit)
    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(changelog.to_xml(), encoding="utf-8")
    click.echo(f"Written: {out}")