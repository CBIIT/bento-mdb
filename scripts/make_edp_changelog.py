"""Generate Liquibase changelog for EDP definitions."""

from __future__ import annotations
import xml.etree.ElementTree as ET
import logging
import re
from pathlib import Path
import yaml
import click
from liquichange.changelog import Changelog, Changeset, CypherChange
from bento_mdb.cypher_utils import DEFAULT_AUTHOR, DEFAULT_COMMIT
from bento_mdf import MDF

logger = logging.getLogger(__name__)

def _load_yaml(path: Path) -> dict:
    """Load a YAML file as a dictionary."""
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _to_snake_case(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _escape(value: str) -> str:
    return value.replace("'", "\\'")


def _term_attrs(term) -> dict:
    """Return normalized term attrs from a bento-meta Term."""
    attrs = term.get_attr_dict()
    return {
        "origin_name": attrs.get("origin_name") or "",
        "origin_id": str(attrs.get("origin_id") or ""),
        "origin_version": str(attrs.get("origin_version") or ""),
        "value": str(attrs.get("value") or ""),
        "origin_definition": attrs.get("origin_definition") or "",
    }


def _edp_definitions_from_files(
    edp_yaml_files: list[Path],
    terms_files: list[Path],
) -> list[tuple[str, object]]:
    """Load EDP definitions using bento-mdf."""
    mdf = MDF(
        *edp_yaml_files,
        *terms_files,
        handle="_EDP",
        raise_error=True,
    )
    edp_definitions = getattr(mdf.model, "edp_definitions", {})
    return list(edp_definitions.items())


def _get_edp_term(prop_handle: str, prop) -> object:
    """Return the single EDP term attached to an EDP property."""
    if not prop.concept or not prop.concept.terms:
        msg = f"EDP '{prop_handle}' must define a Term."
        raise ValueError(msg)

    if len(prop.concept.terms) > 1:
        logger.warning(
            "EDP '%s' has multiple Term entries. Using the first.",
            prop_handle,
        )

    return next(iter(prop.concept.terms.values()))


def _filter_edp_definitions_from_config(
    edp_definitions: list[tuple[str, object]],
    edp_config_file: Path | None,
) -> list[tuple[str, object]]:
    if not edp_config_file:
        return edp_definitions

    config = _load_yaml(edp_config_file)
    allowed = {
        (
            spec.get("property"),
            str(spec.get("latest_version")),
        )
        for spec in config.values()
        if spec.get("property") and spec.get("latest_version") is not None
    }

    filtered = []
    for prop_handle, prop in edp_definitions:
        edp_term = _get_edp_term(prop_handle, prop)
        version = str(getattr(edp_term, "origin_version", "") or "")
        if (prop_handle, version) in allowed:
            filtered.append((prop_handle, prop))

    return filtered


def _generate_edp_changesets(
    prop_handle: str,
    prop,
    author: str,
    _commit: str,
    start_id: int,
) -> list[Changeset]:
    """Generate changesets for one parsed EDP definition."""
    edp_term = _get_edp_term(prop_handle, prop)
    edp = _term_attrs(edp_term)

    origin_name = edp["origin_name"]
    origin_id = edp["origin_id"]
    origin_version = edp["origin_version"]
    value = edp["value"]
    definition = edp["origin_definition"]
    handle = _to_snake_case(value) if value else _to_snake_case(prop_handle)

    changesets = []
    cs_id = start_id

    edp_term_stmt = (
        f"MERGE (edp:term {{origin_name: '{_escape(origin_name)}', origin_id: '{_escape(origin_id)}'}}) "
        f"SET edp.handle = '{_escape(handle)}', "
        f"edp.value = '{_escape(value)}', "
        f"edp.origin_version = '{_escape(origin_version)}', "
        f"edp.origin_definition = '{_escape(definition)}', "
        f"edp._commit = '{_escape(_commit)}'"
    )
    changesets.append(
        Changeset(
            id=str(cs_id),
            author=author,
            change_type=CypherChange(text=edp_term_stmt),
        ),
    )
    cs_id += 1

    vs_handle = f"{origin_id}|{origin_version}"
    vs_stmt = (
        f"MATCH (edp:term {{origin_name: '{_escape(origin_name)}', origin_id: '{_escape(origin_id)}'}}) "
        f"MERGE (vs:value_set {{handle: '{_escape(vs_handle)}'}}) "
        f"SET vs._commit = '{_escape(_commit)}' "
        f"MERGE (edp)-[:specifies_value_set]->(vs)"
    )
    changesets.append(
        Changeset(
            id=str(cs_id),
            author=author,
            change_type=CypherChange(text=vs_stmt),
        ),
    )
    cs_id += 1

    for pv_term_obj in prop.terms.values():
        pv = _term_attrs(pv_term_obj)

        pv_origin = pv["origin_name"]
        pv_code = pv["origin_id"]
        pv_value = pv["value"]
        pv_version = pv["origin_version"]
        pv_definition = pv["origin_definition"]
        pv_handle = _to_snake_case(pv_value) if pv_value else pv_code

        pv_stmt = (
            f"MERGE (pv:term {{origin_name: '{_escape(pv_origin)}', origin_id: '{_escape(pv_code)}'}}) "
            f"SET pv.handle = '{_escape(pv_handle)}', "
            f"pv.value = '{_escape(pv_value)}', "
            f"pv.origin_version = '{_escape(pv_version)}', "
            f"pv.origin_definition = '{_escape(pv_definition)}', "
            f"pv._commit = '{_escape(_commit)}'"
        )
        changesets.append(
            Changeset(
                id=str(cs_id),
                author=author,
                change_type=CypherChange(text=pv_stmt),
            ),
        )
        cs_id += 1

        link_stmt = (
            f"MATCH (vs:value_set {{handle: '{_escape(vs_handle)}'}}) "
            f"MATCH (pv:term {{origin_name: '{_escape(pv_origin)}', origin_id: '{_escape(pv_code)}'}}) "
            f"MERGE (vs)-[:has_term]->(pv)"
        )
        changesets.append(
            Changeset(
                id=str(cs_id),
                author=author,
                change_type=CypherChange(text=link_stmt),
            ),
        )
        cs_id += 1

    return changesets


def generate_edp_changelog(
    edp_yaml_files: list[Path],
    terms_files: list[Path],
    author: str = DEFAULT_AUTHOR,
    _commit: str = DEFAULT_COMMIT,
    edp_config_file: Path | None = None,
) -> Changelog:
    """Parse EDP MDF files with bento-mdf and generate a Liquibase changelog."""
    edp_definitions = _filter_edp_definitions_from_config(
        _edp_definitions_from_files(edp_yaml_files, terms_files),
        edp_config_file,
    )

    changelog = Changelog()
    cs_id = 1

    for prop_handle, prop in edp_definitions:
        logger.info("Generating changesets for EDP definition: %s", prop_handle)
        changesets = _generate_edp_changesets(
            prop_handle,
            prop,
            author,
            _commit,
            cs_id,
        )
        for cs in changesets:
            changelog.add_changeset(cs)
        cs_id += len(changesets)

    if cs_id == 1:
        logger.warning("No EDP definitions found in provided files.")

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
@click.option(
    "--edp_config_file",
    required=False,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
    help="Optional EDP config file used to filter generated EDP versions.",
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
    edp_config_file: str | None,
) -> None:
    """CLI entry point: generate EDP changelog from YAML files."""
    edp_paths = [Path(f) for f in edp_yaml_files]
    terms_paths = [Path(f) for f in terms_files]
    changelog = generate_edp_changelog(
        edp_paths,
        terms_paths,
        author=author,
        _commit=_commit,
        edp_config_file=Path(edp_config_file) if edp_config_file else None,
    )
    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(changelog.to_xml(), encoding="unicode"),
        encoding="utf-8",
    )
    click.echo(f"Written: {out}")