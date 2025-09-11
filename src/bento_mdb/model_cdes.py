"""Contains functions to work with CDEs that annotate CRDC data model entities."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from bento_meta.mdb.mdb import MDB
    from bento_meta.model import Model

    from bento_mdb_updates.clients import CADSRClient, NCItClient
    from bento_mdb_updates.datatypes import (
        MDBCDESpec,
        ModelCDESpec,
        ModelSpec,
        PermissibleValue,
    )

logger = logging.getLogger(__name__)


def load_model_specs_from_yaml(yaml_file: Path) -> dict[str, ModelSpec]:
    """Load model specs from YAML file."""
    with Path(yaml_file).open(mode="r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as exc:
            msg = f"Error parsing YAML file {yaml_file}: {exc}"
            raise yaml.YAMLError(msg) from exc


def get_yaml_files_from_spec(
    model_spec: ModelSpec,
    model: str,
    version: str | None = None,
) -> list[str]:
    """Get YAML file urls from model spec for a given version."""
    if not version:
        version = model_spec["latest_version"]
    mdf_directory = model_spec.get("mdf_directory", "")
    mdf_files = model_spec.get("mdf_files", [])

    is_prerelease = bool(re.search(r"-[a-f0-9]{7}$", version, re.IGNORECASE))
    if is_prerelease:
        logger.info("Is prerelease version: %s", version)
        repo = "CBIIT/crdc-datahub-models"
        tag = "dev2"
        mdf_directory = f"cache/{model}/{model_spec['latest_prerelease_version']}"
    else:
        repo = model_spec.get("repository")
        version_entry = next(
            (v for v in model_spec.get("versions", []) if v["version"] == version),
            None,
        )
        if not version_entry:
            msg = f"Version {version} not found in model spec."
            raise ValueError(msg)

        tag = version_entry.get("tag", version)

    if not repo:
        msg = "Model spec must have a repository."
        raise ValueError(msg)
    if not mdf_files:
        msg = "Model spec must have file names for MDF files."
        raise ValueError(msg)

    base_url = f"https://raw.githubusercontent.com/{repo}/{tag}/{mdf_directory}"
    return [f"{base_url}/{file}" for file in mdf_files]


def count_model_cdes(model: Model) -> int:
    """Count CDEs in a model."""
    count = 0
    for term_key in model.terms:
        if "cadsr" in term_key[1].lower():
            count += 1
    return count


def make_model_cde_spec(model: Model) -> ModelCDESpec:
    """Get CDEs from a bento-meta model."""
    cde_spec: ModelCDESpec = {
        "handle": str(model.handle),
        "version": str(model.version),
        "annotations": [],
    }
    for entity_type in ["nodes", "edges", "props"]:
        model_entities = getattr(model, entity_type)
        for entity_key, entity in model_entities.items():
            if not entity.concept or not entity.concept.terms:
                continue
            for term_key, term in entity.concept.terms.items():
                # if 'caDSR' not in origin name, not a CDE
                if "cadsr" not in term_key[1].lower():
                    continue
                cde_spec["annotations"].append(
                    {
                        "entity": {
                            "key": entity_key,
                            "attrs": entity.get_attr_dict(),
                            "entity_has_enum": bool(entity.value_set),
                        },
                        "annotation": {
                            "key": term_key,
                            "attrs": term.get_attr_dict(),
                        },
                        "value_set": [],
                    },
                )
    return cde_spec


def dump_to_yaml(py_object: object, yaml_file: Path) -> None:
    """Safe dump Python object to YAML file."""
    with Path(yaml_file).open(mode="w", encoding="utf-8") as f:
        yaml.safe_dump(
            py_object,
            f,
            sort_keys=False,
            default_flow_style=False,
        )


def add_cde_pvs_to_model_cde_spec(
    cde_spec: ModelCDESpec,
    cadsr_client: CADSRClient,
) -> None:
    """Add CDE PVs to a ModelCDESpec."""
    logger.info("Getting CDE value sets from caDSR...")
    for annotation in cde_spec["annotations"]:
        cde_id = annotation["annotation"]["attrs"].get("origin_id")
        cde_version = annotation["annotation"]["attrs"].get("origin_version")
        entity_key = str(annotation["entity"]["key"])
        value_set = cadsr_client.fetch_cde_valueset(
            cde_id,
            cde_version,
            entity_key,
        )
        if not value_set:
            continue
        annotation["value_set"] = value_set


def add_ncit_synonyms_to_model_cde_spec(
    cde_spec: ModelCDESpec,
    ncit_client: NCItClient,
) -> None:
    """Add NCIt synonyms to a ModelCDESpec."""
    logger.info("Getting synonyms from NCIt...")
    for annotation in cde_spec["annotations"]:
        value_set = annotation.get("value_set", [])
        for pv in value_set:
            if pv is None:
                continue
            ncit_concept_codes = pv["ncit_concept_codes"]
            if len(ncit_concept_codes) > 1:
                msg = "Multiple NCIt concepts found for PV: %s: %s"
                logger.warning(
                    msg,
                    pv["value"],
                    ncit_concept_codes,
                )
            for code in ncit_concept_codes:
                if not code or code not in ncit_client.ncim_mapping:
                    continue
                syn_dicts = ncit_client.ncim_mapping[code]
                for syn_attrs in syn_dicts:
                    pv["synonyms"].append(syn_attrs)

        annotation["value_set"] = value_set


def load_model_cde_spec(model_handle: str, model_version: str) -> ModelCDESpec:
    """Load model cdes from spec."""
    cde_dir = Path().cwd() / "data/output/model_cde_pvs"
    model_cdes_yml = cde_dir / model_handle / f"{model_handle}_{model_version}_cdes.yml"

    with model_cdes_yml.open(mode="r", encoding="utf-8") as f:
        try:
            return yaml.load(f, Loader=yaml.FullLoader)  # noqa: S506
        except yaml.YAMLError as e:
            msg = f"Error parsing YAML file {model_cdes_yml}: {e}"
            raise ValueError(msg) from e


def compare_model_specs_to_mdb(
    model_specs: dict[str, ModelSpec],
    mdb: MDB,
    *,
    datahub_only: bool = False,
    include_prerelease: bool = False,
) -> dict[str, list[str]]:
    """Get model versions from Model Spec yaml that aren't in an MDB."""
    mdb_models = mdb.models
    spec_models = {}
    for model, spec in model_specs.items():
        if datahub_only and not spec.get("in_data_hub", False):
            continue
        versions = [
            v["version"] for v in spec["versions"] if not v.get("ignore", False)
        ]
        if include_prerelease and spec.get("latest_prerelease_commit"):
            commit_short = spec["latest_prerelease_commit"][:7]
            prerelease_base_version = spec.get(
                "latest_prerelease_version",
                spec.get("latest_version", "unknown"),
            )
            prerelease_version = f"{prerelease_base_version}-{commit_short}"
            versions.append(prerelease_version)
        spec_models[model] = versions

    logger.info("MDB models=%s", mdb_models)
    logger.info("Spec models=%s", spec_models)
    return {
        model: sorted(set(versions) - set(mdb_models.get(model, [])))
        for model, versions in spec_models.items()
        if set(versions) - set(mdb_models.get(model, []))
    }


