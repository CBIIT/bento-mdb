"""Unit tests for promotion logic (flow module). Check 0 — MDF vs DEV. Check 1 — MDF vs QA."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bento_mdb.flows.check_promotion import (
    _load_mdf_handles,
    check_model_dev,
    check_model_qa,
)

import bento_mdb.flows.check_promotion as flow_module

TEST_DIR = Path(__file__).resolve().parent
SAMPLE_MDF_PATH = TEST_DIR / "samples" / "test_mdf.yml"

# test_mdf.yml: Handle TEST, Version 1.2.3, Nodes node_1..3, Relationships edge_1..2, Props prop_1..6
SPEC = {"latest_version": "1.2.3"}
MODEL = "TEST"
VERSION = "1.2.3"


# ── Check 0: MDF vs DEV ──────────────────────────────────────────────────────

def _make_dev_mock(nodes=None, rels=None, props=None) -> MagicMock:
    """Mock MDB for DEV side. get_with_statement returns nodes/rels/props for diff."""
    mock = MagicMock()
    node_rows = [{"handle": h} for h in (nodes or [])]
    rel_rows = [{"handle": h} for h in (rels or [])]
    prop_rows = [{"prop": p, "node": n} for p, n in (props or [])]

    def side(cypher, params):
        if "n:node" in cypher and "has_property" not in cypher:
            return node_rows
        if "r:relationship" in cypher:
            return rel_rows
        return prop_rows

    mock.get_with_statement.side_effect = side
    return mock


class TestCheckModelDev:
    """Check 0: MDF vs DEV. MDF from tests/samples/test_mdf.yml, DEV mocked."""

    @patch.object(flow_module, "get_run_logger")
    @patch.object(flow_module, "get_yaml_files_from_spec", return_value=[str(SAMPLE_MDF_PATH)])
    @patch.object(flow_module, "_connect")
    def test_passed_when_mdf_and_dev_in_sync(
        self, mock_connect, mock_get_yaml, mock_logger
    ) -> None:
        """MDF (real file) and DEV have same handles -> passed."""
        mdf_nodes, mdf_rels, mdf_props = _load_mdf_handles(SPEC, MODEL, VERSION)
        mock_connect.return_value = _make_dev_mock(
            nodes=sorted(mdf_nodes),
            rels=sorted(mdf_rels),
            props=sorted(mdf_props),
        )
        result = check_model_dev.fn(MODEL, SPEC, "dev-mdb")
        assert result.passed
        assert result.model == MODEL
        assert result.version == VERSION
        assert result.inserts == 0 and result.removals == 0

    @patch.object(flow_module, "get_run_logger")
    @patch.object(flow_module, "get_yaml_files_from_spec", return_value=[str(SAMPLE_MDF_PATH)])
    @patch.object(flow_module, "_connect")
    def test_inserts_when_mdf_has_more_than_dev(
        self, mock_connect, mock_get_yaml, mock_logger
    ) -> None:
        """MDF (real file) has more than DEV -> not passed, inserts>0."""
        mock_connect.return_value = _make_dev_mock(
            nodes=["node_1"],
            rels=[],
            props=[],
        )
        result = check_model_dev.fn(MODEL, SPEC, "dev-mdb")
        assert not result.passed
        assert result.inserts > 0
        assert result.removals == 0

    @patch.object(flow_module, "get_run_logger")
    @patch.object(flow_module, "get_yaml_files_from_spec", return_value=[str(SAMPLE_MDF_PATH)])
    @patch.object(flow_module, "_connect")
    def test_removals_when_dev_has_more_than_mdf(
        self, mock_connect, mock_get_yaml, mock_logger
    ) -> None:
        """DEV has more than MDF (real file) -> not passed, removals>0."""
        mdf_nodes, mdf_rels, mdf_props = _load_mdf_handles(SPEC, MODEL, VERSION)
        extra_node = "_extra_node"
        mock_connect.return_value = _make_dev_mock(
            nodes=sorted(mdf_nodes) + [extra_node],
            rels=sorted(mdf_rels),
            props=sorted(mdf_props),
        )
        result = check_model_dev.fn(MODEL, SPEC, "dev-mdb")
        assert not result.passed
        assert result.inserts == 0
        assert result.removals > 0


# ── Check 1: MDF vs QA ───────────────────────────────────────────────────────

class TestCheckModelQa:
    """Check 1: MDF vs QA. MDF from tests/samples/test_mdf.yml, QA mocked."""

    @patch.object(flow_module, "get_run_logger")
    @patch.object(flow_module, "get_yaml_files_from_spec", return_value=[str(SAMPLE_MDF_PATH)])
    @patch.object(flow_module, "_connect")
    def test_passed_when_mdf_and_qa_in_sync(
        self, mock_connect, mock_get_yaml, mock_logger
    ) -> None:
        """MDF (real file) and QA have same handles -> passed."""
        mdf_nodes, mdf_rels, mdf_props = _load_mdf_handles(SPEC, MODEL, VERSION)
        mock_connect.return_value = _make_dev_mock(
            nodes=sorted(mdf_nodes),
            rels=sorted(mdf_rels),
            props=sorted(mdf_props),
        )
        result = check_model_qa.fn(MODEL, SPEC, "qa-mdb")
        assert result.passed
        assert result.model == MODEL
        assert result.version == VERSION
        assert result.inserts == 0 and result.removals == 0

    @patch.object(flow_module, "get_run_logger")
    @patch.object(flow_module, "get_yaml_files_from_spec", return_value=[str(SAMPLE_MDF_PATH)])
    @patch.object(flow_module, "_connect")
    def test_inserts_when_mdf_has_more_than_qa(
        self, mock_connect, mock_get_yaml, mock_logger
    ) -> None:
        """MDF (real file) has more than QA -> not passed, inserts>0."""
        mock_connect.return_value = _make_dev_mock(
            nodes=["node_1"],
            rels=[],
            props=[],
        )
        result = check_model_qa.fn(MODEL, SPEC, "qa-mdb")
        assert not result.passed
        assert result.inserts > 0
        assert result.removals == 0

    @patch.object(flow_module, "get_run_logger")
    @patch.object(flow_module, "get_yaml_files_from_spec", return_value=[str(SAMPLE_MDF_PATH)])
    @patch.object(flow_module, "_connect")
    def test_removals_when_qa_has_more_than_mdf(
        self, mock_connect, mock_get_yaml, mock_logger
    ) -> None:
        """QA has more than MDF (real file) -> not passed, removals>0."""
        mdf_nodes, mdf_rels, mdf_props = _load_mdf_handles(SPEC, MODEL, VERSION)
        extra_node = "_extra_node"
        mock_connect.return_value = _make_dev_mock(
            nodes=sorted(mdf_nodes) + [extra_node],
            rels=sorted(mdf_rels),
            props=sorted(mdf_props),
        )
        result = check_model_qa.fn(MODEL, SPEC, "qa-mdb")
        assert not result.passed
        assert result.inserts == 0
        assert result.removals > 0
