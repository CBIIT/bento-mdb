from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from bento_mdf.mdf import MDFReader

from bento_mdb.datatypes import ModelSpec
from bento_mdb.model_cdes import (
    compare_model_specs_to_mdb,
    get_yaml_files_from_spec,
    load_model_specs_from_yaml,
    make_model_cde_spec,
    process_mdb_cdes,
)
from tests.test_utils import (
    TEST_MAKE_MODEL_CDE_SPEC_BASE,
    TEST_MDB_CDE_SPEC,
    TEST_MDB_CDE_SPEC_RAW,
    TEST_MODEL_SPEC,
    TEST_MODEL_SPEC_INVALID_YML,
    TEST_MODEL_SPEC_YML,
    assert_equal,
)


class TestLoadModelSpecsFromYaml:
    """Tests for load_model_specs_from_yaml."""

    def test_load_model_specs_from_yaml_valid(self, tmp_path) -> None:
        """Test loading valid model specs yaml."""
        valid_yaml = Path(tmp_path / "valid.yml")
        valid_yaml.write_text(TEST_MODEL_SPEC_YML, encoding="utf-8")
        actual = load_model_specs_from_yaml(valid_yaml)
        assert_equal(actual, TEST_MODEL_SPEC)

    def test_load_model_specs_from_yaml_invalid(self, tmp_path) -> None:
        """Test loading invalid model specs yaml."""
        invalid_yaml = Path(tmp_path / "invalid.yml")
        invalid_yaml.write_text(TEST_MODEL_SPEC_INVALID_YML, encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            load_model_specs_from_yaml(invalid_yaml)

    def test_load_model_specs_from_yaml_missing(self, tmp_path) -> None:
        """Test loading missing model specs yaml."""
        valid_yaml = Path(tmp_path / "missing.yml")
        with pytest.raises(FileNotFoundError):
            load_model_specs_from_yaml(valid_yaml)


class TestGetYamlFilesFromSpec:
    """Tests for get_yaml_files_from_spec."""

    def test_get_yaml_files_from_spec(self) -> None:
        """Test getting YAML files from model spec."""
        test_model, test_version = "TCDS", "1.0.0"
        test_spec = TEST_MODEL_SPEC[test_model]
        actual = get_yaml_files_from_spec(test_spec, test_model, test_version)
        base_url = (
            "https://raw.githubusercontent.com/"
            "CBIIT/test-cds-model/1.0.0-release/model-desc/"
        )
        expected = [base_url + str(f) for f in test_spec["mdf_files"]]
        assert_equal(actual, expected)

    def test_get_yaml_files_from_spec_latest(self) -> None:
        """Test getting YAML files from model spec for latest version."""
        test_model = "TCCDI"
        test_spec = TEST_MODEL_SPEC[test_model]
        actual = get_yaml_files_from_spec(test_spec, test_model)
        base_url = (
            "https://raw.githubusercontent.com/CBIIT/test-ccdi-model/2.0.0/model-desc/"
        )
        expected = [base_url + str(f) for f in test_spec["mdf_files"]]
        assert_equal(actual, expected)

    def test_get_yaml_files_from_spec_no_tag(self) -> None:
        """Test getting YAML files from model spec without a tag."""
        test_model = "TCCDI"
        test_spec = TEST_MODEL_SPEC[test_model]
        actual = get_yaml_files_from_spec(test_spec, test_model, "0.1.0")
        base_url = (
            "https://raw.githubusercontent.com/CBIIT/test-ccdi-model/0.1.0/model-desc/"
        )
        expected = [base_url + str(f) for f in test_spec["mdf_files"]]
        assert_equal(actual, expected)

    def test_get_yaml_files_from_spec_prerelease(self) -> None:
        """Test getting YAML files from model spec for prerelease version."""
        test_model = "TEST"
        test_spec = ModelSpec(
            {
                "repository": "test-model",
                "mdf_directory": "model-desc",
                "mdf_files": ["test-model.yml", "test-model-props.yml"],
                "in_data_hub": True,
                "versions": [
                    {"version": "1.0.0"},
                    {"version": "1.1.0"},
                ],
                "latest_version": "1.1.0",
                "latest_prerelease_version": "1.2.0",
                "latest_prerelease_commit": "abcd12304f69bd15672c4c380c562a7f0b40f06f",
            },
        )
        actual = get_yaml_files_from_spec(test_spec, test_model, "1.1.0-abcd123")
        base_url = "https://raw.githubusercontent.com/CBIIT"
        expected = [
            f"{base_url}/crdc-datahub-models/dev2/cache/TEST/1.2.0/test-model.yml",
            f"{base_url}/crdc-datahub-models/dev2/cache/TEST/1.2.0/test-model-props.yml",
        ]
        assert_equal(actual, expected)


class TestModelCDESpec:
    """Tests for model CDE spec."""

    TEST_MDF = Path(__file__).parent / "samples" / "test_mdf_cdes.yml"
    mdf = MDFReader(TEST_MDF)
    model = mdf.model

    def test_make_model_cde_spec(self) -> None:
        """Test making model CDE spec."""
        actual = make_model_cde_spec(self.model)
        assert_equal(actual, TEST_MAKE_MODEL_CDE_SPEC_BASE)

    def test_add_ncit_synonyms_to_model_cde_spec(self) -> None:
        """Test adding NCIt synonyms to model CDE spec."""
    
    def test_add_cde_pvs_skips_edp_annotations(self) -> None:
        """EDP-backed annotations should not be sent to caDSR API."""
        from unittest.mock import MagicMock
        from bento_mdb.model_cdes import add_cde_pvs_to_model_cde_spec
        mock_client = MagicMock()
        cde_spec = {
            "annotations": [
                {"annotation": {"attrs": {"origin_id": "11444542"}}, 
                "value_set": [], 
                "edp_reference": {"origin_id": "CRDC00001", "origin_name": "CRDC"}}
            ]
        }
        add_cde_pvs_to_model_cde_spec(cde_spec, mock_client)
        mock_client.fetch_cde_valueset.assert_not_called()

    def test_add_ncit_synonyms_skips_edp_annotations(self) -> None:
        """EDP-backed annotations should not be sent to NCIt API."""
        from unittest.mock import MagicMock
        from bento_mdb.model_cdes import add_ncit_synonyms_to_model_cde_spec
        mock_client = MagicMock()
        cde_spec = {
            "annotations": [
                {"annotation": {"attrs": {}}, 
                "value_set": [{"value": "test", "synonyms": []}], 
                "edp_reference": {"origin_id": "CRDC00001", "origin_name": "CRDC"}}
            ]
        }
        add_ncit_synonyms_to_model_cde_spec(cde_spec, mock_client)
        mock_client.ncim_mapping.__contains__ = MagicMock(return_value=False)
        assert cde_spec["annotations"][0]["value_set"][0]["synonyms"] == []

    def test_load_model_cde_spec(self) -> None:
        """Test loading model CDE spec."""


class TestCompareModelSpec:
    """Tests for model spec."""

    class MockMDB:
        def __init__(self, models: dict[str, list[str]]) -> None:
            self.models = models

    TEST_MDB_MODELS_YAML = Path(__file__).parent / "samples" / "test_mdb_models.yml"

    def test_compare_model_specs_to_mdb(self) -> None:
        """Test comparing model specs to MDB."""
        mock_mdb = self.MockMDB(
            {
                "TEST1": ["0.0.1"],
                "TEST2": ["1.0.0"],
                "TEST3": ["2.0.1", "2.0.1-wxyz789"],
            },
        )
        model_specs = load_model_specs_from_yaml(self.TEST_MDB_MODELS_YAML)
        actual_no_prerelease = compare_model_specs_to_mdb(model_specs, mock_mdb)  # type: ignore reportArgumentType
        actual_with_prerelease = compare_model_specs_to_mdb(
            model_specs,
            mock_mdb,  # type: ignore reportArgumentType
            include_prerelease=True,
        )
        expected_no_prerelease = {"TEST2": ["1.1.0"]}
        expected_with_prerelease = {
            "TEST2": ["1.1.0", "1.2.0-abcd123"],
            "TEST3": ["2.1.0-wxyz789"],
        }
        assert_equal(actual_no_prerelease, expected_no_prerelease)
        assert_equal(actual_with_prerelease, expected_with_prerelease)

    def test_compare_model_specs_matrix_flow(self) -> None:
        """Test how the matrix generation works with different MDB scenarios."""
        dev_mdb = self.MockMDB({"TEST2": ["1.0.0"]})
        nightly_mdb = self.MockMDB({"TEST2": ["1.0.0", "1.1.0"]})
        model_specs = {
            "TEST2": {
                "in_data_hub": True,
                "versions": [
                    {"version": "1.0.0"},
                    {"version": "1.1.0"},
                ],
                "latest_version": "1.1.0",
                "latest_prerelease_version": "1.1.0",
                "latest_prerelease_commit": "abcd12304f69bd15672c4c380c562a7f0b40f06f",
            },
        }
        dev_actual = compare_model_specs_to_mdb(
            model_specs,
            dev_mdb,
            include_prerelease=False,
        )
        dev_expected = {"TEST2": ["1.1.0"]}
        assert_equal(dev_actual, dev_expected)
        nightly_actual = compare_model_specs_to_mdb(
            model_specs,
            nightly_mdb,
            include_prerelease=True,
        )
        nightly_expected = {"TEST2": ["1.1.0-abcd123"]}
        assert_equal(nightly_actual, nightly_expected)


def test_process_mdb_cdes() -> None:
    raw_mdb_cdes = copy.deepcopy(TEST_MDB_CDE_SPEC_RAW)
    process_mdb_cdes([raw_mdb_cdes])  # type: ignore reportArgumentType
    assert_equal(raw_mdb_cdes, TEST_MDB_CDE_SPEC)

class TestGetEdpEnumTerm:
    """Tests for get_edp_enum_term."""

    TEST_EDP_MDF = Path(__file__).parent / "samples" / "test_mdf_edp.yml"
    @pytest.mark.xfail(reason="Requires bento-mdf EDP enum parsing not compatible")
    def test_get_edp_enum_term_returns_term_when_edp_present(self) -> None:
        """Property with EDP enum should return the EDP term."""
        from bento_mdb.model_cdes import get_edp_enum_term
        mdf = MDFReader(self.TEST_EDP_MDF)
        prop = mdf.model.props[("program", "program_name")]
        result = get_edp_enum_term(prop)
        assert result is not None
        assert result.origin_id == "CRDC00001"
        assert result.origin_name == "CRDC"

    def test_get_edp_enum_term_returns_none_when_no_edp(self) -> None:
        """Property with plain string enum should return None."""
        from bento_mdb.model_cdes import get_edp_enum_term
        TEST_MDF = Path(__file__).parent / "samples" / "test_mdf_cdes.yml"
        mdf = MDFReader(TEST_MDF)
        prop = mdf.model.props[("study", "organism_species")]
        result = get_edp_enum_term(prop)
        assert result is None


class TestMakeModelCdeSpecWithEdp:
    """Tests for make_model_cde_spec with EDP properties."""

    TEST_EDP_MDF = Path(__file__).parent / "samples" / "test_mdf_edp.yml"

    @pytest.mark.xfail(reason="Requires bento-mdf EDP enum DICT parsing not yet implemented in convert.py")
    def test_make_model_cde_spec_edp_reference_populated(self) -> None:
        """Annotation for EDP-backed CDE should have edp_reference set."""
        from bento_mdf.mdf import MDFReader
        mdf = MDFReader(self.TEST_EDP_MDF, ignore_enum_by_reference=True)
        actual = make_model_cde_spec(mdf.model)
        assert len(actual["annotations"]) == 1
        edp_ref = actual["annotations"][0].get("edp_reference")
        assert edp_ref is not None
        assert edp_ref["origin_id"] == "CRDC00001"
        assert edp_ref["origin_name"] == "CRDC"

    @pytest.mark.xfail(reason="Requires bento-mdf EDP enum DICT parsing not yet implemented in convert.py")
    def test_make_model_cde_spec_edp_matches_expected(self) -> None:
        """Full spec output for EDP model matches expected structure."""
        from bento_mdf.mdf import MDFReader
        from tests.test_utils import TEST_MAKE_MODEL_CDE_SPEC_EDP
        mdf = MDFReader(self.TEST_EDP_MDF, ignore_enum_by_reference=True)
        actual = make_model_cde_spec(mdf.model)
        assert_equal(actual, TEST_MAKE_MODEL_CDE_SPEC_EDP)

    def test_make_model_cde_spec_non_edp_has_no_edp_reference(self) -> None:
        """Annotation for plain CDE should have edp_reference as None."""
        TEST_MDF = Path(__file__).parent / "samples" / "test_mdf_cdes.yml"
        mdf = MDFReader(TEST_MDF)
        actual = make_model_cde_spec(mdf.model)
        edp_ref = actual["annotations"][0].get("edp_reference")
        assert edp_ref is None