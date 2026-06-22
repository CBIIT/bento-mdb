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

logger = logging.getLogger(__name__)


def _to_snake_case(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _escape(value: str) -> str:
    return value.replace("'", "\\'")


def _load_yaml(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_terms(terms_files: list[Path]) -> dict:
    terms = {}
    for terms_file in terms_files:
        data = _load_yaml(terms_file)
        terms.update(data.get("Terms") or {})
    return terms


def _normalize_term_spec(spec: dict, *, fallback_value: str | None = None) -> dict:
    value = spec.get("Value") or fallback_value or ""
    return {
        "origin_name": spec.get("Origin") or "",
        "origin_id": str(spec.get("Code") or ""),
        "origin_version": str(spec.get("Version") or ""),
        "value": str(value),
        "origin_definition": spec.get("Definition") or "",
    }


def _edp_specs_from_files(edp_yaml_files: list[Path]) -> list[tuple[str, dict]]:
    edp_specs = []
    for edp_yaml_file in edp_yaml_files:
        data = _load_yaml(edp_yaml_file)
        for prop_handle, spec in (data.get("PropDefinitions") or {}).items():
            if spec.get("Ext") is True:
                edp_specs.append((prop_handle, spec))
    return edp_specs


def _filter_edp_specs_from_config(
    edp_specs: list[tuple[str, dict]],
    edp_config_file: Path | None,
) -> list[tuple[str, dict]]:
    if not edp_config_file:
        return edp_specs

    config = _load_yaml(edp_config_file)
    allowed = {
        (
            spec.get("prop_definition"),
            str(spec.get("latest_version")),
        )
        for spec in config.values()
        if spec.get("prop_definition") and spec.get("latest_version") is not None
    }

    filtered = []
    for prop_handle, spec in edp_specs:
        term = spec.get("Term") or {}
        version = str(term.get("Version") or "")
        if (prop_handle, version) in allowed:
            filtered.append((prop_handle, spec))

    return filtered


def _generate_edp_changesets(
    prop_handle: str,
    spec: dict,
    terms: dict,
    author: str,
    _commit: str,
    start_id: int,
) -> list[Changeset]:
    """Generate changesets for one EDP definition."""
    term_spec = spec.get("Term")
    if not isinstance(term_spec, dict):
        msg = f"EDP '{prop_handle}' must define Term as a mapping."
        raise ValueError(msg)

    enum_values = spec.get("Enum") or []
    if not isinstance(enum_values, list):
        msg = f"EDP '{prop_handle}' must define Enum as a list."
        raise ValueError(msg)

    edp = _normalize_term_spec(term_spec)
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
        Changeset(id=str(cs_id), author=author, change_type=CypherChange(text=edp_term_stmt))
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
        Changeset(id=str(cs_id), author=author, change_type=CypherChange(text=vs_stmt))
    )
    cs_id += 1

    for enum_value in enum_values:
        pv_spec = terms.get(enum_value)
        if not pv_spec:
            msg = f"EDP '{prop_handle}' references enum value '{enum_value}' with no matching Terms entry."
            raise ValueError(msg)

        pv = _normalize_term_spec(pv_spec, fallback_value=str(enum_value))
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
    edp_config_file: Path | None = None,
) -> Changelog:
    """Parse EDP YAML files and generate a Liquibase changelog."""
    terms = _load_terms(terms_files)
    edp_specs = _filter_edp_specs_from_config(
        _edp_specs_from_files(edp_yaml_files),
        edp_config_file,
)
    changelog = Changelog()
    cs_id = 1

    for prop_handle, spec in edp_specs:
        logger.info("Generating changesets for EDP definition: %s", prop_handle)
        changesets = _generate_edp_changesets(
            prop_handle,
            spec,
            terms,
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