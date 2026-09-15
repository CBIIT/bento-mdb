"""Regression coverage for caDSR PV replacement handling."""

from unittest.mock import patch

import pytest
from testcontainers.neo4j import Neo4jContainer

from bento_mdb.cde_cypher import convert_annotation_to_changesets
from bento_mdb.clients import CADSRClient
from bento_mdb.cypher_utils import cypher_string_literal


def _pv(value: str, origin_id: str, origin_version: str = "1") -> dict:
    return {
        "value": value,
        "origin_id": origin_id,
        "origin_version": origin_version,
        "origin_definition": f"definition for {origin_id}",
        "origin_name": "caDSR",
        "ncit_concept_codes": [],
        "synonyms": [],
        "alternates": [],
    }


def _mdb_cde(permissible_values: list[dict]) -> list[dict]:
    return [
        {
            "CDECode": "12345",
            "CDEVersion": "1.00",
            "CDEFullName": "Regression CDE",
            "CDEOrigin": "caDSR",
            "models": [],
            "permissibleValues": permissible_values,
        },
    ]


def _released_cde_details() -> dict:
    return {
        "CDECode": "12345",
        "CDEVersion": "1.00",
        "CDEFullName": "Regression CDE",
        "CDEWorkflowStatus": "RELEASED",
    }


def test_replaced_pv_generates_unlink_before_new_link() -> None:
    """A changed PV identity unlinks the old PV and links its replacement."""
    client = CADSRClient()
    pv_value = "Children's \"Hospital\""
    old_pv = _pv(pv_value, "old-origin-id")
    new_pv = _pv(pv_value, "new-origin-id")

    with (
        patch.object(client, "fetch_cde_valueset", return_value=[new_pv]),
        patch.object(
            client,
            "fetch_cde_details",
            return_value=_released_cde_details(),
        ),
    ):
        annotations = client.check_cdes_against_mdb(_mdb_cde([old_pv]))

    assert len(annotations) == 1
    assert annotations[0]["removed_pvs"] == [
        {
            "value": pv_value,
            "origin_id": "old-origin-id",
            "origin_version": "1",
        },
    ]
    assert annotations[0]["value_set"] == [new_pv]

    changesets = convert_annotation_to_changesets(
        annotations[0],
        changeset_id=1,
        author="TEST",
        _commit="PV-REGRESSION",
    )
    statements = [changeset.change_type.text for changeset in changesets]

    delete_index = next(
        index
        for index, statement in enumerate(statements)
        if statement.endswith("DELETE r")
    )
    new_term_index = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("MERGE (n0:term")
        and "new-origin-id" in statement
    )
    new_link_index = next(
        index
        for index, statement in enumerate(statements)
        if ":has_term" in statement
        and "new-origin-id" in statement
    )

    assert "old-origin-id" in statements[delete_index]
    assert cypher_string_literal(pv_value) in statements[delete_index]
    assert "DELETE r, pv" not in statements[delete_index]
    assert r"Children\'s" in statements[new_term_index]
    assert r"Children\'s" in statements[new_link_index]
    assert delete_index < new_term_index < new_link_index


def test_empty_pv_response_does_not_generate_mass_unlinks() -> None:
    """An ambiguous empty API response must not unlink all existing PVs."""
    client = CADSRClient()
    old_pv = _pv("Last PV", "last-origin-id")

    with (
        patch.object(client, "fetch_cde_valueset", return_value=[]),
        patch.object(
            client,
            "fetch_cde_details",
            return_value=_released_cde_details(),
        ) as fetch_details,
    ):
        annotations = client.check_cdes_against_mdb(_mdb_cde([old_pv]))

    assert annotations == []
    fetch_details.assert_not_called()


@pytest.mark.docker
def test_replaced_pv_changesets_execute_against_neo4j() -> None:
    """Run replacement Cypher and verify the relationship-level update."""
    handle = "pv-regression|1.00"
    other_handle = "other-value-set|1.00"
    pv_value = "Children's \"Hospital\""
    old_origin_id = "old-origin-id"
    new_origin_id = "new-origin-id"
    annotation = {
        "entity": {},
        "annotation": {
            "key": ("Regression CDE", "caDSR"),
            "attrs": {
                "origin_id": "pv-regression",
                "origin_version": "1.00",
                "origin_name": "caDSR",
                "value": "Regression CDE",
            },
        },
        "value_set": [_pv(pv_value, new_origin_id)],
        "removed_pvs": [
            {
                "value": pv_value,
                "origin_id": old_origin_id,
                "origin_version": "1",
            },
        ],
    }
    changesets = convert_annotation_to_changesets(
        annotation,
        changeset_id=1,
        author="TEST",
        _commit="PV-REGRESSION",
    )

    with Neo4jContainer(
        "neo4j:4.4.44-community",
        password="changeme",
    ) as neo4j_container:
        with neo4j_container.get_driver() as driver:
            with driver.session() as session:
                session.run(
                    "CREATE (vs:value_set {handle: $handle}) "
                    "CREATE (old:term {"
                    "value: $value, origin_id: $origin_id, "
                    "origin_version: '1', origin_name: 'caDSR'"
                    "}) "
                    "CREATE (other:value_set {handle: $other_handle}) "
                    "CREATE (vs)-[:has_term]->(old) "
                    "CREATE (other)-[:has_term]->(old)",
                    handle=handle,
                    other_handle=other_handle,
                    value=pv_value,
                    origin_id=old_origin_id,
                ).consume()

                for changeset in changesets:
                    session.run(changeset.change_type.text).consume()

                result = session.run(
                    "MATCH (vs:value_set {handle: $handle}) "
                    "OPTIONAL MATCH (vs)-[:has_term]->(old:term {"
                    "origin_id: $old_origin_id"
                    "}) "
                    "OPTIONAL MATCH (vs)-[:has_term]->(new:term {"
                    "origin_id: $new_origin_id"
                    "}) "
                    "MATCH (other:value_set {handle: $other_handle}) "
                    "OPTIONAL MATCH (other)-[:has_term]->(shared_old:term {"
                    "origin_id: $old_origin_id"
                    "}) "
                    "MATCH (old_node:term {origin_id: $old_origin_id}) "
                    "RETURN count(DISTINCT vs) AS value_sets, "
                    "count(DISTINCT old) AS old_links, "
                    "count(DISTINCT new) AS new_links, "
                    "count(DISTINCT shared_old) AS other_value_set_links, "
                    "count(DISTINCT old_node) AS old_nodes",
                    handle=handle,
                    other_handle=other_handle,
                    old_origin_id=old_origin_id,
                    new_origin_id=new_origin_id,
                ).single()

    assert result is not None
    assert result["value_sets"] == 1
    assert result["old_links"] == 0
    assert result["new_links"] == 1
    assert result["other_value_set_links"] == 1
    assert result["old_nodes"] == 1
