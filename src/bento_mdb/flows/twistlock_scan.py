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

# NCI Console: POST /api/v1/registry/scan/select?collections=...&project=... + registry-only tag array.
DEFAULT_SCAN_SELECT_COLLECTIONS = "CRDC CCDI All Collection"
DEFAULT_SCAN_SELECT_PROJECT = "Central Console"
# scan/select can block until the registry defender finishes; allow long waits (urllib timeout seconds).
SCAN_SELECT_HTTP_TIMEOUT_SECONDS = 30 * 60


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
    body: dict | list | None = None,
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
    """POST /registry/scan — enqueue on-demand registry image scan (Twistlock-side queue)."""
    url = f"{_registry_api_base(address, api_version)}/registry/scan"
    body = {"onDemandScan": True, "tag": {"registry": registry, "repo": repo, "tag": tag, "digest": ""}}
    _http_json_request("POST", url, token=token, body=body, timeout=240)


def _notify_registry_scan_defenders(
    *,
    address: str,
    api_version: str,
    token: str,
    registry: str,
) -> None:
    """POST ``/api/v1/registry/scan/select`` with collections/project query + tag array (NCI Console).

    Body is always ``[{"tag": {"registry": <host>, "repo": "", "tag": ""}}]``.
    Optional Secrets ``twistlock-scan-select-collections`` / ``twistlock-scan-select-project``
    override collection/project query defaults.
    """
    _ = api_version  # NCI scan/select is fixed ``/api/v1/``; ``api_version`` is used for other API calls.
    collections = _optional_secret_block("twistlock-scan-select-collections") or DEFAULT_SCAN_SELECT_COLLECTIONS
    project = _optional_secret_block("twistlock-scan-select-project") or DEFAULT_SCAN_SELECT_PROJECT

    q = urllib.parse.urlencode(
        {"collections": collections, "project": project},
        quote_via=urllib.parse.quote_plus,
    )
    url = f"{address.rstrip('/')}/api/v1/registry/scan/select?{q}"
    body = [{"tag": {"registry": registry, "repo": "", "tag": ""}}]
    _http_json_request(
        "POST", url, token=token, body=body, timeout=SCAN_SELECT_HTTP_TIMEOUT_SECONDS
    )


