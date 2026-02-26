"""Unit tests for scripts/check_promotion.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.check_promotion import (
    _DiffResult,
    _find_updated_models,
    _load_specs,
    _print_diff,
    _query_handles,
    _read_last_promoted_sha,
)


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


# ── _print_diff ───────────────────────────────────────────────────────────────

class TestPrintDiff:
    def test_returns_zero_when_equal(self, capsys) -> None:
        assert _print_diff("NODES", {"a", "b"}, {"a", "b"}, "MDF", "MDB") == 0

    def test_counts_new_and_removed(self, capsys) -> None:
        total = _print_diff("NODES", {"a", "b"}, {"b", "c"}, "MDF", "MDB")
        assert total == 2  # a is NEW, c is REMOVED
        out = capsys.readouterr().out
        assert "<- NEW" in out
        assert "-> REMOVED" in out

    def test_output_shows_header_with_counts(self, capsys) -> None:
        _print_diff("NODES", {"a"}, {"a"}, "MDF", "MDB-DEV")
        out = capsys.readouterr().out
        assert "[NODES]" in out
        assert "MDF=1" in out and "same=1" in out


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

    def test_returns_correct_handles(self) -> None:
        mock = self._make_mdb(nodes=["case"], rels=["of_case"], props=[("id", "case")])
        nodes, rels, props = _query_handles(mock, "TEST", "1.0.0")
        assert nodes == {"case"}
        assert rels == {"of_case"}
        assert props == {("id", "case")}

    def test_empty_db_returns_empty_sets(self) -> None:
        nodes, rels, props = _query_handles(self._make_mdb(), "TEST", "1.0.0")
        assert nodes == rels == props == set()

    def test_exception_returns_empty_sets(self) -> None:
        mock = MagicMock()
        mock.get_with_statement.side_effect = RuntimeError("connection lost")
        nodes, rels, props = _query_handles(mock, "TEST", "1.0.0")
        assert nodes == rels == props == set()


# ── _load_specs ───────────────────────────────────────────────────────────────

class TestLoadSpecs:
    def test_no_filter_returns_all(self, spec_file) -> None:
        assert set(_load_specs(str(spec_file), ()).keys()) == {"MODELA", "MODELB"}

    def test_filter_returns_only_requested(self, spec_file) -> None:
        assert set(_load_specs(str(spec_file), ("MODELA",)).keys()) == {"MODELA"}

    def test_missing_file_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            _load_specs(str(tmp_path / "nonexistent.yml"), ())


# ── _DiffResult ───────────────────────────────────────────────────────────────

class TestDiffResult:
    def test_passed_when_no_diff(self) -> None:
        assert _DiffResult("CDS", "1.0", inserts=0, removals=0).passed

    def test_failed_when_inserts(self) -> None:
        assert not _DiffResult("CDS", "1.0", inserts=3, removals=0).passed

    def test_failed_when_removals(self) -> None:
        assert not _DiffResult("CDS", "1.0", inserts=0, removals=1).passed


# ── _read_last_promoted_sha ───────────────────────────────────────────────────

class TestReadLastPromotedSha:
    def test_reads_sha(self, tmp_path) -> None:
        yml = tmp_path / "sync_status.yml"
        yml.write_text("promotion:\n  last_promoted_sha: abc123\n")
        with patch("scripts.check_promotion._SYNC_STATUS_PATH", yml):
            assert _read_last_promoted_sha() == "abc123"

    def test_returns_none_when_missing(self, tmp_path) -> None:
        with patch("scripts.check_promotion._SYNC_STATUS_PATH", tmp_path / "missing.yml"):
            assert _read_last_promoted_sha() is None


# ── _find_updated_models ──────────────────────────────────────────────────────

class TestFindUpdatedModels:
    def _mock_diff(self, stdout: str, returncode: int = 0) -> list[str]:
        mock = MagicMock(returncode=returncode, stdout=stdout)
        with patch("scripts.check_promotion.subprocess.run", return_value=mock):
            return _find_updated_models("abc123")

    def test_detects_version_bump(self) -> None:
        diff = "@@ -1 +1 @@ CDS:\n-  latest_version: 1.0\n+  latest_version: 1.1\n"
        assert self._mock_diff(diff) == ["CDS"]

    def test_ignores_prerelease_change(self) -> None:
        diff = "@@ -1 +1 @@ ICDC:\n-  latest_prerelease_commit: abc\n+  latest_prerelease_commit: def\n"
        assert self._mock_diff(diff) == []

    def test_empty_or_failed_returns_empty(self) -> None:
        assert self._mock_diff("") == []
        assert self._mock_diff("...", returncode=1) == []
