"""Twistlock (Prisma Cloud Compute) image scan — run on VPN-capable workers."""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from prefect import flow, get_run_logger

DEFAULT_TWISTLOCK_ADDRESS = "https://twistlock.nci.nih.gov"

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
        explicit = os.environ.get("TWISTCLI")
        if explicit:
            p = Path(explicit).expanduser().resolve()
            if p.is_file() and os.access(p, os.X_OK):
                return p, None
            raise RuntimeError(f"TWISTCLI is not an executable file: {p}")
        found = shutil.which("twistcli")
        if found:
            return Path(found), None
        raise RuntimeError("twistcli not found (set TWISTCLI or PATH, or clear twistcli_skip_download)")

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

    Set ``TWISTLOCK_USERNAME`` and ``TWISTLOCK_PASSWORD`` in the environment (e.g. on the Prefect worker).
    Optional: ``TWISTLOCK_ADDRESS`` (default ``https://twistlock.nci.nih.gov``), ``TWISTCLI`` when
    ``twistcli_skip_download`` is true.
    """
    logger = get_run_logger()
    address = twistlock_address or os.environ.get("TWISTLOCK_ADDRESS") or DEFAULT_TWISTLOCK_ADDRESS
    username = os.environ.get("TWISTLOCK_USERNAME")
    password = os.environ.get("TWISTLOCK_PASSWORD")
    if not username or not password:
        raise RuntimeError("TWISTLOCK_USERNAME and TWISTLOCK_PASSWORD must be set in the environment")

    token = _authenticate(address, username, password)
    logger.info("Twistlock authentication succeeded")

    twistcli, cleanup_dir = _resolve_twistcli_binary(
        twistcli_skip_download=twistcli_skip_download,
        twistcli_install_dir=twistcli_install_dir,
        address=address,
        token=token,
    )
    try:
        logger.info("Running twistcli scan for %s", image_ref)
        output = _run_twistcli_scan(twistcli, address, username, token, image_ref)
        print(output)
        _evaluate_scan_output(output)
        logger.info("Twistlock scan passed (no critical/high; threshold not FAIL).")
    finally:
        if cleanup_dir is not None and cleanup_dir.is_dir():
            shutil.rmtree(cleanup_dir, ignore_errors=True)
