"""Refresh schedule: when to re-fetch, and the refresh run itself.

var/pipeline/schedule.json holds {"interval_days", "last_run", "last_status"}.
due() is true when the interval has passed (or no refresh ever ran).
refresh() fetches every seed, extracts new artifacts, builds a candidate,
runs the gates, and writes var/pipeline/last_refresh.json — but never
publishes: publishing needs a human reviewer (see publish.py).

Failures alert but do not cascade: one bad URL is a warning and the refresh
continues; no usable records, or refused gates, end the refresh as an error.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from . import alerts, extract, gates, raw_store, staleness
from .fetch import (
    DEFAULT_MIN_INTERVAL,
    FetchError,
    RateLimiter,
    fetch_url,
)
from .publish import build_candidate, load_current
from .sources import seeds

DEFAULT_INTERVAL_DAYS = 7


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _schedule_path(var_dir: Path) -> Path:
    return Path(var_dir) / "pipeline" / "schedule.json"


def read_schedule(var_dir: Path) -> dict:
    """The schedule ({interval_days, last_run, last_status}); defaults when absent."""
    path = _schedule_path(var_dir)
    schedule = {"interval_days": DEFAULT_INTERVAL_DAYS, "last_run": None, "last_status": None}
    if path.is_file():
        try:
            schedule.update(json.loads(path.read_text()))
        except ValueError:
            pass
    return schedule


def write_schedule(
    var_dir: Path, interval_days: int | None = None, last_run: str | None = None, last_status: str | None = None
) -> dict:
    """Set schedule fields (only the ones given) and return the schedule."""
    schedule = read_schedule(var_dir)
    if interval_days is not None:
        schedule["interval_days"] = interval_days
    if last_run is not None:
        schedule["last_run"] = last_run
    if last_status is not None:
        schedule["last_status"] = last_status
    path = _schedule_path(var_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedule, indent=1))
    return schedule


def due(var_dir: Path, now: datetime.datetime | None = None) -> bool:
    """Whether a refresh is due under the schedule."""
    schedule = read_schedule(var_dir)
    last = schedule.get("last_run")
    if not last:
        return True
    try:
        moment = datetime.datetime.fromisoformat(last)
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    age = (now or _now()) - moment
    return age.days >= int(schedule.get("interval_days", DEFAULT_INTERVAL_DAYS))


def refresh(
    root: Path,
    var_dir: Path,
    transport=None,
    urls: list | None = None,
    min_interval: float = DEFAULT_MIN_INTERVAL,
) -> dict:
    """Run one refresh: fetch, extract, gate, report. Never publishes.

    Returns the report (also written to var/pipeline/last_refresh.json):
    {"ok", "fetched", "records", "verdict", "staleness", "alerts"}.
    """
    root, var_dir = Path(root), Path(var_dir)
    started = _now().isoformat()
    limiter = RateLimiter(var_dir / "raw", min_interval=min_interval)
    robots_cache: dict = {}
    fetched, warnings = [], []
    for url in urls if urls is not None else seeds():
        try:
            body, content_type = fetch_url(
                url,
                transport=transport,
                rate_limiter=limiter,
                robots_cache=robots_cache,
            )
        except (FetchError, ValueError) as error:
            warnings.append(str(error))
            alerts.record(var_dir, "warning", url, str(error))
            continue
        entry = raw_store.store(var_dir, body, url, content_type)
        fetched.append({"url": url, "sha256": entry["sha256"], "deduped": entry["deduped"]})
    records = []
    for item in fetched:
        entry = raw_store.read_manifest(var_dir)[item["sha256"]]
        try:
            records.extend(
                extract.extract(
                    raw_store.get(var_dir, item["sha256"]),
                    entry.get("content_type", ""),
                    item["url"],
                    entry.get("retrieved_at", ""),
                    item["sha256"],
                )
            )
        except extract.ExtractionError as error:
            warnings.append(str(error))
            alerts.record(var_dir, "warning", item["url"], str(error))
    current = load_current(root)
    candidate, unmapped = build_candidate(current, records)
    verdict = gates.run_all(candidate, current, records)
    report = {
        "at": started,
        "ok": bool(records) and verdict["passed"],
        "fetched": fetched,
        "records": len(records),
        "unmapped": [r.get("outcome_id") for r in unmapped],
        "verdict": verdict,
        "staleness": staleness.report(root, var_dir),
        "warnings": warnings,
    }
    if not records:
        alerts.record(var_dir, "error", "refresh", "no usable records extracted")
    elif not verdict["passed"]:
        alerts.record(
            var_dir,
            "error",
            "refresh",
            "gates refused the candidate: "
            + "; ".join(verdict["failures"]),
        )
    path = var_dir / "pipeline" / "last_refresh.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1))
    write_schedule(var_dir, last_run=started, last_status="ok" if report["ok"] else "error")
    return report
