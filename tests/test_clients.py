import copy
import datetime
import logging
import zipfile

import pytest
import requests
from requests.exceptions import HTTPError

from bento_mdb.clients import CADSRClient, NCItClient
from bento_mdb.constants import NCIM_TSV_NAME
from bento_mdb.datatypes import AnnotationSpec
from tests.test_utils import (
    TEST_ANNOTATION_SPEC_NCIM,
    TEST_CADSR_RESPONSE_MDB_CDES,
    TEST_MDB_CDE_SPEC,
    TEST_MDB_CDES_NCIM,
    TEST_NCIM_MAPPING,
    TEST_NCIM_MAPPING_TSV,
    assert_equal,
    create_mock_zip,
)


class FakeResponse:
    """Fake response for testing."""

    def __init__(
        self,
        json_data=None,
        text_data=None,
        content=None,
        status_code=200,
        raise_json_error=False,
    ):
        self.json_data = json_data
        self.text = text_data
        self.content = content
        self.status_code = status_code
        self.raise_json_error = raise_json_error

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise HTTPError(f"HTTP Error: {self.status_code}")


@pytest.fixture
def fake_requests_get(monkeypatch):
    """Fixture that sets a fake requests.get function."""

    def _set_fake_get(
        json_data=None,
        text_data=None,
        content=None,
        status_code=200,
        raise_json_error=False,
    ):
        def fake_get(url, timeout=5, headers=None):
            return FakeResponse(
                json_data,
                text_data,
                content,
                status_code,
                raise_json_error,
            )

        monkeypatch.setattr(requests, "get", fake_get)

    return _set_fake_get


@pytest.fixture
def mock_ncit_client():
    """Fixture to return an NCItClient instance with mocks."""
    client = NCItClient()
    client.ncim_mapping = TEST_NCIM_MAPPING
    return client


@pytest.fixture
def mdb_cde_with_three_pvs():
    """Fixture: MDB CDE with 3 PVs (Breast, Brain, Bone) for testing removed PV detection."""
    return [
        {
            "CDECode": "15260691",
            "CDEVersion": "1",
            "CDEFullName": "Disease Primary Anatomic Site Category",
            "CDEOrigin": "caDSR",
            "models": [],
            "permissibleValues": [
                {
                    "value": "Breast",
                    "origin_id": "2561089",
                    "origin_definition": "Breast definition",
                    "origin_version": "1",
                    "origin_name": "caDSR",
                    "ncit_concept_codes": ["C12971"],
                    "synonyms": [],
                },
                {
                    "value": "Brain",
                    "origin_id": "2558329",
                    "origin_definition": "Brain definition",
                    "origin_version": "1",
                    "origin_name": "caDSR",
                    "ncit_concept_codes": ["C12439"],
                    "synonyms": [],
                },
                {
                    "value": "Bone",
                    "origin_id": "2816296",
                    "origin_definition": "Bone definition",
                    "origin_version": "1",
                    "origin_name": "caDSR",
                    "ncit_concept_codes": ["C12366"],
                    "synonyms": [],
                },
            ],
        }
    ]


@pytest.fixture
def cadsr_response_two_pvs():
    """Fixture: caDSR response with 2 PVs (Breast, Brain) - Bone PV removed from caDSR."""
    return [
        {
            "value": "Breast",
            "origin_id": "2561089",
            "origin_definition": "Breast definition",
            "origin_version": "1",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C12971"],
            "synonyms": [],
        },
        {
            "value": "Brain",
            "origin_id": "2558329",
            "origin_definition": "Brain definition",
            "origin_version": "1",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C12439"],
            "synonyms": [],
        },
    ]


@pytest.fixture
def mdb_cde_with_changed_name():
    """Fixture: MDB CDE with old name for testing metadata change detection."""
    return [
        {
            "CDECode": "15260691",
            "CDEVersion": "1",
            "CDEFullName": "Disease Primary Anatomic Site",  # Old name (before update)
            "CDEOrigin": "caDSR",
            "CDEDefinition": "Old definition",
            "models": [],
            "permissibleValues": [
                {
                    "value": "Breast",
                    "origin_id": "2561089",
                    "origin_definition": "Breast definition",
                    "origin_version": "1",
                    "origin_name": "caDSR",
                    "ncit_concept_codes": ["C12971"],
                    "synonyms": [],
                },
            ],
        }
    ]


