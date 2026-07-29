import pytest

from bento_mdb.consistency import evaluate_expectation, load_query


def test_evaluate_expectation_equals_passes():
    check = {
        "id": "term_dedup_diagnostic",
        "description": "Detect duplicate term groups.",
        "expect": {
            "field": "duplicate_groups",
            "operator": "equals",
            "value": 0,
        },
    }
    rows = [{"duplicate_groups": 0}]

    result = evaluate_expectation(check, rows)

    assert result.passed is True
    assert result.actual == 0


def test_evaluate_expectation_equals_fails():
    check = {
        "id": "term_dedup_diagnostic",
        "description": "Detect duplicate term groups.",
        "expect": {
            "field": "duplicate_groups",
            "operator": "equals",
            "value": 0,
        },
    }
    rows = [{"duplicate_groups": 3}]

    result = evaluate_expectation(check, rows)

    assert result.passed is False
    assert result.actual == 3


def test_evaluate_expectation_missing_field_raises():
    check = {
        "id": "term_dedup_diagnostic",
        "expect": {
            "field": "duplicate_groups",
            "operator": "equals",
            "value": 0,
        },
    }

    with pytest.raises(ValueError, match="expected field"):
        evaluate_expectation(check, [{"other_count": 0}])


def test_evaluate_expectation_row_count_equals():
    check = {
        "id": "empty_result_check",
        "expect": {
            "operator": "row_count_equals",
            "value": 0,
        },
    }

    result = evaluate_expectation(check, [])

    assert result.passed is True
    assert result.actual == 0


def test_load_query_inline():
    check = {"id": "inline", "query": "MATCH (n) RETURN count(n) AS ct"}

    assert load_query(check) == "MATCH (n) RETURN count(n) AS ct"


def test_load_query_requires_query_or_file():
    with pytest.raises(ValueError, match="must define query or query_file"):
        load_query({"id": "bad"})