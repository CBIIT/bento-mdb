import pytest

from bento_mdb.consistency import evaluate_expectation, load_checks_from_yaml, load_query, prepare_read_query

def test_prepare_read_query_adds_return_guard_without_rewriting_query():
    query = """MATCH (t:term)
WITH t.value AS value, count(*) AS n
WHERE n > 1
RETURN count(*) AS duplicate_groups"""

    prepared = prepare_read_query(query)

    assert prepared.splitlines()[0].startswith("// RETURN guard")
    assert query in prepared


def test_prepare_read_query_satisfies_bento_meta_return_check():
    query = """MATCH (t:term)
WITH t.value AS value, count(*) AS n
WHERE n > 1
RETURN count(*) AS duplicate_groups"""

    prepared = prepare_read_query(query)

    assert prepared.lower().splitlines()[0].find("return") != -1


def test_prepare_read_query_rejects_empty_query():
    with pytest.raises(ValueError, match="Cypher query cannot be empty"):
        prepare_read_query("   ")

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


def test_load_query_inline():
    check = {"id": "inline", "query": "MATCH (n) RETURN count(n) AS ct"}

    assert load_query(check) == "MATCH (n) RETURN count(n) AS ct"


def test_load_query_requires_query_or_file():
    with pytest.raises(ValueError, match="must define query or query_file"):
        load_query({"id": "bad"})