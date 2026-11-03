"""Staleness: how old is the pack, and when was each source last fetched?

report() compares the pack file's age and every authority source's newest
artifact against max_age_days. Finding aids are listed but never stale on
their own: they are optional. A refresh is due when anything is stale (see
schedule.py), and the report tells the reviewer what to re-fetch.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from urllib.parse import urlparse

from .publish import load_current
from .raw_store import list_artifacts
from .sources import SOURCES

DEFAULT_MAX_AGE_DAYS = 90


def _parse_moment(value: str) -> datetime.datetime | None:
    try:
        moment = datetime.datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment


def report(
    root: Path,
    var_dir: Path,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: datetime.datetime | None = None,
) -> dict:
    """Freshness of the pack and its sources: {"fresh", "stale", ...}."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    current = load_current(root)
    return _report(
        current, _pack_mtime(root), list_artifacts(var_dir), max_age_days, now
    )


def _pack_file(root: Path) -> Path:
    from curriculum.loader import PACK_FILENAME

    return Path(root) / "curriculum" / PACK_FILENAME


def _pack_mtime(root: Path) -> datetime.datetime:
    mtime = _pack_file(root).stat().st_mtime
    return datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc)


def _report(
    current: dict, pack_mtime: datetime.datetime, artifacts: list, max_age_days: int, now: datetime.datetime
) -> dict:
    newest: dict[str, str] = {}
    for artifact in artifacts:
        for url in artifact.get("urls", []):
            host = (urlparse(url).hostname or "").lower()
            seen = artifact.get("retrieved_at", "")
            if host and seen > newest.get(host, ""):
                newest[host] = seen
    sources = {}
    stale: list[str] = []
    for source in SOURCES:
        host = source["host"]
        seen = newest.get(host)
        moment = _parse_moment(seen) if seen else None
        age = (now - moment).days if moment else None
        sources[host] = {
            "kind": source["kind"],
            "retrieved_at": seen,
            "age_days": age,
        }
        if source["kind"] == "authority" and (age is None or age > max_age_days):
            stale.append(
                f"{host}: never fetched"
                if age is None
                else f"{host}: last fetched {age} days ago"
            )
    pack_age = (now - pack_mtime).days
    if pack_age > max_age_days:
        stale.append(f"pack: last changed {pack_age} days ago")
    return {
        "fresh": not stale,
        "stale": stale,
        "pack_version": (current.get("pack") or {}).get("version"),
        "pack_age_days": pack_age,
        "max_age_days": max_age_days,
        "sources": sources,
    }
