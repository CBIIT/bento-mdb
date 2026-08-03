"""Parse git diff of config/mdb_models.yml to detect updated models (release vs prerelease-only).

Use via import:

  from bento_mdb.promotion_detect import parse_diff
  model_filters = parse_diff(diff_text)
  # model_filters = [{"model": "CDS", "latest_version": "11.0.4", "prerelease_version": null, "has_prerelease_update": false}, ...]
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from bento_mdb.model_cdes import load_model_specs_from_yaml

logger = logging.getLogger(__name__)

_DEFAULT_SPECS_PATH = Path("config/mdb_models.yml")


# Context line: @@ ... ModelName:
_CONTEXT_RE = re.compile(r"^@@.*@@\s+([A-Za-z0-9_-]+):")
_ADDED_MODEL_RE = re.compile(r"^\+([A-Za-z0-9_-]+):\s*$")
_LINE_LATEST_VERSION = re.compile(r"^\+\s+latest_version:\s*(.+)$")
_LINE_PRERELEASE_VERSION = re.compile(r"^\+\s+latest_prerelease_version:\s*(.+)$")
_LINE_PRERELEASE_COMMIT = re.compile(r"^\+\s+latest_prerelease_commit:\s*(.+)$")

_DEFAULT_MODEL_ENTRY = {"saw_release": False, "latest_version": None, "prerelease_version": None, "prerelease_commit": None}


def _ensure_model(data: dict[str, dict], model: str) -> None:
    if model not in data:
        data[model] = dict(_DEFAULT_MODEL_ENTRY)


def parse_diff(
    diff_text: str,
    is_prod_release: bool = False,
) -> list[dict]:
    """Parse git diff of mdb_models.yml. Returns a list of dicts per updated model (see module docstring for shape).
    Loads specs from config/mdb_models.yml so prerelease_commit-only changes get prerelease_version
    built as base-commit from the spec.
    If is_prod_release is True, only include release (latest_version) updates — for QA→Stage→Prod.
    """
    try:
        current_specs = load_model_specs_from_yaml(_DEFAULT_SPECS_PATH)
    except Exception as e:
        logger.debug("Could not load %s: %s", _DEFAULT_SPECS_PATH, e)
        current_specs = {}
    lines = diff_text.splitlines()
    logger.info("Parsing diff of mdb_models.yml (%d lines)", len(lines))
    # Per-model: release_version, prerelease_base, prerelease_commit, saw_release
    data: dict[str, dict] = {}
    current = ""

    for line in lines:
        m = _CONTEXT_RE.match(line)
        if m:
            current = m.group(1)
            continue
        m = _ADDED_MODEL_RE.match(line)
        if m:
            current = m.group(1)
            continue
        if not current:
            continue
        if _LINE_LATEST_VERSION.match(line) and "prerelease" not in line:
            _ensure_model(data, current)
            val = _LINE_LATEST_VERSION.match(line).group(1).strip()
            if val.lower() in {"null", "~"}:
                data[current]["latest_version"] = None
                continue
            data[current]["saw_release"] = True
            data[current]["latest_version"] = val
            current = ""
        elif _LINE_PRERELEASE_VERSION.match(line):
            _ensure_model(data, current)
            val = _LINE_PRERELEASE_VERSION.match(line).group(1).strip()
            data[current]["prerelease_version"] = val
        elif _LINE_PRERELEASE_COMMIT.match(line):
            _ensure_model(data, current)
            val = _LINE_PRERELEASE_COMMIT.match(line).group(1).strip()
            data[current]["prerelease_commit"] = val[:7] if len(val) >= 7 else val

    out: list[dict] = []
    for model in sorted(data):
        d = data[model]
        saw_release = d["saw_release"]
        # When latest_version changed, treat as release only — ignore prerelease for this model.
        if saw_release:
            prerelease_version = None
        else:
            base = d.get("prerelease_version")
            commit = d.get("prerelease_commit")
            if base and commit:
                prerelease_version = f"{base}-{commit}"
            elif commit and current_specs and model in current_specs:
                spec = current_specs[model]
                # Downstream MDF URL uses latest_prerelease_version for path; do not fall back to latest_version.
                base = spec.get("latest_prerelease_version")
                prerelease_version = f"{base}-{commit}" if base else None
            else:
                prerelease_version = base
            prerelease_version = prerelease_version if prerelease_version else None
        # QA→Stage→Prod: only include release (latest_version) updates
        if is_prod_release and not saw_release:
            continue
        out.append({
            "model": model,
            "latest_version": d.get("latest_version"),
            "prerelease_version": prerelease_version,
            "prerelease_commit": d.get("prerelease_commit") if not saw_release else None,
            "has_prerelease_update": not saw_release,
        })
    if out:
        for item in out:
            logger.info(
                "  %s (latest_version=%s, prerelease_version=%s, prerelease_commit=%s)",
                item["model"],
                item["latest_version"],
                item["prerelease_version"],
                item.get("prerelease_commit"),
            )
        logger.info("Detected %d updated model(s)", len(out))
    else:
        logger.info("No updated models detected")
    return out
