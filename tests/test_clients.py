import copy
import datetime
import logging
import zipfile

import pytest
import requests
from requests.exceptions import HTTPError

from bento_mdb_updates.clients import CADSRClient, NCItClient
from bento_mdb_updates.constants import NCIM_TSV_NAME
from bento_mdb_updates.datatypes import AnnotationSpec
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

    def test_check_cdes_against_mdb_no_updates(self, monkeypatch) -> None:
        client = CADSRClient()
        monkeypatch.setattr(
            client,
            "fetch_cde_valueset",
            lambda cde_id, cde_version: TEST_CADSR_RESPONSE_MDB_CDES,
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
            lambda cde_id, cde_version: test_response_new_pv,
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
            lambda cde_id, cde_version: [],
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
            "bento_mdb_updates.clients.get_last_sync_date",
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
            "bento_mdb_updates.clients.get_last_sync_date",
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
