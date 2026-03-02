"""Unit tests for promotion logic (flow module). Check 0 — MDF vs DEV. Check 1 — MDF vs QA."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bento_mdb.flows.check_promotion import (
    _load_mdf_handles,
    check_model_dev,
    check_model_qa,
    check_promotion_flow,
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


# ── check_promotion_flow ───────────────────────────────────────────────────────

def _diff_result(model: str, version: str, inserts: int = 0, removals: int = 0):
    """Build _DiffResult for flow tests."""
    return flow_module._DiffResult(model=model, version=version, inserts=inserts, removals=removals)


class TestCheckPromotionFlow:
    """Unit tests for check_promotion_flow (pre/post stage, pass/fail)."""

    @patch.object(flow_module, "check_model_sync")
    @patch.object(flow_module, "check_model_qa")
    @patch.object(flow_module, "check_model_dev")
    @patch.object(flow_module, "_load_specs", return_value={MODEL: SPEC})
    @patch.object(flow_module, "get_run_logger")
    def test_pre_stage_all_passed(
        self, mock_logger, mock_load_specs, mock_check_dev, mock_check_qa, mock_check_sync
    ) -> None:
        """stage=pre, all models pass Check 0 -> no exception."""
        mock_check_dev.return_value = _diff_result(MODEL, VERSION, 0, 0)
        check_promotion_flow.fn(stage="pre", models_filter=[MODEL])
        mock_load_specs.assert_called_once_with([MODEL])
        assert mock_check_dev.call_count == 1
        mock_check_qa.assert_not_called()
        mock_check_sync.assert_not_called()

    @patch.object(flow_module, "check_model_dev")
    @patch.object(flow_module, "_load_specs", return_value={MODEL: SPEC})
    @patch.object(flow_module, "get_run_logger")
    def test_pre_stage_fails_raises_value_error(
        self, mock_logger, mock_load_specs, mock_check_dev
    ) -> None:
        """stage=pre, one model fails Check 0 -> ValueError."""
        mock_check_dev.return_value = _diff_result(MODEL, VERSION, inserts=1, removals=0)
        with pytest.raises(ValueError, match=r"Check 0 FAILED.*out of sync with MDF.*TEST"):
            check_promotion_flow.fn(stage="pre", models_filter=[MODEL])

    @patch.object(flow_module, "check_model_sync")
    @patch.object(flow_module, "check_model_qa")
    @patch.object(flow_module, "check_model_dev")
    @patch.object(flow_module, "_load_specs", return_value={MODEL: SPEC})
    @patch.object(flow_module, "get_run_logger")
    def test_post_stage_all_passed(
        self, mock_logger, mock_load_specs, mock_check_dev, mock_check_qa, mock_check_sync
    ) -> None:
        """stage=post, Check 1 and Check 2 all pass -> no exception."""
        mock_check_qa.return_value = _diff_result(MODEL, VERSION, 0, 0)
        mock_check_sync.return_value = _diff_result(MODEL, VERSION, 0, 0)
        check_promotion_flow.fn(stage="post", models_filter=[MODEL])
        mock_load_specs.assert_called_once_with([MODEL])
        assert mock_check_qa.call_count == 1
        assert mock_check_sync.call_count == 1
        mock_check_dev.assert_not_called()

    @patch.object(flow_module, "check_model_sync")
    @patch.object(flow_module, "check_model_qa")
    @patch.object(flow_module, "_load_specs", return_value={MODEL: SPEC})
    @patch.object(flow_module, "get_run_logger")
    def test_post_stage_qa_fails_raises_value_error(
        self, mock_logger, mock_load_specs, mock_check_qa, mock_check_sync
    ) -> None:
        """stage=post, Check 1 (QA) fails -> ValueError."""
        mock_check_qa.return_value = _diff_result(MODEL, VERSION, inserts=1, removals=0)
        mock_check_sync.return_value = _diff_result(MODEL, VERSION, 0, 0)
        with pytest.raises(ValueError, match=r"Post-promotion checks FAILED.*TEST"):
            check_promotion_flow.fn(stage="post", models_filter=[MODEL])

    @patch.object(flow_module, "check_model_sync")
    @patch.object(flow_module, "check_model_qa")
    @patch.object(flow_module, "_load_specs", return_value={MODEL: SPEC})
    @patch.object(flow_module, "get_run_logger")
    def test_post_stage_sync_fails_raises_value_error(
        self, mock_logger, mock_load_specs, mock_check_qa, mock_check_sync
    ) -> None:
        """stage=post, Check 2 (DEV vs QA) fails -> ValueError."""
        mock_check_qa.return_value = _diff_result(MODEL, VERSION, 0, 0)
        mock_check_sync.return_value = _diff_result(MODEL, VERSION, removals=1)
        with pytest.raises(ValueError, match=r"Post-promotion checks FAILED.*TEST"):
            check_promotion_flow.fn(stage="post", models_filter=[MODEL])

    @patch.object(flow_module, "_load_specs", return_value={})
    @patch.object(flow_module, "get_run_logger")
    def test_unknown_stage_raises_value_error(
        self, mock_logger, mock_load_specs
    ) -> None:
        """Unknown stage -> ValueError."""
        with pytest.raises(ValueError, match=r"Unknown stage.*Must be 'pre' or 'post'"):
            check_promotion_flow.fn(stage="invalid")
