"""Generate matrix with models/versions to be added to MDB."""

from __future__ import annotations

import json
from pathlib import Path

from prefect import flow

from bento_mdb_updates.constants import MDB_IDS_WITH_PRERELEASES
from bento_mdb_updates.mdb_utils import init_mdb_connection
from bento_mdb_updates.model_cdes import (
    compare_model_specs_to_mdb,
    get_yaml_files_from_spec,
    load_model_specs_from_yaml,
)


def make_matrix_output_more_visible(matrix: dict) -> None:
    """
    Make the matrix output more visible in logs.

    Print multiple times with clear markers.
    """
    result_json = json.dumps(matrix)
    print("\n" + "*" * 80)  # noqa: T201
    print("MATRIX_JSON_BEGIN")  # noqa: T201
    print(f"MATRIX_JSON:{result_json}")  # noqa: T201
    print("MATRIX_JSON_END")  # noqa: T201
    print("*" * 80 + "\n")  # noqa: T201
    print(f"MATRIX_JSON:{result_json}")  # noqa: T201


@flow(name="generate-model-version-matrix", log_prints=True)
def model_matrix_flow(
    mdb_id: str,
    model_specs_yaml: str,
    *,
    datahub_only: bool,
) -> None:
    """Generate matrix with models/versions to be added to MDB."""
    model_specs = load_model_specs_from_yaml(Path(model_specs_yaml))

    mdb = init_mdb_connection(mdb_id)

    include_prerelease = mdb_id in MDB_IDS_WITH_PRERELEASES
    models_to_update = compare_model_specs_to_mdb(
        model_specs,
        mdb,
        datahub_only=datahub_only,
        include_prerelease=include_prerelease,
    )
    matrix = {
        "include": [
            {
                "model": model,
                "version": version,
                "mdf_files": get_yaml_files_from_spec(
                    model_specs[model],
                    model,
                    version,
                ),
            }
            for model, versions in models_to_update.items()
            for version in versions
        ],
    }
    make_matrix_output_more_visible(matrix)