def try_fetch_registry_compact_result(
    *,
    address: str,
    api_version: str,
    token: str,
    image_ref: str,
) -> dict | None:
    """Return compact registry row for ``image_ref``, or None if Twistlock has no row yet."""
    query = urllib.parse.urlencode({"name": image_ref, "compact": "true"})
    url = f"{_registry_api_base(address, api_version)}/registry?{query}"
    resp = _http_json_request("GET", url, token=token, timeout=120)
    if isinstance(resp, list):
        if not resp:
            return None
        first = resp[0]
        return first if isinstance(first, dict) else None
    if isinstance(resp, dict):
        return resp
    return None


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
    notify_registry_defenders: bool = True,
    poll_timeout_seconds: int = 1800,
    poll_interval_seconds: int = 15,
) -> None:
    """ECR image scan via Twistlock Console Registry API (no Docker on Prefect worker).

    Pipeline:

    #. ``POST /api/<ver>/authenticate`` → bearer token
    #. ``POST /api/<ver>/registry/scan`` — submit **on-demand** scan for ``registry/repo:tag`` (Twistlock queue)
    #. Optional ``POST /api/<ver>/registry/scan/select`` — ping registry scanner defenders
    #. ``GET /api/<ver>/registry/progress`` — poll until scan finishes
    #. ``GET /api/<ver>/registry?name=<image_ref>&compact=true`` — fetch result and enforce critical/high policy

    Secrets (Prefect blocks): ``twistlock-username``, ``twistlock-password``;
    optional ``twistlock-address``, ``twistlock-api-version``.

    ``POST /api/v1/registry/scan/select``: NCI collections/project defaults + tag payload with ``repo``/``tag`` ``""``;
    Secrets ``twistlock-scan-select-collections`` / ``twistlock-scan-select-project`` override query defaults.
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

    existing = try_fetch_registry_compact_result(
        address=address, api_version=api_version, token=token, image_ref=image_ref
    )
    if existing:
        logger.info(
            "Twistlock registry already has a row for this image (compact lookup succeeded). "
            "Snippet: %s",
            json.dumps(existing)[:800],
        )
    else:
        logger.info(
            "No compact registry row yet for %r (Twistlock may not have indexed this tag). "
            "Proceeding with on-demand scan.",
            image_ref,
        )

    logger.info("step 2: POST registry/scan (enqueue on-demand ECR scan in Twistlock)…")
    _start_on_demand_registry_scan(
        address=address,
        api_version=api_version,
        token=token,
        registry=registry,
        repo=repo,
        tag=tag,
    )
    logger.info("on-demand scan request accepted")

    if notify_registry_defenders:
        logger.info("step 2b: POST registry/scan/select (notify registry scanner defenders)…")
        try:
            _notify_registry_scan_defenders(
                address=address,
                api_version=api_version,
                token=token,
                registry=registry,
            )
            logger.info("registry scan/select completed")
        except RuntimeError as e:
            logger.warning("registry/scan/select failed (continuing with progress poll): %s", e)

    logger.info("step 3: GET registry/progress (poll Twistlock scan queue until done)…")
    _poll_registry_scan_progress(
        address=address,
        api_version=api_version,
        token=token,
        repo=repo,
        tag=tag,
        logger=logger,
        timeout_seconds=poll_timeout_seconds,
        interval_seconds=poll_interval_seconds,
    )

    logger.info("step 4: GET registry (compact result via API)…")
    result = _fetch_registry_compact_result(
        address=address,
        api_version=api_version,
        token=token,
        image_ref=image_ref,
    )
    logger.info("evaluating scan output against policy…")
    _evaluate_registry_scan_result(result)
    logger.info("Twistlock registry scan passed (no critical/high).")


@flow(name="twistlock-registry-verify", log_prints=True)
def verify_twistlock_registry_image_flow(
    image_ref: str,
    *,
    twistlock_address: str | None = None,
    fail_if_not_found: bool = False,
) -> dict:
    """Check whether Twistlock already has a compact registry row for ``image_ref`` (no scan).

    Returns ``{"found": bool, "image_ref": str, "row": dict | None}``.

    Prefect Secrets: ``twistlock-username``, ``twistlock-password``; optional
    ``twistlock-address``, ``twistlock-api-version``.
    """
    logger = get_run_logger()
    image_ref = image_ref.strip()
    if not image_ref:
        raise RuntimeError("image_ref is empty.")

    twistlock_addr_secret = _optional_secret_block("twistlock-address")
    address = twistlock_address or twistlock_addr_secret or DEFAULT_TWISTLOCK_ADDRESS
    api_version = _optional_secret_block("twistlock-api-version") or DEFAULT_COMPUTE_API_VERSION
    logger.info("verify: address=%r api_version=%r image_ref=%r", address, api_version, image_ref)

    _split_image_ref(image_ref)

    username = _require_secret_block("twistlock-username")
    password = _require_secret_block("twistlock-password")
    token = _authenticate(address, username, password)

    row = try_fetch_registry_compact_result(
        address=address, api_version=api_version, token=token, image_ref=image_ref
    )
    if row:
        logger.info("FOUND: registry row exists for this image.")
        out: dict = {"found": True, "image_ref": image_ref, "row": row}
    else:
        logger.info("NOT FOUND: no compact registry row for this name.")
        out = {"found": False, "image_ref": image_ref, "row": None}
        if fail_if_not_found:
            raise RuntimeError(
                f"No Twistlock registry row for {image_ref!r}. "
                "Check name string vs Console UI, API version, or wait for scan to index."
            )
    return out