def get_cdes_from_mdb(mdb: MDB) -> list[MDBCDESpec]:
    """Get CDEs, CDE PVs, PV Synonyms mapped by NCIt from an MDB."""
    qry = (
        "MATCH (cde:term) WHERE toLower(cde.origin_name) CONTAINS 'cadsr' WITH cde "
        "OPTIONAL MATCH (ent)-[:has_property]->(p:property)-[:has_concept]->(:concept)"
        "<-[:represents]-(cde) WHERE p.model IS NOT NULL AND p.version IS NOT NULL "
        "WITH cde, COLLECT(DISTINCT {model: p.model, version: p.version, "
        "property: ent.handle + '.' + p.handle}) AS models "
        "WITH cde, models, cde.origin_id + '|' + COALESCE(cde.origin_version, '') "
        "AS cde_hdl OPTIONAL MATCH (vs:value_set {handle: cde_hdl})-[:has_term]->"
        "(pv:term) WITH cde, models, COLLECT(DISTINCT pv) AS pvs "
        "WHERE size(pvs) > 0 UNWIND pvs as pv "
        "OPTIONAL MATCH (pv)-[:represents]->(c_cadsr:concept)<-[:represents]-"
        "(ncit_term:term {origin_name: 'NCIt'}), "
        "(c_cadsr)-[:has_tag]->(:tag {key: 'mapping_source', value: 'caDSR'}) "
        "OPTIONAL MATCH (ncit_term)-[:represents]->(c_ncim:concept)<-[:represents]-"
        "(syn:term), (c_ncim)-[:has_tag]->(:tag {key: 'mapping_source', value: 'NCIm'})"
        " WHERE pv <> syn AND pv.value <> syn.value "
        "WITH cde, models, pv, COLLECT(DISTINCT {value: syn.value, origin_id: "
        "syn.origin_id, origin_name: syn.origin_name, origin_version: "
        "syn.origin_version}) AS synonyms "
        "WITH cde, models, COLLECT(DISTINCT {value: pv.value, origin_id: pv.origin_id, "
        "origin_definition: pv.origin_definition, origin_version: pv.origin_version, "
        "origin_name: pv.origin_name, synonyms: synonyms}) "
        "AS permissibleValues "
        "RETURN cde.origin_id AS CDECode, cde.origin_version AS CDEVersion, "
        "cde.value AS CDEFullName, cde.origin_name AS CDEOrigin, "
        "models, permissibleValues "
    )
    return mdb.get_with_statement(qry)  # type: ignore ReportReturnType


def set_ncit_concept_codes(pv: PermissibleValue) -> None:
    """Set ncit_concept_codes for a PV with NCIt synonyms."""
    pv["ncit_concept_codes"] = sorted(
        {
            syn["origin_id"]
            for syn in pv.get("synonyms", [])
            if syn.get("origin_name") == "NCIt" and syn.get("origin_id") is not None
        },
    )


def process_mdb_cdes(mdb_cdes: list[MDBCDESpec]) -> None:
    """Perform additional processing on MDB CDEs."""
    for cde_spec in mdb_cdes:
        for pv in cde_spec["permissibleValues"]:
            set_ncit_concept_codes(pv)
