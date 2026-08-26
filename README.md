# Metamodel Database

The metamodel database (MDB) records
- node/relationship/property structure of models;
- the official local vocabulary - terms that are employed in the backend data system;
- synonyms for local vocabulary mapped from external standards; and
- the value sets for properties with enumerated value domains, and data types for other properties.

The production instance of MDB contains a practical representation of a data model, in that it records the curated external terminology mappings and official sets of valid terms for each relevant property. In this way, the MDB is an extension of the [MDF](https://github.com/CBIIT/bento-mdf) for any model it contains.

As the central location for official mappings to external vocabularies, the MDB can (should) be used as part of software modules that convert between the data physically stored in the production database and external standards. For example, an API known as the Simple Terminology Service [STS](https://github.com/CBIIT/bento-sts), using MDB as its backend, is used for simple queries about a given model and validation of incoming data.

The [bento-meta](https://github.com/CBIIT/bento-meta) repository contains APIS for working with the MDB in Python and Perl.

## Documentation

[View MDB documentation on GitHub Pages](https://cbiit.github.io/bento-mdb/)


## MDB Consistency Checks

MDB consistency checks are configurable read-only Cypher diagnostics for validating MDB graph contents. The checker logic lives in `bento_mdb.consistency`, and the live MDB execution is handled by the `check_mdb_consistency_flow` Prefect flow.

Checks are configured in `config/mdb_consistency_queries.yml`. Each check defines a description, a Cypher query or query file, tags, severity, and the expected result when MDB is consistent.

The initial term deduplication diagnostic query is stored in `data/queries/term_dedup_diagnostic.cypher`.

### Run Unit Tests

The pytest tests validate the query-harness logic without connecting to MDB:

```bash
pytest tests/test_check_mdb_consistency.py
```

Live MDB checks are not run directly by local pytest because MDB credentials are stored as Prefect Secret blocks and the production MDB is accessed through the Prefect work pool.

### Run Live C1 Dev Checks

Use the `Check C1 Dev MDB Consistency` GitHub Actions workflow. The workflow triggers the `check-mdb-consistency` Prefect deployment with:

```text
mdb_id: cloud-one-mdb-dev
checks_yaml: config/mdb_consistency_queries.yml
```

The Prefect flow loads MDB credentials from the existing Prefect Secret naming convention:

```text
cloud-one-mdb-dev-uri
cloud-one-mdb-dev-usr
cloud-one-mdb-dev-pwd
```

### Add A Check
Add a new entry to config/mdb_consistency_queries.yml:
```yaml
checks:
  - id: my_check
    description: Description of the consistency rule.
    query_file: data/queries/my_check.cypher
    tags:
      - diagnostic
    severity: error
    expected:
        problem_count: 0
```
The query should return a field that can be compared to the expected value. For most diagnostics, the expected compliant result should be 0 problem rows or 0 problem groups.