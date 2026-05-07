"""Twistlock (Prisma Cloud Compute) image scan — run on VPN-capable workers."""

from __future__ import annotations

import json
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from prefect import flow, get_run_logger
from prefect.blocks.system import Secret

DEFAULT_TWISTLOCK_ADDRESS = "https://twistlock.nci.nih.gov"


def _require_secret_block(name: str) -> str:
    """Load a non-empty Prefect Secret block (by block name)."""
    try:
        val = Secret.load(name).get()  # type: ignore reportAttributeAccessIssue
    except Exception as e:
        msg = (
            f"Prefect Secret block {name!r} is missing or not readable in this workspace. "
            f"Create the Secret block with that exact name. ({e})"
        )
        raise RuntimeError(msg) from e
    if val is None or not str(val).strip():
        raise RuntimeError(f"Prefect Secret block {name!r} is empty.")
    return str(val).strip()


def _optional_secret_block(name: str) -> str | None:
    """Return Secret value or None if the block is missing or empty."""
    try:
        val = Secret.load(name).get()  # type: ignore reportAttributeAccessIssue
    except Exception:
        return None
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


_UNSAFE_TLS = ssl.create_default_context()
_UNSAFE_TLS.check_hostname = False
_UNSAFE_TLS.verify_mode = ssl.CERT_NONE


def _http_json_post(url: str, body: dict, *, timeout: int = 120) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, context=_UNSAFE_TLS, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        msg = f"HTTP {e.code} from {url}: {err_body}"
        raise RuntimeError(msg) from e


def _http_download(url: str, dest: Path, headers: dict[str, str], *, timeout: int = 600) -> None:
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, context=_UNSAFE_TLS, timeout=timeout) as resp:
        dest.write_bytes(resp.read())
    dest.chmod(0o755)


def _authenticate(address: str, username: str, password: str) -> str:
    url = f"{address.rstrip('/')}/api/v1/authenticate"
    auth_json = _http_json_post(url, {"username": username, "password": password})
    token = auth_json.get("token")
    if not token:
        raise RuntimeError(f"Twistlock authentication failed: {auth_json!r}")
    return str(token)


def _download_twistcli(address: str, token: str, dest: Path) -> None:
    url = f"{address.rstrip('/')}/api/v1/util/twistcli"
    _http_download(url, dest, {"Authorization": f"Bearer {token}"})
    if not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError("twistcli download returned an empty file; check token and /api/v1/util/twistcli access.")
    head = dest.read_bytes()[:512]
    if head.startswith((b"{", b"[")) or b"<html" in head[:256].lower():
        raise RuntimeError(
            "twistcli download returned non-binary body (auth or API error?): "
            + head[:200].decode(errors="replace")
        )
    # Linux worker: official twistcli is an ELF binary
    if not head.startswith(b"\x7fELF"):
        raise RuntimeError(
            "twistcli download does not look like a Linux ELF binary; use Linux Prefect workers."
        )


def _resolve_twistcli_binary(
    *,
    twistcli_skip_download: bool,
    twistcli_install_dir: str | None,
    address: str,
    token: str,
) -> tuple[Path, Path | None]:
    """Return (path to twistcli, temp dir to delete after run, or None)."""
    if twistcli_skip_download:
        found = shutil.which("twistcli")
        if found:
            return Path(found), None
        raise RuntimeError(
            "twistcli not found on PATH; install it on the worker or leave twistcli_skip_download false "
            "to download from the console API."
        )

    if twistcli_install_dir:
        install = Path(twistcli_install_dir).expanduser().resolve()
        install.mkdir(parents=True, exist_ok=True)
        dest = install / "twistcli"
        _download_twistcli(address, token, dest)
        return dest, None

    tmp = Path(tempfile.mkdtemp(prefix="twistlock-cli-"))
    dest = tmp / "twistcli"
    _download_twistcli(address, token, dest)
    return dest, tmp


