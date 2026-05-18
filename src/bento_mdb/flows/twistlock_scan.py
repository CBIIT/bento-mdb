"""Twistlock (Prisma Cloud Compute) registry scan via Console API."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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
# scan/select can block until registry scanner selection finishes; allow long waits (urllib timeout seconds).
SCAN_SELECT_HTTP_TIMEOUT_SECONDS = 30 * 60

CVE_ID_PATTERN = re.compile(r"(CVE-\d{4}-\d+)", re.IGNORECASE)
_REGISTRY_DETAIL_HTTP_TIMEOUT_SECONDS = 300
_SEVERITY_SORT_KEY = {
    "critical": 0,
    "high": 1,
    "important": 1,
    "medium": 2,
    "moderate": 2,
    "low": 3,
    "informational": 4,
    "negligible": 5,
    "unknown": 9,
}


@dataclass(frozen=True)
class ImageRef:
    value: str
    registry: str
    repo: str
    tag: str

    @classmethod
    def parse(cls, image_ref: str) -> "ImageRef":
        value = image_ref.strip()
        if not value:
            raise RuntimeError("image_ref is empty.")
        m = re.match(r"^(?P<registry>[^/]+)/(?P<repo>.+):(?P<tag>[^:@]+)$", value)
        if not m:
            raise RuntimeError(
                "image_ref must be in '<registry>/<repo>:<tag>' form for registry API scans. "
                f"Got: {image_ref!r}"
            )
        return cls(
            value=value,
            registry=m.group("registry"),
            repo=m.group("repo"),
            tag=m.group("tag"),
        )

    def __str__(self) -> str:
        return self.value


class PrefectTwistlockSettingsLoader:
    """Loads Twistlock runtime configuration from Prefect Secret blocks."""

    def get_secret(self, name: str) -> str | None:
        try:
            val = Secret.load(name).get()  # type: ignore reportAttributeAccessIssue
        except Exception:
            return None
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None


@dataclass(frozen=True)
class TwistlockSettings:
    address: str
    api_version: str
    username: str
    password: str
    scan_select_collections: str = DEFAULT_SCAN_SELECT_COLLECTIONS
    scan_select_project: str = DEFAULT_SCAN_SELECT_PROJECT

    @classmethod
    def from_prefect(
        cls,
        loader: PrefectTwistlockSettingsLoader,
        *,
        address_override: str | None = None,
    ) -> "TwistlockSettings":
        return cls(
            address=(
                _clean_optional(address_override)
                or loader.get_secret("twistlock-address")
                or DEFAULT_TWISTLOCK_ADDRESS
            ),
            api_version=loader.get_secret("twistlock-api-version") or DEFAULT_COMPUTE_API_VERSION,
            username=_required_secret(loader, "twistlock-username"),
            password=_required_secret(loader, "twistlock-password"),
            scan_select_collections=(
                loader.get_secret("twistlock-scan-select-collections")
                or DEFAULT_SCAN_SELECT_COLLECTIONS
            ),
            scan_select_project=(
                loader.get_secret("twistlock-scan-select-project") or DEFAULT_SCAN_SELECT_PROJECT
            ),
        )


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s if s else None


def _required_secret(loader: PrefectTwistlockSettingsLoader, name: str) -> str:
    val = loader.get_secret(name)
    if val is None:
        raise RuntimeError(
            f"Secret {name!r} is missing, empty, or not readable. "
            "Create the secret with that exact name."
        )
    return val


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


def _registry_api_base(address: str, api_version: str) -> str:
    return f"{address.rstrip('/')}/api/{api_version.strip('/')}"


def _clip_cell(s: str, width: int) -> str:
    s = (s or "").replace("\n", " ").replace("\t", " ")
    return s if len(s) <= width else s[: width - 1] + "…"


def _format_vuln_timestamp(val: object) -> str:
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        ts = float(val) / 1000.0 if val > 1e12 else float(val)
        try:
            return time.strftime("%Y-%m-%d", time.gmtime(ts))
        except (OverflowError, OSError, ValueError):
            return str(int(val))[:16]
    if isinstance(val, str):
        v = val.strip()
        if len(v) >= 10 and v[4] == "-" and v[7] == "-":
            return v[:10]
        return _clip_cell(v, 32)
    return _clip_cell(str(val), 32)


def _cde_like_id_from_dict(d: dict) -> str:
    for key in ("cdePublicId", "cdeId", "cde", "caDSRPublicId", "caDSR"):
        v = d.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _severity_display(raw: object) -> str:
    if raw is None:
        return "—"
    s = str(raw).strip()
    if not s:
        return "—"
    low = s.lower()
    return low.capitalize() if low in _SEVERITY_SORT_KEY else s[:24]


def _parse_vuln_record(d: dict) -> dict[str, str] | None:
    cve: str | None = None
    for key in ("cve", "cveId", "cveID"):
        v = d.get(key)
        if isinstance(v, str):
            m = CVE_ID_PATTERN.search(v)
            if m:
                cve = m.group(1).upper()
                break
    if not cve:
        return None
    sev_raw = d.get("severity") or d.get("risk") or d.get("cvssSeverity") or d.get("impact")
    date_raw = None
    for dk in ("discovered", "detected", "firstSeen", "modified", "time", "creationTime", "discoveredTime"):
        if dk in d and d[dk] is not None:
            date_raw = d[dk]
            break
    pkg = d.get("packageName") or d.get("package") or d.get("fullPackageName") or ""
    if isinstance(pkg, str):
        pkg_s = pkg.strip()
    else:
        pkg_s = str(pkg) if pkg else ""
    return {
        "cve": cve,
        "cde_id": _cde_like_id_from_dict(d),
        "severity": _severity_display(sev_raw),
        "severity_key": str(sev_raw).strip().lower() if sev_raw is not None else "unknown",
        "date": _format_vuln_timestamp(date_raw) if date_raw is not None else "—",
        "package": pkg_s,
    }


def _collect_vulnerability_rows(payload: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_ids: set[int] = set()

    def walk(o: object) -> None:
        if isinstance(o, dict):
            oid = id(o)
            if oid in seen_ids:
                return
            seen_ids.add(oid)
            parsed = _parse_vuln_record(o)
            if parsed:
                rows.append(parsed)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(payload)
    dedup: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for r in rows:
        key = (r["cve"], r["package"], r.get("severity_key", ""), r["date"])
        dedup[key] = r
    out = list(dedup.values())

    def sort_key(r: dict[str, str]) -> tuple[int, str]:
        sk = _SEVERITY_SORT_KEY.get(r.get("severity_key", ""), 9)
        return sk, r["cve"]

    out.sort(key=sort_key)
    return out


def _log_twistlock_vulnerability_report(
    logger,
    payload: object,
    *,
    microservice_name: str,
    image_ref: str,
) -> None:
    """Emit a fixed-width table to Prefect logs (CVE + optional CDE-style ids when present in JSON)."""
    rows = _collect_vulnerability_rows(payload)
    logger.info(
        "Twistlock vulnerability report — image_ref=%r microservice=%r parsed_cve_rows=%s",
        image_ref,
        microservice_name,
        len(rows),
    )
    widths = (22, 18, 14, 10, 16, 28)
    headers = (
        "Microservice",
        "CVE identifier",
        "CDE ID",
        "Severity",
        "Date identified",
        "Package",
    )
    header_line = " | ".join(_clip_cell(h, w) for h, w in zip(headers, widths))
    logger.info(header_line)
    logger.info("-" * min(120, max(len(header_line), 80)))
    for rec in rows:
        line = " | ".join(
            _clip_cell(x, w)
            for x, w in zip(
                (
                    microservice_name,
                    rec["cve"],
                    rec["cde_id"] or "—",
                    rec["severity"],
                    rec["date"],
                    rec["package"] or "—",
                ),
                widths,
            )
        )
        logger.info(line)
    if not rows:
        snippet = json.dumps(payload, default=str)[:900]
        logger.info(
            "No CVE-sized records parsed from registry JSON for table view "
            "(structure may differ by Console version). Payload snippet: %s",
            snippet,
        )


def _microservice_report_label(image_ref: str, override: str | None) -> str:
    if override and override.strip():
        return override.strip()
    return ImageRef.parse(image_ref).repo


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


class TwistlockRegistryClient(ABC):
    """Boundary for Twistlock Registry API operations used by scan use cases."""

    @abstractmethod
    def authenticate(self) -> str:
        """Return an authenticated bearer token."""

    @abstractmethod
    def start_scan(self, token: str, image_ref: ImageRef) -> None:
        """Enqueue an on-demand registry scan."""

    @abstractmethod
    def trigger_scan_select(self, token: str, registry: str) -> None:
        """Trigger optional scan/select; this is a registry-level nudge, not the image scan."""

    @abstractmethod
    def registry_result(self, token: str, image_ref: ImageRef, *, compact: bool) -> dict | list:
        """Fetch compact or detailed registry result payload."""

    @abstractmethod
    def registry_progress(self, token: str, image_ref: ImageRef) -> dict | list:
        """Fetch registry scan progress."""


class HttpTwistlockRegistryClient(TwistlockRegistryClient):
    """urllib-backed Twistlock Registry API adapter."""

    def __init__(self, settings: TwistlockSettings):
        self.settings = settings

    def authenticate(self) -> str:
        url = f"{self.settings.address.rstrip('/')}/api/v1/authenticate"
        auth_json = _http_json_request(
            "POST",
            url,
            body={"username": self.settings.username, "password": self.settings.password},
        )
        if not isinstance(auth_json, dict):
            raise RuntimeError(f"Unexpected auth response type: {type(auth_json).__name__}")
        token = auth_json.get("token")
        if not token:
            raise RuntimeError(f"Twistlock authentication failed: {auth_json!r}")
        return str(token)

    def start_scan(self, token: str, image_ref: ImageRef) -> None:
        url = f"{_registry_api_base(self.settings.address, self.settings.api_version)}/registry/scan"
        body = {
            "onDemandScan": True,
            "tag": {
                "registry": image_ref.registry,
                "repo": image_ref.repo,
                "tag": image_ref.tag,
                "digest": "",
            },
        }
        _http_json_request("POST", url, token=token, body=body, timeout=240)

    def trigger_scan_select(self, token: str, registry: str) -> None:
        q = urllib.parse.urlencode(
            {
                "collections": self.settings.scan_select_collections,
                "project": self.settings.scan_select_project,
            },
            quote_via=urllib.parse.quote_plus,
        )
        url = f"{self.settings.address.rstrip('/')}/api/v1/registry/scan/select?{q}"
        body = [{"tag": {"registry": registry, "repo": "", "tag": ""}}]
        _http_json_request(
            "POST",
            url,
            token=token,
            body=body,
            timeout=SCAN_SELECT_HTTP_TIMEOUT_SECONDS,
        )

    def registry_result(self, token: str, image_ref: ImageRef, *, compact: bool) -> dict | list:
        query = urllib.parse.urlencode(
            {"name": image_ref.value, "compact": "true" if compact else "false"}
        )
        url = f"{_registry_api_base(self.settings.address, self.settings.api_version)}/registry?{query}"
        timeout = 120 if compact else _REGISTRY_DETAIL_HTTP_TIMEOUT_SECONDS
        return _http_json_request("GET", url, token=token, timeout=timeout)

    def registry_progress(self, token: str, image_ref: ImageRef) -> dict | list:
        query = urllib.parse.urlencode(
            {"onDemand": "true", "repo": image_ref.repo, "tag": image_ref.tag}
        )
        url = (
            f"{_registry_api_base(self.settings.address, self.settings.api_version)}"
            f"/registry/progress?{query}"
        )
        return _http_json_request("GET", url, token=token, timeout=60)


class TwistlockRegistryScanService:
    """Application service for the registry scan use case."""

    def __init__(self, client: TwistlockRegistryClient, logger):
        self.client = client
        self.logger = logger

    def scan(
        self,
        image_ref: ImageRef,
        *,
        microservice_report_name: str | None,
        trigger_registry_scan_select: bool,
        poll_timeout_seconds: int,
        poll_interval_seconds: int,
    ) -> None:
        token = self.client.authenticate()
        self.logger.info("Twistlock authentication succeeded")
        self.logger.info(
            "parsed image_ref registry=%s repo=%s tag=%s",
            image_ref.registry,
            image_ref.repo,
            image_ref.tag,
        )

        existing = self._compact_result(token, image_ref, required=False)
        if existing:
            self.logger.info(
                "Twistlock registry already has a row for this image (compact lookup succeeded). "
                "Snippet: %s",
                json.dumps(existing)[:800],
            )
        else:
            self.logger.info(
                "No compact registry row yet for %r (Twistlock may not have indexed this tag). "
                "Proceeding with on-demand scan.",
                image_ref.value,
            )

        self.logger.info("step 2: POST registry/scan (enqueue on-demand ECR scan in Twistlock)...")
        self.client.start_scan(token, image_ref)
        self.logger.info("on-demand scan request accepted")

        # Optional extra nudge for consoles where registry scanners do not pick up ECR changes promptly.
        if trigger_registry_scan_select:
            self.logger.info("step 2b: POST registry/scan/select (optional registry scan-select helper)...")
            try:
                self.client.trigger_scan_select(token, image_ref.registry)
                self.logger.info("registry scan/select completed")
            except RuntimeError as e:
                self.logger.warning("registry/scan/select failed (continuing with progress poll): %s", e)

        self.logger.info(
            "step 3: wait for scan (registry/progress + compact fallback when no prior row)... "
            "had_compact_before_enqueue=%s",
            existing is not None,
        )
        self._wait_until_ready(
            token,
            image_ref,
            timeout_seconds=poll_timeout_seconds,
            interval_seconds=poll_interval_seconds,
            use_compact_row_completion=(existing is None),
        )

        self.logger.info("step 4: GET registry (compact result via API)...")
        result = self._compact_result(token, image_ref, required=True)
        ms_label = _microservice_report_label(image_ref.value, microservice_report_name)
        self.logger.info("step 4b: vulnerability report (prefer non-compact registry payload for CVE rows)...")
        try:
            detailed = self.client.registry_result(token, image_ref, compact=False)
        except RuntimeError as e:
            self.logger.warning(
                "non-compact registry GET failed (%s); logging CVE table from compact payload only.", e
            )
            detailed = result
        _log_twistlock_vulnerability_report(
            self.logger,
            detailed,
            microservice_name=ms_label,
            image_ref=image_ref.value,
        )
        self.logger.info("evaluating scan output against policy...")
        _evaluate_registry_scan_result(result)
        self.logger.info("Twistlock registry scan passed (no critical/high).")

    def verify(self, image_ref: ImageRef, *, fail_if_not_found: bool) -> dict:
        token = self.client.authenticate()
        row = self._compact_result(token, image_ref, required=False)
        if row:
            self.logger.info("FOUND: registry row exists for this image.")
            return {"found": True, "image_ref": image_ref.value, "row": row}
        self.logger.info("NOT FOUND: no compact registry row for this name.")
        out = {"found": False, "image_ref": image_ref.value, "row": None}
        if fail_if_not_found:
            raise RuntimeError(
                f"No Twistlock registry row for {image_ref.value!r}. "
                "Check name string vs Console UI, API version, or wait for scan to index."
            )
        return out

    def _compact_result(
        self,
        token: str,
        image_ref: ImageRef,
        *,
        required: bool,
    ) -> dict | None:
        resp = self.client.registry_result(token, image_ref, compact=True)
        if isinstance(resp, list):
            if not resp:
                if required:
                    raise RuntimeError(f"No registry scan result found for image {image_ref.value!r}.")
                return None
            first = resp[0]
            if not isinstance(first, dict):
                raise RuntimeError(f"Unexpected registry result item type: {type(first).__name__}")
            return first
        if isinstance(resp, dict):
            return resp
        raise RuntimeError(f"Unexpected registry result type: {type(resp).__name__}")

    def _wait_until_ready(
        self,
        token: str,
        image_ref: ImageRef,
        *,
        timeout_seconds: int,
        interval_seconds: int,
        use_compact_row_completion: bool,
    ) -> None:
        started = time.time()
        seen_nonempty_progress = False
        polls = 0
        empty_streak = 0
        warned_empty_progress = False

        while True:
            if time.time() - started > timeout_seconds:
                raise RuntimeError(
                    f"Timed out waiting for registry scan after {timeout_seconds}s "
                    f"(no compact row and no usable progress). image_ref={image_ref.value!r}"
                )

            # Some registry scans never expose progress; a new compact row means the image is indexed.
            if use_compact_row_completion:
                row = self._compact_result(token, image_ref, required=False)
                if row:
                    self.logger.info(
                        "registry compact row present (scan/index ready); snippet: %s",
                        json.dumps(row)[:500],
                    )
                    return

            polls += 1
            resp = self.client.registry_progress(token, image_ref)
            if isinstance(resp, list) and resp:
                seen_nonempty_progress = True
                empty_streak = 0
                ongoing = any(bool(item.get("isScanOngoing")) for item in resp if isinstance(item, dict))
                if polls == 1 or polls % 4 == 0:
                    self.logger.info("registry progress poll #%s: %s", polls, json.dumps(resp)[:600])
                if not ongoing:
                    self.logger.info("registry progress reports no ongoing scan")
                    return
            elif seen_nonempty_progress:
                self.logger.info("registry progress returned empty after prior non-empty (assuming complete)")
                return
            else:
                empty_streak += 1
                if polls == 1 or polls % 4 == 0:
                    self.logger.info(
                        "registry progress poll #%s returned empty list (compact fallback %s)",
                        polls,
                        "on" if use_compact_row_completion else "off - row existed before enqueue",
                    )
                if empty_streak >= 8 and not warned_empty_progress:
                    warned_empty_progress = True
                    self.logger.warning(
                        "registry/progress still empty after %s polls; continuing until timeout (%s).",
                        empty_streak,
                        "polling compact registry for a new row"
                        if use_compact_row_completion
                        else "waiting on progress only",
                    )

            time.sleep(interval_seconds)


@flow(name="twistlock-scan", log_prints=True)
def twistlock_scan_flow(
    image_ref: str,
    *,
    twistlock_address: str | None = None,
    twistcli_skip_download: bool = False,
    twistcli_install_dir: str | None = None,
    microservice_report_name: str | None = None,
    # Optional registry-level nudge; the primary image scan is always start_scan().
    trigger_registry_scan_select: bool = False,
    poll_timeout_seconds: int = 1800,
    poll_interval_seconds: int = 15,
) -> None:
    """ECR image scan via Twistlock Console Registry API (no Docker on Prefect worker).

    Pipeline:

    #. ``POST /api/<ver>/authenticate`` → bearer token
    #. ``POST /api/<ver>/registry/scan`` — submit **on-demand** scan for ``registry/repo:tag`` (Twistlock queue)
    #. Optional ``POST /api/v1/registry/scan/select`` — trigger registry scan-select helper
    #. Poll ``registry/progress`` and (when no compact row existed before enqueue) compact ``GET /registry?name=…``
    #. ``GET /api/<ver>/registry?name=<image_ref>&compact=true`` — fetch result; log CVE/CDE-style report;
       enforce critical/high policy

    Optional ``microservice_report_name``: label for the vulnerability report table (defaults to ECR repo path).

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

    settings = TwistlockSettings.from_prefect(
        PrefectTwistlockSettingsLoader(), address_override=twistlock_address
    )
    logger.info(
        "using Twistlock address=%r api_version=%r",
        settings.address,
        settings.api_version,
    )
    logger.info("loaded twistlock-username and twistlock-password from Prefect Secret blocks")

    logger.info("authenticating to Twistlock console...")
    service = TwistlockRegistryScanService(HttpTwistlockRegistryClient(settings), logger)
    service.scan(
        ImageRef.parse(image_ref),
        microservice_report_name=microservice_report_name,
        trigger_registry_scan_select=trigger_registry_scan_select,
        poll_timeout_seconds=poll_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


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
    parsed_image_ref = ImageRef.parse(image_ref)
    settings = TwistlockSettings.from_prefect(
        PrefectTwistlockSettingsLoader(), address_override=twistlock_address
    )
    logger.info(
        "verify: address=%r api_version=%r image_ref=%r",
        settings.address,
        settings.api_version,
        parsed_image_ref.value,
    )

    service = TwistlockRegistryScanService(HttpTwistlockRegistryClient(settings), logger)
    return service.verify(parsed_image_ref, fail_if_not_found=fail_if_not_found)
