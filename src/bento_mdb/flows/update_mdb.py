"""Run Liquibase Update on Changelog."""

from __future__ import annotations

import io
import logging
import shutil
import stat
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.blocks.system import Secret
from prefect.logging.handlers import APILogHandler
from pyliquibase import Pyliquibase

from bento_mdb_updates.constants import VALID_LOG_LEVELS, VALID_MDB_IDS

# liquibase constants
DRIVER_PATH = "/app/drivers"
DRIVER_JAR = "liquibase-neo4j-4.31.1-full.jar"
LIQUIBASE_VERSION = "4.31.1"
DRIVER_NAME = "liquibase.ext.neo4j.database.jdbc.Neo4jDriver"

# configure jvm
JVM_HEAP_MIN = "1g"
JVM_HEAP_MAX = "3g"


@task
def set_defaults_file(
    changelog_file: str,
    mdb_id: str,
    log_level: str,
) -> tuple[Path, Path]:
    """Create temporary defaults file; returns paths of defaults file and log file."""
    logger = get_run_logger()
    if mdb_id not in VALID_MDB_IDS:
        msg = f"Invalid MDB ID: {mdb_id}. Valid IDs: {VALID_MDB_IDS}"
        raise ValueError(msg)
    if log_level not in VALID_LOG_LEVELS:
        logger.warning(
            "Invalid log level %r (valid: %s); defaulting to 'info'.",
            log_level,
            list(VALID_LOG_LEVELS.keys()),
        )
        log_level = "info"

    uri_secret_name = mdb_id + "-uri"
    usr_secret_name = mdb_id + "-usr"
    pwd_secret_name = mdb_id + "-pwd"
    uri = Secret.load(uri_secret_name).get()  # type: ignore reportAttributeAccessIssue
    user = Secret.load(usr_secret_name).get()  # type: ignore reportAttributeAccessIssue
    password = Secret.load(pwd_secret_name).get()  # type: ignore reportAttributeAccessIssue
    if mdb_id.startswith("og-mdb"):
        password = ""  # can't set empty string in prefect secrets

    # create liquibase log file
    log_file = tempfile.NamedTemporaryFile(suffix=".log", delete=False)  # noqa: SIM115
    log_file_path = Path(log_file.name)
    log_file.close()

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(f"changelogFile: {changelog_file}\n")
        f.write(f"url: {uri}\n")
        f.write(f"username: {user}\n")
        f.write(f"password: {password}\n")
        f.write(f"classpath: {DRIVER_PATH}\n")
        f.write(f"driver: {DRIVER_NAME}\n")
        f.write(f"logLevel: {log_level}\n")
        f.write(f"logFile: {log_file_path}\n")
        temp_file_path = Path(f.name)
    temp_file_path.chmod(
        stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP,
    )  # User/group read/write only
    return temp_file_path, log_file_path


@task
def run_liquibase_update(  # noqa: C901, PLR0912
    defaults_file: Path | str,
    log_file: Path,
    *,
    dry_run: bool = False,
) -> None:
    """Run Liquibase Update on Changelog."""
    logger = get_run_logger()

    plb = Pyliquibase(
        defaultsFile=str(defaults_file),
        jdbcDriversDir=DRIVER_PATH,
        version=LIQUIBASE_VERSION,
    )

    # copy Neo4j extension JAR to Liquibase's lib folder
    ext_jar = Path(DRIVER_PATH) / DRIVER_JAR
    dest_lib = Path(plb.liquibase_lib_dir)
    shutil.copy(ext_jar, dest_lib)
    logger.info("Copied Neo4j extension JAR from %s to %s", ext_jar, dest_lib)

    out_capture = io.StringIO()
    err_capture = io.StringIO()
    try:
        with redirect_stdout(out_capture), redirect_stderr(err_capture):
            if dry_run:
                logger.info("Running updateSQL (dry run)...")
                plb.updateSQL()
            else:
                logger.info("Running update...")
                plb.update()
    finally:
        for line in out_capture.getvalue().splitlines():
            if not line.strip():
                continue
            logger.info(line)
        for line in err_capture.getvalue().splitlines():
            if not line.strip():
                continue
            logger.error(line)
        if log_file.exists():
            logger.info("Reading Liquibase logs from %s", log_file)
            try:
                with log_file.open("r") as f:
                    for line in f:
                        strip_line = line.strip()
                        if not strip_line:
                            continue
                        if "ERROR" in strip_line or "SEVERE" in strip_line:
                            logger.error(strip_line)
                        elif "WARNING" in strip_line:
                            logger.warning(strip_line)
                        else:
                            logger.info(strip_line)
            except Exception:
                logger.exception("Error reading Liquibase logs from %s", log_file)


@flow(name="liquibase-update", log_prints=True)
def liquibase_update_flow(
    changelog_file: str,
    mdb_id: str,
    log_level: str = "info",
    *,
    dry_run: bool = False,
) -> None:
    """Run Liquibase Update on Changelog."""
    logger = get_run_logger()
    # configure jvm
    import jnius_config

    jnius_config.add_options(f"-Xms{JVM_HEAP_MIN}", f"-Xmx{JVM_HEAP_MAX}")

    # set up pyliquibase logger use prefect api log handler
    plb_logger = logging.getLogger("pyliquibase")
    plb_logger.setLevel(VALID_LOG_LEVELS[log_level])
    if not any(isinstance(h, APILogHandler) for h in plb_logger.handlers):
        plb_logger.addHandler(APILogHandler())

    defaults_file, log_file = set_defaults_file(
        changelog_file,
        mdb_id,
        log_level,
    )
    # print out the contents of the defaults file
    raw = Path(defaults_file).read_text().splitlines()  # type:ignore reportArgumentType
    for line in raw:
        if line.lower().startswith("password"):
            logger.info("password: ********")
        else:
            logger.info(line)
    logger.info("Changelog file: %s", Path(changelog_file).resolve())

    try:
        run_liquibase_update(defaults_file, log_file, dry_run=dry_run)
    finally:
        defaults_file.unlink(missing_ok=True)  # type:ignore reportAttributeAccessIssue
        if log_file.exists():
            try:
                log_file.unlink(missing_ok=True)  # type:ignore reportAttributeAccessIssue
            except Exception:
                logger.exception("Error deleting log file %s", log_file)

    logger.info("Liquibase finished.")
