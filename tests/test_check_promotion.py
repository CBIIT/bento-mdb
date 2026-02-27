"""Unit tests for promotion logic (flow module) and detect-updated CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bento_mdb.flows.check_promotion import (
    _DiffResult,
    _load_specs,
    _query_handles,
    find_updated_models,
    read_last_promoted_sha,
)

# Import for patch targets
import bento_mdb.flows.check_promotion as flow_module


# ── fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_SPEC_YML = """
MODELA:
    repository: CBIIT/model-a
    mdf_directory: model-desc
    mdf_files:
    - model-a.yml
    versions:
    - version: 1.0.0
      tag: 1.0.0
    latest_version: 1.0.0
MODELB:
    repository: CBIIT/model-b
    mdf_directory: model-desc
    mdf_files:
    - model-b.yml
    versions:
    - version: 2.0.0
      tag: 2.0.0
    latest_version: 2.0.0
"""


@pytest.fixture()
def spec_file(tmp_path) -> Path:
    p = tmp_path / "models.yml"
    p.write_text(SAMPLE_SPEC_YML, encoding="utf-8")
    return p


# ── _query_handles ────────────────────────────────────────────────────────────

class TestQueryHandles:
    def _make_mdb(self, nodes=None, rels=None, props=None) -> MagicMock:
        mock = MagicMock()
        node_rows = [{"handle": h} for h in (nodes or [])]
        rel_rows  = [{"handle": h} for h in (rels or [])]
        prop_rows = [{"prop": p, "node": n} for p, n in (props or [])]

        def side(cypher, params):
            if "n:node" in cypher and "has_property" not in cypher:
                return node_rows
            if "r:relationship" in cypher:
                return rel_rows
            return prop_rows

        mock.get_with_statement.side_effect = side
        return mock

    @patch.object(flow_module, "get_run_logger")
    def test_returns_correct_handles(self, mock_logger) -> None:
        mock = self._make_mdb(nodes=["case"], rels=["of_case"], props=[("id", "case")])
        nodes, rels, props = _query_handles(mock, "TEST", "1.0.0")
        assert nodes == {"case"}
        assert rels == {"of_case"}
        assert props == {("id", "case")}

    @patch.object(flow_module, "get_run_logger")
    def test_empty_db_returns_empty_sets(self, mock_logger) -> None:
        nodes, rels, props = _query_handles(self._make_mdb(), "TEST", "1.0.0")
        assert nodes == rels == props == set()

    @patch.object(flow_module, "get_run_logger")
    def test_exception_returns_empty_sets(self, mock_logger) -> None:
        mock = MagicMock()
        mock.get_with_statement.side_effect = RuntimeError("connection lost")
        nodes, rels, props = _query_handles(mock, "TEST", "1.0.0")
        assert nodes == rels == props == set()


# ── _load_specs ───────────────────────────────────────────────────────────────

class TestLoadSpecs:
    def test_no_filter_returns_all(self, spec_file) -> None:
        with patch.object(flow_module, "_MDB_MODELS_PATH", spec_file):
            assert set(_load_specs(None).keys()) == {"MODELA", "MODELB"}

    def test_filter_returns_only_requested(self, spec_file) -> None:
        with patch.object(flow_module, "_MDB_MODELS_PATH", spec_file):
            assert set(_load_specs(["MODELA"]).keys()) == {"MODELA"}

    def test_missing_file_raises(self, tmp_path) -> None:
        with patch.object(flow_module, "_MDB_MODELS_PATH", tmp_path / "nonexistent.yml"):
            with pytest.raises(FileNotFoundError):
                _load_specs(None)


# ── _DiffResult ───────────────────────────────────────────────────────────────

class TestDiffResult:
    def test_passed_when_no_diff(self) -> None:
        assert _DiffResult("CDS", "1.0", inserts=0, removals=0).passed

    def test_failed_when_inserts(self) -> None:
        assert not _DiffResult("CDS", "1.0", inserts=3, removals=0).passed

    def test_failed_when_removals(self) -> None:
        assert not _DiffResult("CDS", "1.0", inserts=0, removals=1).passed


# ── read_last_promoted_sha ────────────────────────────────────────────────────

class TestReadLastPromotedSha:
    def test_reads_sha(self, tmp_path) -> None:
        yml = tmp_path / "sync_status.yml"
        yml.write_text("promotion:\n  last_promoted_sha: abc123\n")
        with patch.object(flow_module, "_SYNC_STATUS_PATH", yml):
            assert read_last_promoted_sha() == "abc123"

    def test_returns_none_when_missing(self, tmp_path) -> None:
        with patch.object(flow_module, "_SYNC_STATUS_PATH", tmp_path / "missing.yml"):
            assert read_last_promoted_sha() is None


# ── find_updated_models ────────────────────────────────────────────────────────

class TestFindUpdatedModels:
    def _mock_diff(self, stdout: str, returncode: int = 0) -> list[str]:
        mock = MagicMock(returncode=returncode, stdout=stdout)
        with patch.object(flow_module, "subprocess") as subprocess_mod:
            subprocess_mod.run.return_value = mock
            return find_updated_models("abc123")

    def test_detects_version_bump(self) -> None:
        diff = "@@ -1 +1 @@ CDS:\n-  latest_version: 1.0\n+  latest_version: 1.1\n"
        assert self._mock_diff(diff) == ["CDS"]

    def test_ignores_prerelease_change(self) -> None:
        diff = "@@ -1 +1 @@ ICDC:\n-  latest_prerelease_commit: abc\n+  latest_prerelease_commit: def\n"
        assert self._mock_diff(diff) == []

    def test_empty_or_failed_returns_empty(self) -> None:
        assert self._mock_diff("") == []
        assert self._mock_diff("...", returncode=1) == []
