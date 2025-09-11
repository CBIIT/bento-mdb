#!/usr/bin/env python3
"""Script to process CDEs that annotate CRDC data model entities."""

from __future__ import annotations

import logging
from pathlib import Path

import click
from bento_mdf.mdf import MDF

from bento_mdb_updates.clients import CADSRClient, NCItClient
from bento_mdb_updates.model_cdes import (
    add_cde_pvs_to_model_cde_spec,
    add_ncit_synonyms_to_model_cde_spec,
    count_model_cdes,
    dump_to_yaml,
    make_model_cde_spec,
)

logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "-m",
    "--model_handle",
    required=True,
    type=str,
    prompt=True,
    help="CRDC Model Handle (e.g. 'GDC')",
)
@click.option(
    "-v",
    "--model_version",
    required=False,
    type=str,
    help="Manually set model version (e.g., 1.2.3) if not included in MDF.",
)
@click.option(
    "-f",
    "--mdf_files",
    required=True,
    type=str,
    prompt=True,
    multiple=True,
    help="path or URL to MDF YAML file(s)",
)
def main(model_handle: str, model_version: str, mdf_files: str | list[str]) -> None:
    """Do stuff."""
    ncit_client = NCItClient()
    cadsr_client = CADSRClient()

    # get CDEs from model files
    logger.info("Getting CDEs from %s v%s MDFs...", model_handle, model_version)
    mdf = MDF(*mdf_files, handle=model_handle, raise_error=True)
    model = mdf.model
    (f"{model_handle} v{model_version} has {count_model_cdes(model)} CDEs.")
    model_cde_spec = make_model_cde_spec(model)

    add_cde_pvs_to_model_cde_spec(model_cde_spec, cadsr_client)
    add_ncit_synonyms_to_model_cde_spec(model_cde_spec, ncit_client)

    # save cde spec to yaml
    output_dir = Path().cwd() / "data/output/model_cde_pvs"
    model_cdes_yml = (
        output_dir / model_handle / f"{model_handle}_{model_version}_cdes.yml"
    )

    dump_to_yaml(model_cde_spec, model_cdes_yml)


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameters
