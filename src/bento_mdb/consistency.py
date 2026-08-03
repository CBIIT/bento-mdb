from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class ExpectationResult:
    check_id: str
    description: str
    passed: bool
    actual: dict[str, Any]
    expected: dict[str, Any]
    rows: list[dict[str, Any]]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_query(check: dict[str, Any], repo_root: Path = _REPO_ROOT) -> str:
    if "query" in check:
        return check["query"]

    if "query_file" in check:
        query_path = repo_root / check["query_file"]
        return query_path.read_text(encoding="utf-8")

    msg = f"Check {check.get('id')} must define query or query_file"
    raise ValueError(msg)


def load_checks_from_yaml(
    checks_yaml: str | Path,
    tags: list[str] | None = None,
    repo_root: Path = _REPO_ROOT,
) -> list[dict[str, Any]]:
    config_path = Path(checks_yaml)
    if not config_path.is_absolute():
        config_path = repo_root / config_path

    config = load_yaml(config_path)
    checks = config.get("checks", [])

    if not isinstance(checks, list):
        raise ValueError("'checks' must be a list")

    if tags:
        requested_tags = set(tags)
        checks = [
            check for check in checks
            if requested_tags.intersection(set(check.get("tags", [])))
        ]

    return checks


def evaluate_expectation(
    check: dict[str, Any],
    rows: list[dict[str, Any]],
) -> ExpectationResult:
    expected = check["expected"]

    if not rows:
        msg = f"Check {check['id']} returned no rows"
        raise ValueError(msg)

    actual_row = rows[0]
    mismatches = {}

    for field, expected_value in expected.items():
        if field not in actual_row:
            msg = f"Check {check['id']} expected field {field!r}; got {list(actual_row.keys())}"
            raise ValueError(msg)

        actual_value = actual_row[field]
        if actual_value != expected_value:
            mismatches[field] = {
                "actual": actual_value,
                "expected": expected_value,
            }

    return ExpectationResult(
        check_id=check["id"],
        description=check.get("description", ""),
        passed=not mismatches,
        actual={field: actual_row[field] for field in expected},
        expected=expected,
        rows=rows,
    )