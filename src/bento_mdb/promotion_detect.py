"""Parse git diff of config/mdb_models.yml to detect updated models (release vs prerelease-only).

Use via import:

  from bento_mdb.promotion_detect import parse_diff
  model_filters = parse_diff(diff_text)
  # model_filters = [{"model": "CDS", "latest_version": "11.0.4", "prerelease_version": null, "has_prerelease_update": false}, ...]
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# Context line: @@ ... ModelName:
_CONTEXT_RE = re.compile(r"^@@.*@@\s+([A-Za-z0-9_-]+):")
# Added lines and value capture
_LINE_LATEST_VERSION = re.compile(r"^\+\s+latest_version:\s*(.+)$")
_LINE_PRERELEASE_VERSION = re.compile(r"^\+\s+latest_prerelease_version:\s*(.+)$")
_LINE_PRERELEASE_COMMIT = re.compile(r"^\+\s+latest_prerelease_commit:\s*(.+)$")

_DEFAULT_MODEL_ENTRY = {"saw_release": False, "latest_version": None, "prerelease_version": None, "prerelease_commit": None}


def _ensure_model(data: dict[str, dict], model: str) -> None:
    if model not in data:
        data[model] = dict(_DEFAULT_MODEL_ENTRY)


def parse_diff(diff_text: str) -> list[dict]:
    """Parse git diff of mdb_models.yml. Returns a list of dicts per updated model (see module docstring for shape)."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
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
        if not current:
            continue
        if _LINE_LATEST_VERSION.match(line) and "prerelease" not in line:
            _ensure_model(data, current)
            val = _LINE_LATEST_VERSION.match(line).group(1).strip()
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
            # do not clear current so prerelease_version can follow in any order

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
            else:
                prerelease_version = base
            prerelease_version = prerelease_version if prerelease_version else None
        out.append({
            "model": model,
            "latest_version": d.get("latest_version"),
            "prerelease_version": prerelease_version,
            "has_prerelease_update": not saw_release,
        })
    if out:
        for item in out:
            kind = "release" if not item["has_prerelease_update"] else "prerelease"
            logger.info(
                "  %s: %s (latest_version=%s, prerelease_version=%s)",
                item["model"],
                kind,
                item["latest_version"],
                item["prerelease_version"],
            )
        logger.info("Detected %d updated model(s)", len(out))
    else:
        logger.info("No updated models detected")
    return out
