"""Twistlock (Prisma Cloud Compute) registry scan via Console API."""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from prefect import flow, get_run_logger
from prefect.blocks.system import Secret

DEFAULT_TWISTLOCK_ADDRESS = "https://twistlock.nci.nih.gov"
DEFAULT_COMPUTE_API_VERSION = "v34.02"


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


def _http_json_request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: int = 120,
) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, context=_UNSAFE_TLS, timeout=timeout) as resp:
            text = resp.read().decode()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        msg = f"HTTP {e.code} from {url}: {err_body}"
        raise RuntimeError(msg) from e
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Non-JSON response from {url}: {text[:500]!r}") from e


def _authenticate(address: str, username: str, password: str) -> str:
    url = f"{address.rstrip('/')}/api/v1/authenticate"
    auth_json = _http_json_request("POST", url, body={"username": username, "password": password})
    if not isinstance(auth_json, dict):
        raise RuntimeError(f"Unexpected auth response type: {type(auth_json).__name__}")
    token = auth_json.get("token")
    if not token:
        raise RuntimeError(f"Twistlock authentication failed: {auth_json!r}")
    return str(token)


def _split_image_ref(image_ref: str) -> tuple[str, str, str]:
    """Parse full image ref into (registry, repo, tag)."""
    image_ref = image_ref.strip()
    if not image_ref:
        raise RuntimeError("image_ref is empty.")
    m = re.match(r"^(?P<registry>[^/]+)/(?P<repo>.+):(?P<tag>[^:@]+)$", image_ref)
    if not m:
        raise RuntimeError(
            "image_ref must be in '<registry>/<repo>:<tag>' form for registry API scans. "
            f"Got: {image_ref!r}"
        )
    return m.group("registry"), m.group("repo"), m.group("tag")


def _registry_api_base(address: str, api_version: str) -> str:
    return f"{address.rstrip('/')}/api/{api_version.strip('/')}"


def _start_on_demand_registry_scan(
    *,
    address: str,
    api_version: str,
    token: str,
    registry: str,
    repo: str,
    tag: str,
) -> None:
    url = f"{_registry_api_base(address, api_version)}/registry/scan"
    body = {"onDemandScan": True, "tag": {"registry": registry, "repo": repo, "tag": tag, "digest": ""}}
    _http_json_request("POST", url, token=token, body=body, timeout=120)


def _poll_registry_scan_progress(
    *,
    address: str,
    api_version: str,
    token: str,
    repo: str,
    tag: str,
    logger,
    timeout_seconds: int = 900,
    interval_seconds: int = 15,
) -> None:
    started = time.time()
    query = urllib.parse.urlencode({"onDemand": "true", "repo": repo, "tag": tag})
    url = f"{_registry_api_base(address, api_version)}/registry/progress?{query}"
    seen_non_empty = False
    polls = 0
    empty_polls = 0
    max_initial_empty_polls = 8
    while True:
        polls += 1
        if time.time() - started > timeout_seconds:
            raise RuntimeError(f"Timed out waiting for registry scan progress after {timeout_seconds}s.")
        resp = _http_json_request("GET", url, token=token, timeout=60)
        if isinstance(resp, list) and resp:
            seen_non_empty = True
            empty_polls = 0
            ongoing = any(bool(item.get("isScanOngoing")) for item in resp if isinstance(item, dict))
            if polls == 1 or polls % 4 == 0:
                logger.info("registry progress poll #%s: %s", polls, json.dumps(resp)[:600])
            if not ongoing:
                return
        elif seen_non_empty:
            # API may return [] right after completion for prior on-demand scans.
            return
        else:
            empty_polls += 1
            if polls == 1 or polls % 4 == 0:
                logger.info("registry progress poll #%s returned empty list", polls)
            if empty_polls >= max_initial_empty_polls:
                raise RuntimeError(
                    "Registry progress endpoint kept returning empty results for this on-demand scan. "
                    "This usually means the image is outside configured registry scan scope, repo/tag parsing "
                    "does not match Console expectations, or API version is mismatched for this Console."
                )
        time.sleep(interval_seconds)


