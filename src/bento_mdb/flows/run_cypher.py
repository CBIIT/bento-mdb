"""Run arbitrary Cypher queries on MDB."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from bento_meta.mdb import MDB
from prefect import flow, get_run_logger, task
from prefect.cache_policies import INPUTS

from bento_mdb_updates.mdb_utils import init_mdb_connection

if TYPE_CHECKING:
    from bento_meta.mdb import MDB

no_cache_mdb = INPUTS - "mdb"


@task
def create_connection(
    mdb_id: str,
    *,
    writeable: bool = True,
    allow_empty: bool = True,
) -> MDB:
    """Create a connection to the MDB."""
    logger = get_run_logger()
    logger.setLevel(logging.INFO)
    mdb = None
    try:
        mdb = init_mdb_connection(
            mdb_id,
            writeable=writeable,
            allow_empty=allow_empty,
        )
    except Exception:
        logger.exception("Error on MDB connection attempt")
        raise
    return mdb


@task(cache_policy=no_cache_mdb)
def execute_cypher(
    mdb: MDB,
    query: str,
    params: dict,
    *,
    is_write: bool = True,
) -> None:
    """Run Cypher on MDB."""
    logger = get_run_logger()
    logger.setLevel(logging.INFO)
    qfn = None
    result = None
    logger.info("Run query '%s'...", query)
    qfn = mdb.put_with_statement if is_write else mdb.get_with_statement
    try:
        result = qfn(query, params)
        logger.info("...completed")
    except Exception:
        logger.exception("Error in MDB query run")
        raise
    return result


@flow(name="run-cypher", log_prints=True)
def run_cypher_flow(
    mdb_id: str,
    query: list,
    params: dict | None = None,
    *,
    allow_empty: bool | None = True,
) -> None:
    """Run arbitrary Cypher queries on MDB."""
    if params is None:
        params = {}
    logger = get_run_logger()
    logger.setLevel(logging.INFO)
    logger.info("Running query:\n%s", query)
    results = []
    mdb = create_connection(mdb_id, writeable=True, allow_empty=allow_empty)
    if params:
        logger.info(" with params:\n%s", params)

    if len(query) == 1:
        qpath = Path(query[0])
        if qpath.exists():
            query = list(qpath.open())

    for q in query:
        try:
            result = execute_cypher(mdb, q, params)
            results.append(result)
        except Exception:
            logger.exception("Query '%s' failed", q)
    logger.info("Queries finished.")
    logger.info(results)
