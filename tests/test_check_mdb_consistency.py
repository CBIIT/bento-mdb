import pytest

from bento_mdb.consistency import evaluate_expectation, load_query


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


def test_load_query_inline():
    check = {"id": "inline", "query": "MATCH (n) RETURN count(n) AS ct"}

    assert load_query(check) == "MATCH (n) RETURN count(n) AS ct"


def test_load_query_requires_query_or_file():
    with pytest.raises(ValueError, match="must define query or query_file"):
        load_query({"id": "bad"})