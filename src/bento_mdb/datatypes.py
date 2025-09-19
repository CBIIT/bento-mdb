"""Data types for CDE PVs and Synonyms."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from pathlib import Path


class ModelSpec(TypedDict):
    """CRDC model spec. Dict with model repository info and MDF file details."""

    repository: str
    mdf_directory: str
    mdf_files: list[str | Path]
    in_data_hub: bool
    versions: list[dict[str, Any]]
    latest_version: str
    latest_prerelease_commit: str | None
    latest_prerelease_version: str | None


class PermissibleValue(TypedDict):
    """
    Permissible value dict w/ CDE PV term attributes and synonyms list.

    id & definition refer to ValueMeaning of the Permissible Value.
    synonyms: initiated with NCIt synonym(s) from 'Concepts' for the PV if available.
    """

    value: str
    origin_id: str
    origin_definition: str
    origin_version: str
    origin_name: str
    ncit_concept_codes: list[str | None]
    synonyms: list[dict[str, str | None]]


class AnnotationSpec(TypedDict):
    """Annotation spec."""

    entity: dict
    annotation: dict
    value_set: list[PermissibleValue | None]


class ModelCDESpec(TypedDict):
    """CRDC model CDE spec."""

    handle: str
    version: str
    annotations: list[AnnotationSpec]


class MDBModelSpec(TypedDict):
    """MDB Model Spec."""

    model: str
    version: str
    property: str


class MDBSynSpec(TypedDict):
    """MDB CDE Synonym Spec."""

    value: str
    origin_id: str | None
    origin_name: str | None
    origin_version: str | None


class MDBCDESpec(TypedDict):
    """MDB CDE Spec."""

    CDECode: str
    CDEVersion: str | None
    CDEFullName: str
    CDEOrigin: str
    models: list[MDBModelSpec]
    permissibleValues: list[PermissibleValue]
