"""Scrape-failure alerts: every pipeline failure, in one append-only log.

Fetch errors, extraction errors, and gate refusals are recorded here
(var/pipeline/alerts.jsonl, one JSON object per line) as well as returned to
the caller, so a refresh that fails overnight still explains itself in the
morning. Severities: "warning" (one URL failed, the refresh continued) and
"error" (the refresh stopped).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path


def _path(var_dir: Path) -> Path:
    return Path(var_dir) / "pipeline" / "alerts.jsonl"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def record(
    var_dir: Path,
    severity: str,
    source: str,
    message: str,
    at: str | None = None,
) -> dict:
    """Append one alert and return it."""
    if severity not in ("warning", "error"):
        raise ValueError(f"severity must be warning or error, not {severity!r}")
    entry = {
        "at": at or _now(),
        "severity": severity,
        "source": source,
        "message": str(message),
    }
    path = _path(var_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(entry) + "\n")
    return entry


def list_alerts(var_dir: Path, severity: str | None = None) -> list:
    """Every alert, oldest first, optionally filtered by severity."""
    path = _path(var_dir)
    if not path.is_file():
        return []
    entries = [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]
    if severity is not None:
        entries = [e for e in entries if e.get("severity") == severity]
    return entries
