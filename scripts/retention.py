#!/usr/bin/env python3
"""Retention: list or purge runs older than the policy keeps.

    ./helper retention              # dry run: what would go (default 90 days)
    ./helper retention --days 30    # same, 30-day window
    ./helper retention --apply      # actually delete (run dir + case record)

Policy (see PILOT.md): run artifacts (conversation, audit log, figures,
exports) are operational data and go after 90 days; curriculum packs,
teacher context, and the alert log stay. Never deletes outside
workspace/runs/<run-id>/ and workspace/case_records/<run-id>.json.
Purged run ids are reported, never recovered: back up first if unsure.
"""

from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DAYS = 90


def _started(progress_path: Path) -> datetime.datetime | None:
    try:
        started = json.loads(progress_path.read_text()).get("started")
        moment = datetime.datetime.fromisoformat(started)
    except (OSError, ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment


def expired(root: Path, days: int, now: datetime.datetime | None = None) -> list:
    """Run ids older than `days` (by run start time), oldest first."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    runs_dir = Path(root) / "workspace/runs"
    if not runs_dir.is_dir():
        return []
    found = []
    for folder in runs_dir.iterdir():
        if not folder.is_dir():
            continue
        started = _started(folder / "progress.json")
        if started is not None and (now - started).days > days:
            found.append((started, folder.name))
    return [name for _, name in sorted(found)]


def purge(root: Path, run_id: str) -> list:
    """Delete one run's directory and case record; return removed paths."""
    root = Path(root)
    removed = []
    for path in (
        root / "workspace/runs" / run_id,
        root / "workspace/case_records" / f"{run_id}.json",
    ):
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(str(path))
        elif path.is_file():
            path.unlink()
            removed.append(str(path))
    return removed


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--apply", action="store_true", help="actually delete")
    args = parser.parse_args(argv)
    old = expired(ROOT, args.days)
    if not old:
        print(f"no runs older than {args.days} days")
        return 0
    if not args.apply:
        print(f"{len(old)} run(s) older than {args.days} days (dry run; --apply deletes):")
        for run_id in old:
            print(f"  {run_id}")
        return 0
    for run_id in old:
        for path in purge(ROOT, run_id):
            print(f"removed {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
