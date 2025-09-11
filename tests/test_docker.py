"""Test Docker image."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DOCKERFILE_PATH = PROJECT_ROOT / "Dockerfile"
DOCKER_IMAGE_TAG = "mdb-update-test:latest"


# @pytest.mark.docker
# def test_mdb(mdb_versioned):
#     """Test that the MDB is running."""
#     bolt_url, http_url = mdb_versioned
#     mdb = MDB(uri=bolt_url, user=TEST_MDB_USER, password=TEST_MDB_PASSWORD)
#     assert mdb

# @pytest.mark.docker
# def test_prefect_flow(mdb_versioned, run_prefect_flow):
#     """Test that the Prefect flow is running."""
#     bolt_url, http_url = mdb_versioned
#     result = run_prefect_flow(
#         "tests/samples/test_prefect_flow.py",
#         "test-prefect-flow",
#         uri=bolt_url,
#         username=TEST_MDB_USER,
#         password=TEST_MDB_PASSWORD,
#     )
#     print(result)
#     assert result.returncode == 0
