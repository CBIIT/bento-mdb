from unittest.mock import MagicMock

import pytest

from bento_mdb.consistency import (
    evaluate_expectation,
    load_checks_from_yaml,
    load_query,
)
from bento_mdb.mdb_utils import execute_read_query


def test_execute_read_query_preserves_multiline_query():
    query = """MATCH (t:term)
WITH t.value AS value, count(*) AS n
WHERE n > 1
RETURN count(*) AS duplicate_groups"""
    params = {"model": "TEST"}
    expected_rows = [{"duplicate_groups": 0}]

    transaction = MagicMock()
    transaction.run.return_value.data.return_value = expected_rows
    session = MagicMock()
    session.execute_read.side_effect = lambda transaction_work: transaction_work(
        transaction
    )
    mdb = MagicMock()
    mdb.driver.session.return_value.__enter__.return_value = session

    rows = execute_read_query(mdb, query, params)

    assert rows == expected_rows
    transaction.run.assert_called_once_with(query, parameters=params)


def test_load_query_inline_preserves_query():
    expected_query = "MATCH (n) RETURN count(n) AS ct"
    check = {"id": "inline", "query": expected_query}

    query = load_query(check)

    assert query == expected_query


def test_load_query_multiline_query_file_preserves_query(tmp_path):
    query_file = tmp_path / "query.cypher"
    expected_query = """MATCH (t:term)
WITH t.value AS value, count(*) AS n
WHERE n > 1
RETURN count(*) AS duplicate_groups"""
    query_file.write_text(
        f"{expected_query}\n",
        encoding="utf-8",
    )

    check = {"id": "term_dedup_diagnostic", "query_file": "query.cypher"}

    query = load_query(check, repo_root=tmp_path)

    assert query == expected_query


def test_load_query_rejects_empty_query():
    check = {"id": "empty", "query": "   "}

    with pytest.raises(ValueError, match="query cannot be empty"):
        load_query(check)


def test_load_checks_from_yaml_uses_supplied_repo_root(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    checks_yaml = config_dir / "mdb_consistency_queries.yml"
    checks_yaml.write_text(
        """
checks:
  - id: test_check
    description: Test check
    query: RETURN 0 AS problem_count
    tags:
      - diagnostic
    severity: error
    expected:
      problem_count: 0
""",
        encoding="utf-8",
    )

    checks = load_checks_from_yaml(
        "config/mdb_consistency_queries.yml",
        repo_root=tmp_path,
    )

    assert checks[0]["id"] == "test_check"
    
def test_evaluate_expectation_expected_mapping_passes():
    check = {
        "id": "term_dedup_diagnostic",
        "description": "Detect duplicate term groups.",
        "expected": {
            "duplicate_groups": 0,
        },
    }
    rows = [{"duplicate_groups": 0}]

    result = evaluate_expectation(check, rows)

    assert result.passed is True
    assert result.actual == {"duplicate_groups": 0}
    assert result.expected == {"duplicate_groups": 0}


def test_evaluate_expectation_expected_mapping_fails():
    check = {
        "id": "term_dedup_diagnostic",
        "description": "Detect duplicate term groups.",
        "expected": {
            "duplicate_groups": 0,
        },
    }
    rows = [{"duplicate_groups": 3}]

    result = evaluate_expectation(check, rows)

    assert result.passed is False
    assert result.actual == {"duplicate_groups": 3}
    assert result.expected == {"duplicate_groups": 0}


def test_evaluate_expectation_multiple_fields_passes():
    check = {
        "id": "summary_check",
        "expected": {
            "duplicate_groups": 0,
            "redundant_terms": 0,
        },
    }
    rows = [{"duplicate_groups": 0, "redundant_terms": 0}]

    result = evaluate_expectation(check, rows)

    assert result.passed is True
    assert result.actual == {
        "duplicate_groups": 0,
        "redundant_terms": 0,
    }


def test_evaluate_expectation_missing_field_raises():
    check = {
        "id": "term_dedup_diagnostic",
        "expected": {
            "duplicate_groups": 0,
        },
    }

    with pytest.raises(ValueError, match="expected field"):
        evaluate_expectation(check, [{"other_count": 0}])


def test_evaluate_expectation_no_rows_raises():
    check = {
        "id": "term_dedup_diagnostic",
        "expected": {
            "duplicate_groups": 0,
        },
    }

    with pytest.raises(ValueError, match="returned no rows"):
        evaluate_expectation(check, [])


def test_load_query_requires_query_or_file():
    with pytest.raises(ValueError, match="must define query or query_file"):
        load_query({"id": "bad"})
