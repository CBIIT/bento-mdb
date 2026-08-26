"""Tests for bento_mdb.promotion_detect (parse git diff of mdb_models.yml)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bento_mdb.promotion_detect import parse_diff


def _diff(context: str, *added_lines: str) -> str:
    """Build a minimal diff fragment: context line then added lines."""
    lines = [context]
    for line in added_lines:
        lines.append("+" + line if not line.startswith("+") else line)
    return "\n".join(lines)


def test_parse_diff_empty() -> None:
    assert parse_diff("") == []
    assert parse_diff("nothing relevant\n") == []


def test_parse_diff_release_only() -> None:
    diff = _diff("@@ -40,7 +40,7 @@ CDS:", "  latest_version: 11.0.4")
    out = parse_diff(diff)
    assert len(out) == 1
    assert out[0]["model"] == "CDS"
    assert out[0]["latest_version"] == "11.0.4"
    assert out[0]["prerelease_version"] is None
    assert out[0]["has_prerelease_update"] is False


def test_parse_diff_prerelease_only() -> None:
    diff = _diff(
        "@@ -1,6 +1,6 @@ ICDC:",
        "  latest_prerelease_commit: abc1234567890",
        "  latest_prerelease_version: 2.0.0",
    )
    out = parse_diff(diff)
    assert len(out) == 1
    assert out[0]["model"] == "ICDC"
    assert out[0]["latest_version"] is None
    assert out[0]["prerelease_version"] == "2.0.0-abc1234"
    assert out[0]["has_prerelease_update"] is True


def test_parse_diff_release_and_prerelease_same_model() -> None:
    """When latest_version changed, prerelease is ignored — release takes priority."""
    diff = _diff(
        "@@ -40,7 +40,7 @@ CDS:",
        "  latest_version: 11.0.4",
        "  latest_prerelease_commit: def456",
    )
    out = parse_diff(diff)
    assert len(out) == 1
    assert out[0]["model"] == "CDS"
    assert out[0]["latest_version"] == "11.0.4"
    assert out[0]["prerelease_version"] is None  # ignored when release updated
    assert out[0]["has_prerelease_update"] is False


def test_parse_diff_two_models_one_release_one_prerelease() -> None:
    d1 = _diff("@@ -40,7 +40,7 @@ CDS:", "  latest_version: 11.0.4")
    d2 = _diff("@@ -1,6 +1,6 @@ ICDC:", "  latest_prerelease_version: 2.0.0")
    out = parse_diff(d1 + "\n" + d2)
    assert len(out) == 2
    models = [x["model"] for x in out]
    assert sorted(models) == ["CDS", "ICDC"]
    cds = next(x for x in out if x["model"] == "CDS")
    icdc = next(x for x in out if x["model"] == "ICDC")
    assert cds["has_prerelease_update"] is False
    assert icdc["has_prerelease_update"] is True


def test_parse_diff_two_models_both_prerelease_only() -> None:
    d1 = _diff("@@ -1,6 +1,6 @@ CDS:", "  latest_prerelease_version: 11.0.4")
    d2 = _diff("@@ -1,6 +1,6 @@ ICDC:", "  latest_prerelease_commit: abc1234")
    out = parse_diff(d1 + "\n" + d2)
    assert len(out) == 2
    assert all(x["has_prerelease_update"] for x in out)


def test_parse_diff_latest_prerelease_version_line_ignored() -> None:
    diff = _diff("@@ -40,7 +40,7 @@ X:", "  latest_prerelease_version: 1.0.0")
    out = parse_diff(diff)
    assert len(out) == 1
    assert out[0]["has_prerelease_update"] is True


def test_parse_diff_context_sets_current_model() -> None:
    diff = "@@ -1,6 +1,6 @@ SomeModel:\n  repository: foo\n"
    assert parse_diff(diff) == []


def test_parse_diff_new_prerelease_only_model() -> None:
    diff = _diff(
        "@@ -313,3 +313,18 @@ PSDC:",
        "TEST:",
        "  latest_version: null",
        "  latest_prerelease_commit: 277d1c56e41bdec9",
        "  latest_prerelease_version: 1.0.0",
    )
    assert parse_diff(diff) == [
        {
            "model": "TEST",
            "latest_version": None,
            "prerelease_version": "1.0.0-277d1c5",
            "prerelease_commit": "277d1c5",
            "has_prerelease_update": True,
        },
    ]


def test_parse_diff_prerelease_commit_only_with_specs_file(tmp_path: Path) -> None:
    """When only prerelease_commit is in diff, specs loaded from config fill prerelease_version."""
    import bento_mdb.promotion_detect as pd

    yaml_path = tmp_path / "config" / "mdb_models.yml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        "ICDC:\n  latest_version: 2.0.0\n  latest_prerelease_version: 2.1.0\n"
    )
    diff = _diff("@@ -1,6 +1,6 @@ ICDC:", "  latest_prerelease_commit: abc1234")
    with pytest.MonkeyPatch.context() as m:
        m.setattr(pd, "_DEFAULT_SPECS_PATH", yaml_path)
        out = parse_diff(diff)
    assert len(out) == 1
    assert out[0]["model"] == "ICDC"
    assert out[0]["prerelease_version"] == "2.1.0-abc1234"
    assert out[0]["has_prerelease_update"] is True


def test_parse_diff_is_prod_release_excludes_prerelease() -> None:
    """is_prod_release=True: only release (latest_version) updates, prerelease-only excluded."""
    d1 = _diff("@@ -40,7 +40,7 @@ CDS:", "  latest_version: 11.0.4")
    d2 = _diff("@@ -1,6 +1,6 @@ ICDC:", "  latest_prerelease_commit: abc1234")
    out = parse_diff(d1 + "\n" + d2, is_prod_release=True)
    assert len(out) == 1
    assert out[0]["model"] == "CDS"
    assert out[0]["has_prerelease_update"] is False