def _run_twistcli_scan(
    twistcli: Path,
    address: str,
    username: str,
    token: str,
    image_ref: str,
) -> str:
    proc = subprocess.run(
        [
            str(twistcli),
            "images",
            "scan",
            "--address",
            address,
            "--user",
            username,
            "--token",
            token,
            "--details",
            image_ref,
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"twistcli exited {proc.returncode}\n{out}")
    return out


def _assert_local_docker_socket_ready() -> None:
    """Fail fast with actionable guidance when docker.sock is unavailable."""
    sock_path = Path("/var/run/docker.sock")
    if not sock_path.exists():
        raise RuntimeError(
            "Docker socket not found at /var/run/docker.sock. "
            "twistcli image scan requires local Docker daemon access. "
            "Run this flow on a VPN worker host that has Docker installed and exposes docker.sock "
            "(for ECS: EC2 launch type with host socket mount; not Fargate-only runtime)."
        )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(str(sock_path))
    except OSError as e:
        raise RuntimeError(
            "Cannot connect to /var/run/docker.sock. "
            "Ensure the flow container user has permission to access the Docker daemon."
        ) from e


def _evaluate_scan_output(output: str) -> None:
    summary = None
    for line in output.splitlines():
        if "Vulnerabilities found for image" in line:
            summary = line
    if not summary:
        raise RuntimeError(
            "Could not find vulnerability summary line (expected 'Vulnerabilities found for image …')."
        )
    crit_m = re.search(r"critical - (\d+)", summary)
    high_m = re.search(r"high - (\d+)", summary)
    if not crit_m or not high_m:
        raise RuntimeError(f"Could not parse critical/high from line: {summary!r}")
    crit, high = int(crit_m.group(1)), int(high_m.group(1))
    if crit > 0 or high > 0:
        raise RuntimeError(f"Scan policy: failing on critical={crit} high={high}")
    if re.search(r"Vulnerability threshold check results:\s*FAIL", output):
        raise RuntimeError("Vulnerability threshold check results: FAIL")


@flow(name="twistlock-scan", log_prints=True)
def twistlock_scan_flow(
    image_ref: str,
    *,
    twistlock_address: str | None = None,
    twistcli_skip_download: bool = False,
    twistcli_install_dir: str | None = None,
) -> None:
    """Scan a container image with Twistlock (Linux worker).

    End-to-end: (1) ``POST /api/v1/authenticate`` → token, (2) download Linux ``twistcli`` from
    ``GET /api/v1/util/twistcli`` with ``Authorization: Bearer``, (3) run
    ``twistcli images scan --address … --user … --token … --details <image_ref>``,
    (4) log combined stdout/stderr, (5) fail the flow if the summary line reports critical/high > 0
    or ``Vulnerability threshold check results: FAIL``.

    **Credentials must come from Prefect Secret blocks** named ``twistlock-username`` and
    ``twistlock-password``. Optional Secret ``twistlock-address``; otherwise use flow parameter
    ``twistlock_address``, then the default NCI console URL.
    With ``twistcli_skip_download``, the worker must already have ``twistcli`` on ``PATH`` (e.g. system install).
    Default is to download ``twistcli`` from the console after login (no PATH needed).
    """
    logger = get_run_logger()
    logger.info(
        "twistlock_scan_flow starting (image_ref=%r twistcli_skip_download=%s twistcli_install_dir=%r)",
        image_ref,
        twistcli_skip_download,
        twistcli_install_dir,
    )
    twistlock_addr_secret = _optional_secret_block("twistlock-address")
    address = twistlock_address or twistlock_addr_secret or DEFAULT_TWISTLOCK_ADDRESS
    if twistlock_address:
        _addr_src = "flow parameter"
    elif twistlock_addr_secret:
        _addr_src = "Prefect Secret twistlock-address"
    else:
        _addr_src = "default constant"
    logger.info("resolved twistlock console address=%r (source=%s)", address, _addr_src)

    username = _require_secret_block("twistlock-username")
    password = _require_secret_block("twistlock-password")
    logger.info("loaded twistlock-username and twistlock-password from Prefect Secret blocks")

    logger.info("authenticating to Twistlock console…")
    token = _authenticate(address, username, password)
    logger.info("Twistlock authentication succeeded")

    logger.info("resolving twistcli binary (download=%s)…", not twistcli_skip_download)
    twistcli, cleanup_dir = _resolve_twistcli_binary(
        twistcli_skip_download=twistcli_skip_download,
        twistcli_install_dir=twistcli_install_dir,
        address=address,
        token=token,
    )
    logger.info("using twistcli at %s", twistcli)
    try:
        logger.info("checking Docker daemon socket before scan…")
        _assert_local_docker_socket_ready()
        logger.info("running twistcli scan for %s", image_ref)
        output = _run_twistcli_scan(twistcli, address, username, token, image_ref)
        logger.info("twistcli finished; output length=%s chars", len(output))
        print(output)
        logger.info("evaluating scan output against policy…")
        _evaluate_scan_output(output)
        logger.info("Twistlock scan passed (no critical/high; threshold not FAIL).")
    finally:
        if cleanup_dir is not None and cleanup_dir.is_dir():
            shutil.rmtree(cleanup_dir, ignore_errors=True)