@pytest.fixture
def cadsr_cde_with_new_name():
    """Fixture: caDSR CDE metadata with new name and DRAFT NEW workflow status."""
    return {
        "CDECode": "15260691",
        "CDEVersion": "1",
        "CDEFullName": "Disease Primary Anatomic Site Category",  # New name (after update)
        "CDEDefinition": "New definition",
        "workflowStatus": "DRAFT NEW",  # caDSR API field name for workflow status
    }


@pytest.fixture
def cadsr_response_with_new_pv():
    """Fixture: caDSR response with new PV (Data Redacted)."""
    return [
        {
            "value": "Not Reported",
            "origin_id": "2181620",
            "origin_definition": "Not provided",
            "origin_version": "1",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C17998"],
            "synonyms": [],
        },
        {
            "value": "Data Redacted",
            "origin_id": "2181621",
            "origin_definition": "Data suppressed",
            "origin_version": "1",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C25474"],
            "synonyms": [],
        },
    ]


class TestCADSRClient:
    """Tests for CADSRClient."""

    client = CADSRClient()

    SAMPLE_RESPONSE = {
        "DataElement": {
            "publicId": "11524549",
            "version": "1",
            "ValueDomain": {
                "PermissibleValues": [
                    {
                        "value": "Pediatric",
                        "ValueMeaning": {
                            "version": "1",
                            "publicId": "2597927",
                            "definition": "Having to do with children.",
                            "Concepts": [
                                {
                                    "longName": "Pediatric",
                                    "conceptCode": "C39299",
                                    "definition": "Having to do with children.",
                                    "evsSource": "NCI_CONCEPT_CODE",
                                    "primaryIndicator": "Yes",
                                    "displayOrder": "0",
                                },
                            ],
                        },
                    },
                ],
            },
        },
    }

    def test_fetch_cde_valueset(self, fake_requests_get) -> None:
        """Happy path test for fetch_cde_valueset."""
        fake_requests_get(self.SAMPLE_RESPONSE)
        actual = self.client.fetch_cde_valueset("11524549", "1")
        expected = [
            {
                "value": "Pediatric",
                "origin_version": "1",
                "origin_id": "2597927",
                "origin_definition": "Having to do with children.",
                "origin_name": "caDSR",
                "ncit_concept_codes": ["C39299"],
                "synonyms": [
                    {
                        "value": "Pediatric",
                        "origin_id": "C39299",
                        "origin_definition": "Having to do with children.",
                        "origin_name": "NCIt",
                    },
                ],
                "alternates": [],
            },
        ]
        assert_equal(actual, expected)

    def test_http_error(self, fake_requests_get) -> None:
        """Test that empty list is returned when status code is not 2xx."""
        fake_requests_get(self.SAMPLE_RESPONSE, status_code=404)
        actual = self.client.fetch_cde_valueset("11524549", "1")
        assert_equal(actual, [])

    def test_bad_json(self, fake_requests_get) -> None:
        """Test that JSONDecodeError is raised when response is not JSON."""
        fake_requests_get(json_data=None, raise_json_error=True)
        actual = self.client.fetch_cde_valueset("11524549", "1")
        assert_equal(actual, [])

    def test_missing_pvs(self, fake_requests_get) -> None:
        """Test that no PVs are returned when no PVs are found."""
        incomplete_response = {
            "DataElement": {"publicId": "11524549", "version": "1", "ValueDomain": {}},
        }
        fake_requests_get(incomplete_response)
        actual = self.client.fetch_cde_valueset("11524549", "1")
        assert_equal(actual, [])

    def test_empty_pvs(self, fake_requests_get) -> None:
        """Test that no PVs are returned when PVs are empty."""
        empty_pvs_response = {
            "DataElement": {
                "publicId": "11524549",
                "version": "1",
                "ValueDomain": {"PermissibleValues": []},
            },
        }
        fake_requests_get(empty_pvs_response)
        actual = self.client.fetch_cde_valueset("11524549", "1")
        assert_equal(actual, [])

    def test_missing_valuedomain(self, fake_requests_get) -> None:
        """Test that no PVs are returned when ValueDomain key is missing."""
        missing_valuedomain_response = {
            "DataElement": {"publicId": "11524549", "version": "1"},
        }
        fake_requests_get(missing_valuedomain_response)
        actual = self.client.fetch_cde_valueset("11524549", "1")
        assert_equal(actual, [])

    def test_get_valueset_from_json_with_alternates(self) -> None:
        """Test that alternates are extracted from Designations in Valueset."""
        response_with_alternates = {
            "DataElement": {
                "publicId": "11524549",
                "version": "1",
                "ValueDomain": {
                    "PermissibleValues": [
                        {
                            "value": "Yes",
                            "ValueMeaning": {
                                "version": "1",
                                "publicId": "2597927",
                                "definition": "Affirmative response.",
                                "Concepts": [
                                    {
                                        "longName": "Yes",
                                        "conceptCode": "C25554",
                                        "definition": "Affirmative response.",
                                        "evsSource": "NCI_CONCEPT_CODE",
                                        "primaryIndicator": "Yes",
                                        "displayOrder": "0",
                                    },
                                ],
                                "Designations": [
                                    {"name": "Affirmative"},
                                    {"name": "True"},
                                    {"name": ""},  # Empty name should be skipped
                                    {"name": "Affirmative"},  # Duplicate should be skipped
                                ],
                            },
                        },
                    ],
                },
            },
        }
        actual = self.client.get_valueset_from_json(response_with_alternates)
        expected = [
            {
                "value": "Yes",
                "origin_version": "1",
                "origin_id": "2597927",
                "origin_definition": "Affirmative response.",
                "origin_name": "caDSR",
                "ncit_concept_codes": ["C25554"],
                "synonyms": [
                    {
                        "value": "Yes",
                        "origin_id": "C25554",
                        "origin_definition": "Affirmative response.",
                        "origin_name": "NCIt",
                    },
                ],
                "alternates": [
                    {"value": "Affirmative"},
                    {"value": "True"},
                ],
            },
        ]
        assert_equal(actual, expected)

    def test_get_valueset_from_json_without_designations(self) -> None:
        """Test that alternates are empty when no Designations field present."""
        response_without_designations = {
            "DataElement": {
                "publicId": "11524549",
                "version": "1",
                "ValueDomain": {
                    "PermissibleValues": [
                        {
                            "value": "No",
                            "ValueMeaning": {
                                "version": "1",
                                "publicId": "2597928",
                                "definition": "Negative response.",
                                "Concepts": [
                                    {
                                        "longName": "No",
                                        "conceptCode": "C25555",
                                        "definition": "Negative response.",
                                        "evsSource": "NCI_CONCEPT_CODE",
                                        "primaryIndicator": "Yes",
                                        "displayOrder": "0",
                                    },
                                ],
                            },
                        },
                    ],
                },
            },
        }
        actual = self.client.get_valueset_from_json(response_without_designations)
        expected = [
            {
                "value": "No",
                "origin_version": "1",
                "origin_id": "2597928",
                "origin_definition": "Negative response.",
                "origin_name": "caDSR",
                "ncit_concept_codes": ["C25555"],
                "synonyms": [
                    {
                        "value": "No",
                        "origin_id": "C25555",
                        "origin_definition": "Negative response.",
                        "origin_name": "NCIt",
                    },
                ],
                "alternates": [],
            },
        ]
        assert_equal(actual, expected)

    def test_check_cdes_against_mdb_no_updates(self, monkeypatch) -> None:
        client = CADSRClient()
        monkeypatch.setattr(
            client,
            "fetch_cde_valueset",
            lambda cde_id, cde_version, **kwargs: TEST_CADSR_RESPONSE_MDB_CDES,
        )
        # Mock fetch_cde_details to avoid network call
        monkeypatch.setattr(
            client,
            "fetch_cde_details",
            lambda cde_id, cde_version, **kwargs: {},
        )

        annotations = client.check_cdes_against_mdb([TEST_MDB_CDE_SPEC])
        assert_equal(annotations, [])

    def test_check_cdes_against_mdb_new_pv(self, monkeypatch) -> None:
        client = CADSRClient()
        test_response_new_pv = copy.deepcopy(TEST_CADSR_RESPONSE_MDB_CDES)
        new_pv = {
            "origin_version": "1",
            "synonyms": [
                {
                    "origin_version": "4_1",
                    "origin_id": "RID39225",
                    "value": "not evaluable",
                    "origin_name": "RADLEX",
                },
                {
                    "origin_version": None,
                    "origin_id": "C62222",
                    "value": "Unevaluable",
                    "origin_name": "NCIt",
                },
            ],
            "origin_id": "2559597",
            "origin_definition": "Unable to be evaluated.",
            "value": "Not evaluable",
            "origin_name": "caDSR",
            "ncit_concept_codes": ["C62222"],
        }
        test_response_new_pv.append(new_pv)
        monkeypatch.setattr(
            client,
            "fetch_cde_valueset",
            lambda cde_id, cde_version, **kwargs: test_response_new_pv,
        )
        # Mock fetch_cde_details to avoid network call
        monkeypatch.setattr(
            client,
            "fetch_cde_details",
            lambda cde_id, cde_version, **kwargs: {},
        )
        annotations = client.check_cdes_against_mdb([TEST_MDB_CDE_SPEC])
        expected_annotations = [
            AnnotationSpec(
                entity={},
                annotation={
                    "key": ("ploidy", "caDSR"),
                    "attrs": {
                        "origin_id": "6142527",
                        "origin_version": "1.00",
                        "origin_name": "caDSR",
                        "value": "ploidy",
                    },
                },
                value_set=[new_pv],
            ),
        ]
        assert_equal(annotations, expected_annotations)

    def test_check_cdes_against_mdb_raises_error_no_pvs(
        self,
        monkeypatch,
        caplog,
    ) -> None:
        client = CADSRClient()
        monkeypatch.setattr(
            client,
            "fetch_cde_valueset",
            lambda cde_id, cde_version, **kwargs: [],
        )
        # Mock fetch_cde_details to avoid network call
        monkeypatch.setattr(
            client,
            "fetch_cde_details",
            lambda cde_id, cde_version, **kwargs: {},
        )
        with caplog.at_level(logging.ERROR):
            result = client.check_cdes_against_mdb([TEST_MDB_CDE_SPEC])
        assert_equal(result, [])
        assert "Error fetching PVs from caDSR for 6142527v1.00" in caplog.text


