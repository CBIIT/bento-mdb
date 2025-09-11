"""Utilities for testing."""

import io
import re
import zipfile
from typing import Any

import pytest

from bento_mdb_updates.datatypes import (
    AnnotationSpec,
    MDBCDESpec,
    ModelCDESpec,
    ModelSpec,
)


def remove_nanoids_from_str(statement: str) -> str:
    """Remove values for 'nanoid' attr from string if present."""
    return re.sub(r"nanoid:'[^']*'", "nanoid:''", statement)


def assert_equal(actual: Any, expected: Any) -> None:  # noqa: ANN401
    """
    Compare actual and expected results.

    Print both values in case of failure for better debugging.
    """
    if actual != expected:
        print("\n=== ACTUAL ===\n", actual)
        print("\n=== EXPECTED ===\n", expected)
    assert actual == expected


def create_mock_zip(mock_name: str, mock_data: str) -> bytes:
    """Create an in-memory ZIP file containing the mock TSV data."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(mock_name, mock_data)
    zip_buffer.seek(0)  # Reset buffer position
    return zip_buffer.getvalue()


TEST_ANNOTATION_SPEC = AnnotationSpec(
    entity={
        "key": ("study", "organism_species"),
        "attrs": {
            "handle": "organism_species",
            "model": "TEST",
            "value_domain": "value_set",
            "is_required": "Preferred",
            "is_key": "False",
            "is_nullable": "False",
            "is_strict": "True",
            "desc": "Species binomial of study participants",
        },
    },
    annotation={
        "key": ("sample_organism_type", "caDSR"),
        "attrs": {
            "handle": "sample_organism_type",
            "value": "Sample Organism Type",
            "origin_id": "6118266",
            "origin_version": "1.00",
            "origin_name": "caDSR",
        },
    },
    value_set=[
        {
            "value": "Mouse",
            "origin_version": "1",
            "origin_id": "2578400",
            "origin_definition": "Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C14238"],
            "synonyms": [
                {
                    "value": "Mouse",
                    "origin_id": "C14238",
                    "origin_definition": "Any of numerous species of small rodents belonging to the genus Mus and various related genera of the family Muridae.",
                    "origin_name": "NCIt",
                },
                {
                    "origin_id": "447482001",
                    "origin_name": "SNOMEDCT_US",
                    "origin_version": "2024_03_01",
                    "value": "Mus",
                },
            ],
        },
        {
            "value": "Human",
            "origin_version": "1",
            "origin_id": "2620875",
            "origin_definition": "The bipedal primate mammal, Homo sapiens; belonging to man or mankind; pertaining to man or to the race of man; use of man as experimental subject or unit of analysis in research.",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C14225"],
            "synonyms": [
                {
                    "value": "Human",
                    "origin_id": "C14225",
                    "origin_definition": "The bipedal primate mammal, Homo sapiens; belonging to man or mankind; pertaining to man or to the race of man; use of man as experimental subject or unit of analysis in research.",
                    "origin_name": "NCIt",
                },
            ],
        },
        {
            "value": "Dog",
            "origin_version": "1",
            "origin_id": "5729587",
            "origin_definition": "The domestic dog, Canis familiaris.",
            "origin_name": "caDSR",
            "ncit_concept_codes": [],
            "synonyms": [],
        },
    ],
)

TEST_ANNOTATION_SPEC_MIN = AnnotationSpec(
    entity={},
    annotation={
        "key": ("subject_legal_adult_or_pediatric_participant_type", "caDSR"),
        "attrs": {
            "handle": "subject_legal_adult_or_pediatric_participant_type",
            "value": "Subject Legal Adult Or Pediatric Participant Type",
            "origin_id": "11524549",
            "origin_name": "caDSR",
        },
    },
    value_set=[
        {
            "value": "Pediatric",
            "origin_version": "1",
            "origin_id": "2597927",
            "origin_definition": "Having to do with children.",
            "origin_name": "caDSR",
            "ncit_concept_codes": [],
            "synonyms": [],
        },
        {
            "value": "Adult - legal age",
            "origin_version": "1",
            "origin_id": "11524542",
            "origin_definition": (
                "A person of legal age to consent to a procedure as specifed by local regulation."
            ),
            "origin_name": "caDSR",
            "ncit_concept_codes": [],
            "synonyms": [],
        },
    ],
)

TEST_ANNOTATION_SPEC_NO_VS = AnnotationSpec(
    entity={},
    annotation={
        "key": ("program_name_text", "caDSR - CRDC"),
        "attrs": {
            "handle": "program_name_text",
            "value": "Program Name Text",
            "origin_id": "11444542",
            "origin_version": "1",
            "origin_name": "caDSR - CRDC",
        },
    },
    value_set=[],
)

TEST_MODEL_CDE_SPEC = ModelCDESpec(
    handle="TEST",
    version="1.2.3",
    annotations=[
        TEST_ANNOTATION_SPEC,
        TEST_ANNOTATION_SPEC_MIN,
        TEST_ANNOTATION_SPEC_NO_VS,
    ],
)

TEST_MODEL_CDE_SPEC_NO_ANNOTATIONS = ModelCDESpec(
    handle="TEST",
    version="1.2.3",
    annotations=[],
)

TEST_MDB_CDE_SPEC_RAW = {
    "CDECode": "6142527",
    "CDEVersion": "1.00",
    "CDEFullName": "ploidy",
    "CDEOrigin": "caDSR",
    "models": [
        {"property": "molecular_test.ploidy", "model": "CCDI", "version": "2.0.0"},
        {"property": "molecular_test.ploidy", "model": "CCDI", "version": "2.1.0"},
        {"property": "molecular_test.ploidy", "model": "C3DC", "version": "1.2.3"},
    ],
    "permissibleValues": [
        {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "20.05a",
                    "origin_id": "C43234",
                    "value": "Not Reported",
                    "origin_name": "NCIt",
                },
                {
                    "origin_version": "1",
                    "origin_id": "C43234",
                    "value": "Not Reported",
                    "origin_name": "NCIt",
                },
            ],
            "origin_id": "2572578",
            "origin_definition": "Not provided or available.",
            "value": "Not Reported",
            "origin_name": "caDSR",
        },
        {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "2024_03_01",
                    "origin_id": "C123456",
                    "value": "Unknown (qualifier value)",
                    "origin_name": "NCIt",
                },
                {
                    "origin_version": None,
                    "origin_id": "C17998",
                    "value": "Unknown",
                    "origin_name": "NCIt",
                },
            ],
            "origin_id": "2565695",
            "origin_definition": "Not known, not observed, not recorded, or refused.",
            "value": "Unknown",
            "origin_name": "caDSR",
        },
        {
            "origin_version": "1",
            "synonyms": [],
            "origin_id": "2558889",
            "origin_definition": "A chromosomal abnormality in which the chromosomal number is less than the normal diploid number.",
            "value": "Hypodiploid",
            "origin_name": "caDSR",
        },
        {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "2_77",
                    "origin_id": "LA30219-2",
                    "value": "Hyperdiploid",
                    "origin_name": "LNC",
                },
            ],
            "origin_id": "2558886",
            "origin_definition": "A chromosomal abnormality in which the chromosomal number is greater than the normal diploid number.",
            "value": "Hyperdiploid",
            "origin_name": "caDSR",
        },
        {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "20.10d",
                    "origin_id": "C118941",
                    "value": "Diploidy",
                    "origin_name": "NCIt",
                },
            ],
            "origin_id": "2558626",
            "origin_definition": "Having two sets of homologous chromosomes.",
            "value": "Diploid",
            "origin_name": "caDSR",
        },
    ],
}

TEST_MDB_CDE_SPEC = MDBCDESpec(
    CDECode="6142527",
    CDEVersion="1.00",
    CDEFullName="ploidy",
    CDEOrigin="caDSR",
    models=[
        {"property": "molecular_test.ploidy", "model": "CCDI", "version": "2.0.0"},
        {"property": "molecular_test.ploidy", "model": "CCDI", "version": "2.1.0"},
        {"property": "molecular_test.ploidy", "model": "C3DC", "version": "1.2.3"},
    ],
    permissibleValues=[
        {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "20.05a",
                    "origin_id": "C43234",
                    "value": "Not Reported",
                    "origin_name": "NCIt",
                },
                {
                    "origin_version": "1",
                    "origin_id": "C43234",
                    "value": "Not Reported",
                    "origin_name": "NCIt",
                },
            ],
            "origin_id": "2572578",
            "origin_definition": "Not provided or available.",
            "value": "Not Reported",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C43234"],
        },
        {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "2024_03_01",
                    "origin_id": "C123456",
                    "value": "Unknown (qualifier value)",
                    "origin_name": "NCIt",
                },
                {
                    "origin_version": None,
                    "origin_id": "C17998",
                    "value": "Unknown",
                    "origin_name": "NCIt",
                },
            ],
            "origin_id": "2565695",
            "origin_definition": "Not known, not observed, not recorded, or refused.",
            "value": "Unknown",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C123456", "C17998"],
        },
        {
            "origin_version": "1",
            "synonyms": [],
            "origin_id": "2558889",
            "origin_definition": "A chromosomal abnormality in which the chromosomal number is less than the normal diploid number.",
            "value": "Hypodiploid",
            "origin_name": "caDSR",
            "ncit_concept_codes": [],
        },
        {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "2_77",
                    "origin_id": "LA30219-2",
                    "value": "Hyperdiploid",
                    "origin_name": "LNC",
                },
            ],
            "origin_id": "2558886",
            "origin_definition": "A chromosomal abnormality in which the chromosomal number is greater than the normal diploid number.",
            "value": "Hyperdiploid",
            "origin_name": "caDSR",
            "ncit_concept_codes": [],
        },
        {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "20.10d",
                    "origin_id": "C118941",
                    "value": "Diploidy",
                    "origin_name": "NCIt",
                },
            ],
            "origin_id": "2558626",
            "origin_definition": "Having two sets of homologous chromosomes.",
            "value": "Diploid",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C118941"],
        },
    ],
)

TEST_CADSR_RESPONSE_MDB_CDES = [
    {
        "value": "Not Reported",
        "origin_version": "1",
        "origin_id": "2572578",
        "origin_definition": "Not provided or available.",
        "origin_name": "caDSR",
        "ncit_concept_codes": ["C43234"],
        "synonyms": [
            {
                "origin_version": "20.05a",
                "origin_id": "C43234",
                "value": "Not Reported",
                "origin_name": "NCIt",
            },
            {
                "origin_version": "1",
                "origin_id": "C43234",
                "value": "Not Reported",
                "origin_name": "NCIt",
            },
        ],
    },
    {
        "value": "Unknown",
        "origin_version": "1",
        "origin_id": "2565695",
        "origin_definition": "Not known, not observed, not recorded, or refused.",
        "origin_name": "caDSR",
        "ncit_concept_codes": ["C17998", "C123456"],
        "synonyms": [
            {
                "origin_version": "2024_03_01",
                "origin_id": "C123456",
                "value": "Unknown (qualifier value)",
                "origin_name": "NCIt",
            },
            {
                "origin_version": None,
                "origin_id": "C17998",
                "value": "Unknown",
                "origin_name": "NCIt",
            },
        ],
    },
    {
        "value": "Hypodiploid",
        "origin_version": "1",
        "origin_id": "2558889",
        "origin_definition": "A chromosomal abnormality in which the chromosomal number is less than the normal diploid number.",
        "origin_name": "caDSR",
        "ncit_concept_codes": [],
        "synonyms": [],
    },
    {
        "value": "Hyperdiploid",
        "origin_version": "1",
        "origin_id": "2558886",
        "origin_definition": "A chromosomal abnormality in which the chromosomal number is greater than the normal diploid number.",
        "origin_name": "caDSR",
        "ncit_concept_codes": [],
        "synonyms": [
            {
                "origin_version": "2_77",
                "origin_id": "LA30219-2",
                "value": "Hyperdiploid",
                "origin_name": "LNC",
            },
        ],
    },
    {
        "value": "Diploid",
        "origin_version": "1",
        "origin_id": "2558626",
        "origin_definition": "Having two sets of homologous chromosomes.",
        "origin_name": "caDSR",
        "ncit_concept_codes": ["C118941"],
        "synonyms": [
            {
                "origin_version": "20.10d",
                "origin_id": "C118941",
                "value": "Diploidy",
                "origin_name": "NCIt",
            },
        ],
    },
]

TEST_NCIM_MAPPING = {
    # single synonym
    "C39299": [
        {
            "origin_id": "LA19834-3",
            "origin_name": "LNC",
            "origin_version": "1",
            "value": "Pediatric",
        },
    ],
    # multiple synonyms
    "C17998": [
        {
            "origin_id": "LA15677-0",
            "origin_name": "LNC",
            "origin_version": "1.2",
            "value": "? = Unknown",
        },
        {
            "origin_id": "RID39181",
            "origin_name": "RADLEX",
            "origin_version": "",
            "value": "Unknown",
        },
    ],
    # not in mdb (unmatched)
    "C0392366": [
        {
            "origin_id": "272393004",
            "origin_name": "SNOMEDCT_US",
            "origin_version": "20020131",
            "value": "Tests",
        },
    ],
}

TEST_NCIM_MAPPING_TSV = """NCI Meta CUI\tNCI Meta Concept Name\tNCI Code\tNCI PT\tSource Atom Code\tSource Atom Name\tSource\tVersion\tSource Term Type
C39299\tPediatric\tC39299\tPediatric\tLA19834-3\tPediatric\tLNC\t1\tPT
C17998\tUnknown\tC17998\tUnknown\tLA15677-0\t? = Unknown\tLNC\t1.2\tSY
C17998\tUnknown\tC17998\tUnknown\tRID39181\tUnknown\tRADLEX\t\tSY
C0392366\tTests\tC0392366\tTests\t272393004\tTests\tSNOMEDCT_US\t20020131\tPT
"""

TEST_MDB_CDES_NCIM = [
    MDBCDESpec(
        CDECode="cde1",
        CDEVersion="1.0",
        CDEFullName="Pediatric",
        CDEOrigin="caDSR",
        models=[
            {"property": "test.pediatric", "model": "CCDI", "version": "2.0.0"},
            {"property": "test.pediatric", "model": "CCDI", "version": "2.1.0"},
            {"property": "test.pediatric", "model": "C3DC", "version": "1.2.3"},
        ],
        permissibleValues=[
            {
                "origin_version": "1",
                "origin_id": "oid1",
                "origin_definition": "",
                "value": "Pediatric",
                "origin_name": "caDSR",
                "ncit_concept_codes": ["C39299"],
                "synonyms": [
                    {
                        "origin_id": "C39299",
                        "origin_name": "NCIt",
                        "origin_version": "1",
                        "value": "peds",
                    },
                    {
                        "origin_id": "LA19834-3",
                        "origin_name": "LNC",
                        "origin_version": "1",
                        "value": "Pediatric",
                    },
                ],
            },
        ],
    ),
    MDBCDESpec(
        CDECode="cde2",
        CDEVersion="1.0",
        CDEFullName="Unknown",
        CDEOrigin="caDSR",
        models=[
            {"property": "test.unknown", "model": "CCDI", "version": "2.0.0"},
            {"property": "test.unknown", "model": "CCDI", "version": "2.1.0"},
            {"property": "test.unknown", "model": "C3DC", "version": "1.2.3"},
        ],
        permissibleValues=[
            {
                "origin_version": "",
                "origin_id": "oid2",
                "origin_definition": "",
                "value": "Unknown",
                "origin_name": "caDSR",
                "ncit_concept_codes": ["C17998"],
                "synonyms": [
                    {
                        "origin_id": "C17998",
                        "origin_name": "NCIt",
                        "origin_version": "1",
                        "value": "unknown",
                    },
                    {
                        "origin_id": "LA15677-0",
                        "origin_name": "LNC",
                        "origin_version": "1.2",
                        "value": "? = Unknown",
                    },
                    {
                        "origin_id": "RID39181",
                        "origin_name": "RADLEX",
                        "origin_version": "",
                        "value": "Unknown",
                    },
                ],
            },
        ],
    ),
]

TEST_ANNOTATION_SPEC_NCIM = AnnotationSpec(
    entity={},
    annotation={
        "key": ("Unknown", "caDSR"),
        "attrs": {
            "origin_id": "cde2",
            "origin_version": "1.0",
            "origin_name": "caDSR",
            "value": "Unknown",
        },
    },
    value_set=[
        {
            "origin_version": "",
            "origin_id": "oid2",
            "origin_definition": "",
            "value": "Unknown",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C17998"],
            "synonyms": [
                {
                    "origin_id": "C17998",
                    "origin_name": "NCIt",
                    "origin_version": "1",
                    "value": "unknown",
                },
                {
                    "origin_id": "LA15677-0",
                    "origin_name": "LNC",
                    "origin_version": "1.2",
                    "value": "? = Unknown",
                },
                {
                    "origin_id": "RID39181",
                    "origin_name": "RADLEX",
                    "origin_version": "",
                    "value": "Unknown",
                },
                {
                    "origin_id": "oid123",
                    "origin_name": "TERMS-R-US",
                    "origin_version": "20000101",
                    "value": "UNKNWN",
                },
            ],
        },
    ],
)

TEST_MODEL_SPEC_YML = """
    TCDS:
        repository: CBIIT/test-cds-model
        mdf_directory: model-desc
        mdf_files:
        - test-cds-model.yml
        - test-cds-model-props.yml
        in_data_hub: true
        versions:
            - version: 1.0.0
              tag: 1.0.0-release
        latest_version: 1.0.0
    TCCDI:
        repository: CBIIT/test-ccdi-model
        mdf_directory: model-desc
        mdf_files:
        - test-ccdi-model.yml
        - test-ccdi-model-props.yml
        - terms.yml
        in_data_hub: false
        versions:
            - version: 0.1.0
            - version: 2.0.0
              tag: 2.0.0
        latest_version: 2.0.0
