"""Tests for the run-cypher flow."""

from unittest.mock import MagicMock, patch

import bento_mdb.flows.run_cypher as flow_module


def test_long_single_query_is_executed_as_cypher() -> None:
    """A long query must not be interpreted as a local file path."""
    query = "MATCH (n) RETURN n // " + ("x" * 300)
    mdb = object()

    with (
        patch.object(flow_module, "get_run_logger"),
        patch.object(flow_module, "create_connection", return_value=mdb),
        patch.object(flow_module, "execute_cypher", return_value=[]) as execute,
    ):
        flow_module.run_cypher_flow.fn("test-mdb", [query])

    execute.assert_called_once_with(mdb, query, {})


def test_query_is_loaded_from_s3_when_bucket_is_provided() -> None:
    """Query list items are treated as S3 keys when a bucket is provided."""
    query = "MATCH (n) RETURN count(n) AS ct"
    body = MagicMock()
    body.read.return_value = query.encode("utf-8")
    s3 = MagicMock()
    s3.get_object.return_value = {"Body": body}
    mdb = object()

    with (
        patch.object(flow_module, "get_run_logger"),
        patch.object(flow_module.boto3, "client", return_value=s3),
        patch.object(flow_module, "create_connection", return_value=mdb),
        patch.object(flow_module, "execute_cypher", return_value=[]) as execute,
    ):
        flow_module.run_cypher_flow.fn(
            "test-mdb",
            ["queries/check.cypher"],
            bucket="test-bucket",
        )

    s3.get_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="queries/check.cypher",
    )
    execute.assert_called_once_with(mdb, query, {})