def _fetch_registry_compact_result(
    *,
    address: str,
    api_version: str,
    token: str,
    image_ref: str,
) -> dict:
    query = urllib.parse.urlencode({"name": image_ref, "compact": "true"})
    url = f"{_registry_api_base(address, api_version)}/registry?{query}"
    resp = _http_json_request("GET", url, token=token, timeout=120)
    if isinstance(resp, list):
        if not resp:
            raise RuntimeError(f"No registry scan result found for image {image_ref!r}.")
        first = resp[0]
        if not isinstance(first, dict):
            raise RuntimeError(f"Unexpected registry result item type: {type(first).__name__}")
        return first
    if isinstance(resp, dict):
        return resp
    raise RuntimeError(f"Unexpected registry result type: {type(resp).__name__}")


def _find_critical_high_counts(data: object) -> tuple[int, int] | None:
    if isinstance(data, dict):
        crit = data.get("critical")
        high = data.get("high")
        if isinstance(crit, int) and isinstance(high, int):
            return crit, high
        for val in data.values():
            found = _find_critical_high_counts(val)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_critical_high_counts(item)
            if found is not None:
                return found
    return None


def _evaluate_registry_scan_result(result: dict) -> None:
    counts = _find_critical_high_counts(result)
    if counts is None:
        raise RuntimeError(
            "Could not find critical/high counts in registry scan response. "
            f"Response (truncated): {json.dumps(result)[:1200]}"
        )
    critical, high = counts
    if critical > 0 or high > 0:
        raise RuntimeError(f"Scan policy: failing on critical={critical} high={high}")


@flow(name="twistlock-scan", log_prints=True)
def twistlock_scan_flow(
    image_ref: str,
    *,
    twistlock_address: str | None = None,
    twistcli_skip_download: bool = False,
    twistcli_install_dir: str | None = None,
) -> None:
    """Scan a registry image through Prisma Cloud Compute Console API.

    End-to-end: (1) authenticate, (2) trigger on-demand registry scan,
    (3) poll progress, (4) fetch compact result, (5) fail on critical/high > 0.

    Credentials must come from Prefect Secret blocks ``twistlock-username`` and
    ``twistlock-password``. Optional ``twistlock-address`` and ``twistlock-api-version``.
    """
    logger = get_run_logger()
    logger.info(
        "twistlock_scan_flow starting (image_ref=%r twistcli_skip_download=%s twistcli_install_dir=%r)",
        image_ref,
        twistcli_skip_download,
        twistcli_install_dir,
    )
    if twistcli_skip_download or twistcli_install_dir:
        logger.warning("twistcli_* parameters are ignored in registry API mode.")

    twistlock_addr_secret = _optional_secret_block("twistlock-address")
    address = twistlock_address or twistlock_addr_secret or DEFAULT_TWISTLOCK_ADDRESS
    api_version = _optional_secret_block("twistlock-api-version") or DEFAULT_COMPUTE_API_VERSION
    logger.info("using Twistlock address=%r api_version=%r", address, api_version)

    username = _require_secret_block("twistlock-username")
    password = _require_secret_block("twistlock-password")
    logger.info("loaded twistlock-username and twistlock-password from Prefect Secret blocks")

    logger.info("authenticating to Twistlock console…")
    token = _authenticate(address, username, password)
    logger.info("Twistlock authentication succeeded")

    registry, repo, tag = _split_image_ref(image_ref)
    logger.info("parsed image_ref registry=%s repo=%s tag=%s", registry, repo, tag)

    logger.info("starting on-demand registry scan…")
    _start_on_demand_registry_scan(
        address=address,
        api_version=api_version,
        token=token,
        registry=registry,
        repo=repo,
        tag=tag,
    )
    logger.info("scan request submitted; polling progress…")
    _poll_registry_scan_progress(
        address=address,
        api_version=api_version,
        token=token,
        repo=repo,
        tag=tag,
        logger=logger,
    )

    logger.info("fetching compact registry scan result…")
    result = _fetch_registry_compact_result(
        address=address,
        api_version=api_version,
        token=token,
        image_ref=image_ref,
    )
    logger.info("evaluating scan output against policy…")
    _evaluate_registry_scan_result(result)
    logger.info("Twistlock registry scan passed (no critical/high).")