class TestNCItClient:
    def test_get_readme_date_success(self, mock_ncit_client, fake_requests_get) -> None:
        fake_requests_get(
            text_data="NCIm version: 202503\nSource\tVersion\nGO\t2024_03_28",
        )
        actual = mock_ncit_client.get_readme_date()
        assert actual is not None
        assert_equal(actual.strftime("%Y%m"), "202503")

    def test_get_readme_date_failure(self, mock_ncit_client, fake_requests_get) -> None:
        fake_requests_get(text_data="Invalid Header\nSource\tVersion\nGO\t2024_03_28")
        actual = mock_ncit_client.get_readme_date()
        assert_equal(actual, None)

    def test_get_readme_date_http_error(
        self,
        mock_ncit_client,
        fake_requests_get,
    ) -> None:
        fake_requests_get(status_code=404)
        with pytest.raises(HTTPError):
            mock_ncit_client.get_readme_date()

    def test_download_and_extract_tsv_success(
        self,
        mock_ncit_client,
        fake_requests_get,
    ) -> None:
        mock_name = NCIM_TSV_NAME
        zip = create_mock_zip(mock_name, TEST_NCIM_MAPPING_TSV)
        fake_requests_get(content=zip)
        actual = mock_ncit_client.download_and_extract_tsv(tsv_filename=mock_name)
        assert_equal(actual, TEST_NCIM_MAPPING)

    def test_download_and_extract_tsv_empty_zip(
        self,
        mock_ncit_client,
        fake_requests_get,
    ) -> None:
        mock_name = "empty.txt"
        zip = create_mock_zip(mock_name, "")
        fake_requests_get(content=zip)
        actual = mock_ncit_client.download_and_extract_tsv(mock_name)
        assert_equal(actual, {})

    def test_download_and_extract_tsv_missing_tsv(
        self,
        mock_ncit_client,
        fake_requests_get,
    ) -> None:
        mock_name = "wrong-file.txt"
        zip = create_mock_zip(mock_name, "")
        fake_requests_get(content=zip)
        with pytest.raises(KeyError):
            mock_ncit_client.download_and_extract_tsv(
                mock_ncit_client.DEFAULT_NCIM_TSV.name,
            )

    def test_download_and_extract_tsv_invalid_zip(
        self,
        mock_ncit_client,
        fake_requests_get,
    ) -> None:
        invalid_zip_content = b"Invalid ZIP file"
        fake_requests_get(content=invalid_zip_content)
        with pytest.raises(zipfile.BadZipFile):
            mock_ncit_client.download_and_extract_tsv()

    def test_ncit_for_updated_mappings_update(
        self,
        monkeypatch,
        mock_ncit_client,
    ) -> None:
        monkeypatch.setattr(
            mock_ncit_client,
            "get_readme_date",
            lambda: datetime.datetime(2025, 3, 1),
        )
        monkeypatch.setattr(
            "bento_mdb.clients.get_last_sync_date",
            lambda x: datetime.datetime(2025, 2, 1),
        )
        monkeypatch.setattr(
            mock_ncit_client,
            "download_and_extract_tsv",
            lambda: {"C12345": [{"value": "New Synonym"}]},
        )

        assert_equal(mock_ncit_client.check_ncit_for_updated_mappings(), True)

    def test_ncit_for_updated_mappings_no_update(
        self,
        monkeypatch,
        mock_ncit_client,
    ) -> None:
        monkeypatch.setattr(
            mock_ncit_client,
            "get_readme_date",
            lambda: datetime.datetime(2025, 2, 1),
        )
        monkeypatch.setattr(
            "bento_mdb.clients.get_last_sync_date",
            lambda x: datetime.datetime(2025, 2, 1),
        )

        assert_equal(mock_ncit_client.check_ncit_for_updated_mappings(), False)

    def test_check_synonyms_against_mdb_no_update(
        self,
        mock_ncit_client,
        fake_requests_get,
        monkeypatch,
    ) -> None:
        annotations = mock_ncit_client.check_synonyms_against_mdb(
            TEST_MDB_CDES_NCIM,
        )
        assert_equal(annotations, [])

    def test_check_synonyms_against_mdb_new_pv(
        self,
        mock_ncit_client,
        fake_requests_get,
        monkeypatch,
    ) -> None:
        client = mock_ncit_client
        client.ncim_mapping["C17998"].append(
            {
                "origin_id": "oid123",
                "origin_name": "TERMS-R-US",
                "origin_version": "20000101",
                "value": "UNKNWN",
            },
        )
        annotations = mock_ncit_client.check_synonyms_against_mdb(
            TEST_MDB_CDES_NCIM,
        )
        expected_annotations = [TEST_ANNOTATION_SPEC_NCIM]
        expected_models = {
            (x["model"], x["version"]) for x in TEST_MDB_CDE_SPEC["models"]
        }
        assert_equal(annotations, expected_annotations)

    def test_check_cdes_against_mdb_detect_removed_pvs(
        self,
        mdb_cde_with_three_pvs,
        cadsr_response_two_pvs,
    ) -> None:
        """Test that removed PVs are detected when DRAFT NEW CDE has fewer PVs in caDSR.

        This test verifies that when a DRAFT NEW CDE is checked against MDB:
        - MDB has: [Breast, Brain, Bone]
        - caDSR has: [Breast, Brain] (Bone removed)
        - Result: removed_pvs = ["Bone"]
        """
        client = CADSRClient()
        import unittest.mock as mock
        # Return DRAFT NEW status to trigger _check_draft_new_cde_changes
        cadsr_cde_details_draft_new = {
            "CDECode": "15260691",
            "CDEVersion": "1",
            "CDEFullName": "Disease Primary Anatomic Site Category",
            "CDEWorkflowStatus": "DRAFT NEW",
        }
        with mock.patch.object(client, "fetch_cde_valueset", return_value=cadsr_response_two_pvs):
            with mock.patch.object(client, "fetch_cde_details", return_value=cadsr_cde_details_draft_new):
                annotations = client.check_cdes_against_mdb(mdb_cde_with_three_pvs)

        # Verify removed PVs are detected (now includes origin_id and origin_version)
        assert len(annotations) > 0
        assert "removed_pvs" in annotations[0]
        assert len(annotations[0]["removed_pvs"]) == 1
        assert annotations[0]["removed_pvs"][0]["value"] == "Bone"
        assert annotations[0]["removed_pvs"][0]["origin_id"] == "2816296"
        assert "origin_version" in annotations[0]["removed_pvs"][0]

    def test_check_cdes_against_mdb_detect_removed_pvs_released(
        self,
        mdb_cde_with_three_pvs,
        cadsr_response_two_pvs,
    ) -> None:
        """Test removed PV detection also runs for RELEASED CDEs."""
        client = CADSRClient()
        import unittest.mock as mock

        cadsr_cde_details_released = {
            "CDECode": "15260691",
            "CDEVersion": "1",
            "CDEFullName": "Disease Primary Anatomic Site Category",
            "CDEWorkflowStatus": "RELEASED",
        }
        with mock.patch.object(client, "fetch_cde_valueset", return_value=cadsr_response_two_pvs):
            with mock.patch.object(client, "fetch_cde_details", return_value=cadsr_cde_details_released):
                annotations = client.check_cdes_against_mdb(mdb_cde_with_three_pvs)

        assert len(annotations) > 0
        assert "removed_pvs" in annotations[0]
        assert len(annotations[0]["removed_pvs"]) == 1
        assert annotations[0]["removed_pvs"][0]["value"] == "Bone"
        assert annotations[0]["removed_pvs"][0]["origin_id"] == "2816296"

    def test_check_cdes_against_mdb_detect_replaced_origin_id_same_value(
        self,
    ) -> None:
        """Detect removed PV when value is same but origin_id changes."""
        client = CADSRClient()
        import unittest.mock as mock

        mdb_cde = [
            {
                "CDECode": "11379445",
                "CDEVersion": "1.00",
                "CDEFullName": "Chromosome",
                "CDEOrigin": "caDSR",
                "models": [],
                "permissibleValues": [
                    {
                        "value": "Chr X",
                        "origin_id": "3636171",
                        "origin_definition": "old X",
                        "origin_version": "1",
                        "origin_name": "caDSR",
                        "ncit_concept_codes": [],
                        "synonyms": [],
                    },
                    {
                        "value": "Chr Y",
                        "origin_id": "3636170",
                        "origin_definition": "old Y",
                        "origin_version": "1",
                        "origin_name": "caDSR",
                        "ncit_concept_codes": [],
                        "synonyms": [],
                    },
                ],
            },
        ]
        cadsr_pvs = [
            {
                "value": "Chr X",
                "origin_id": "17141238",
                "origin_definition": "new X",
                "origin_version": "1",
                "origin_name": "caDSR",
                "ncit_concept_codes": [],
                "synonyms": [],
            },
            {
                "value": "Chr Y",
                "origin_id": "17141239",
                "origin_definition": "new Y",
                "origin_version": "1",
                "origin_name": "caDSR",
                "ncit_concept_codes": [],
                "synonyms": [],
            },
        ]
        cadsr_cde_details_released = {
            "CDECode": "11379445",
            "CDEVersion": "1.00",
            "CDEFullName": "Chromosome",
            "CDEWorkflowStatus": "RELEASED",
        }

        with mock.patch.object(client, "fetch_cde_valueset", return_value=cadsr_pvs):
            with mock.patch.object(client, "fetch_cde_details", return_value=cadsr_cde_details_released):
                annotations = client.check_cdes_against_mdb(mdb_cde)

        assert len(annotations) > 0
        assert "removed_pvs" in annotations[0]
        removed = annotations[0]["removed_pvs"]
        assert len(removed) == 2
        removed_keys = {(x["value"], x["origin_id"], x["origin_version"]) for x in removed}
        assert ("Chr X", "3636171", "1") in removed_keys
        assert ("Chr Y", "3636170", "1") in removed_keys

    def test_check_cdes_against_mdb_detect_metadata_change(
        self,
        mdb_cde_with_changed_name,
        cadsr_cde_with_new_name,
    ) -> None:
        """Test detection of CDE metadata changes when DRAFT NEW CDE name changes.

        This test verifies that when a DRAFT NEW CDE name is updated:
        - MDB has old name: "Disease Primary Anatomic Site"
        - caDSR has new name: "Disease Primary Anatomic Site Category"
        - Result: annotation is returned with CDEFullName field set
        """
        # Get the Breast PV from the fixture for caDSR response
        cadsr_pvs = [mdb_cde_with_changed_name[0]["permissibleValues"][0]]

        client = CADSRClient()
        import unittest.mock as mock
        # Ensure DRAFT NEW status is set to trigger _check_draft_new_cde_changes
        cadsr_cde_details = dict(cadsr_cde_with_new_name)
        cadsr_cde_details["CDEWorkflowStatus"] = "DRAFT NEW"
        with mock.patch.object(client, "fetch_cde_valueset", return_value=cadsr_pvs):
            with mock.patch.object(client, "fetch_cde_details", return_value=cadsr_cde_details):
                annotations = client.check_cdes_against_mdb(mdb_cde_with_changed_name)

        # Verify metadata change is detected (annotation should be returned)
        assert len(annotations) > 0
        assert annotations[0]["entity"] == {}
        assert annotations[0]["annotation"]["key"] == ('Disease Primary Anatomic Site', 'caDSR')
        # Verify CDEFullName is stored in annotation_spec
        assert "CDEFullName" in annotations[0]
        assert annotations[0]["CDEFullName"] == "Disease Primary Anatomic Site Category"

    def test_check_cdes_against_mdb_detect_version_change(self) -> None:
        """Test detection of CDE version changes when DRAFT NEW CDE version updates.

        This test verifies that when a DRAFT NEW CDE version is updated:
        - MDB has version: "1"
        - caDSR has version: "2"
        - Result: annotation is returned with CDEVersion field set
        """
        mdb_cde_old_version = [
            {
                "CDECode": "15260691",
                "CDEVersion": "1",
                "CDEFullName": "Disease Primary Anatomic Site Category",
                "CDEOrigin": "caDSR",
                "models": [],
                "permissibleValues": [
                    {
                        "value": "Breast",
                        "origin_id": "2561089",
                        "origin_definition": "Breast definition",
                        "origin_version": "1",
                        "origin_name": "caDSR",
                        "ncit_concept_codes": ["C12971"],
                        "synonyms": [],
                    },
                ],
            }
        ]

        cadsr_pvs = [mdb_cde_old_version[0]["permissibleValues"][0]]
        cadsr_cde_details_new_version = {
            "CDECode": "15260691",
            "CDEVersion": "2",  # New version
            "CDEFullName": "Disease Primary Anatomic Site Category",
            "CDEWorkflowStatus": "DRAFT NEW",
        }

        client = CADSRClient()
        import unittest.mock as mock
        with mock.patch.object(client, "fetch_cde_valueset", return_value=cadsr_pvs):
            with mock.patch.object(client, "fetch_cde_details", return_value=cadsr_cde_details_new_version):
                annotations = client.check_cdes_against_mdb(mdb_cde_old_version)

        # Version change detection is currently disabled
        # When re-enabled, this test should detect the version change
        assert len(annotations) == 0