"""

TEST_MODEL_SPEC = {
    "TCDS": ModelSpec(
        {
            "repository": "CBIIT/test-cds-model",
            "mdf_directory": "model-desc",
            "mdf_files": ["test-cds-model.yml", "test-cds-model-props.yml"],
            "in_data_hub": True,
            "versions": [{"version": "1.0.0", "tag": "1.0.0-release"}],
            "latest_version": "1.0.0",
        },
    ),
    "TCCDI": ModelSpec(
        {
            "repository": "CBIIT/test-ccdi-model",
            "mdf_directory": "model-desc",
            "mdf_files": [
                "test-ccdi-model.yml",
                "test-ccdi-model-props.yml",
                "terms.yml",
            ],
            "in_data_hub": False,
            "versions": [
                {"version": "0.1.0"},
                {"version": "2.0.0", "tag": "2.0.0"},
            ],
            "latest_version": "2.0.0",
        },
    ),
}

TEST_MODEL_SPEC_INVALID_YML = """
    TCDS:
        repository: "CBIIT/test-cds-model
        mdf_directory: model-desc
        mdf_files:
        - test-cds-model.yml
        - test-cds-model-props.yml
        in_data_hub: true
        versions:
            - version: 1.0.0
              tag: 1.0.0-release
        latest_version: 1.0.0
"""

TEST_MAKE_MODEL_CDE_SPEC_BASE = ModelCDESpec(
    {
        "handle": "TEST",
        "version": "1.2.3",
        "annotations": [
            {
                "entity": {
                    "key": ("study", "organism_species"),
                    "attrs": {
                        "handle": "organism_species",
                        "model": "TEST",
                        "value_domain": "value_set",
                        "is_required": "Preferred",
                        "is_key": "False",
                        "is_nullable": "False",
                        "is_strict": "True",
                        "desc": "Species binomial of study participants",
                    },
                    "entity_has_enum": True,
                },
                "annotation": {
                    "key": ("sample_organism_type", "caDSR"),
                    "attrs": {
                        "handle": "sample_organism_type",
                        "value": "Sample Organism Type",
                        "origin_id": "6118266",
                        "origin_version": "1.00",
                        "origin_name": "caDSR",
                    },
                },
                "value_set": [],
            },
        ],
    },
)
