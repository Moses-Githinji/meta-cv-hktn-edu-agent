#!/usr/bin/env python3
"""Run the golden evaluation set (offline replay, or live free-runs).

    ./helper eval                    # every task, offline replay
    ./helper eval --task exam-filing # one task
    ./helper eval --live             # free-run with the live API (needs MODEL_API_KEY)
    ./helper eval --shadow JUDGE     # also compare a shadow judge per filed memo

Tasks whose pack has not landed yet skip with a reason. Exit code is 1
when any task fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.runner import load_tasks, run_all  # noqa: E402


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--task", default=None, help="run one task by id")
    parser.add_argument("--live", action="store_true", help="free-run with the live API")
    parser.add_argument("--shadow", default=None, metavar="JUDGE", help="shadow judge model")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    try:
        report = run_all(load_tasks(), live=args.live, only=args.task, shadow_judge=args.shadow)
    except Exception as error:  # missing key, bad fixture: report, don't trace
        print(f"eval failed: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        for task in report["tasks"]:
            if task.get("skipped"):
                print(f"SKIP {task['id']}: {task.get('reason')}")
            else:
                print(("PASS " if task["pass"] else "FAIL ") + task["id"])
                for failure in task["failures"]:
                    print(f"  {failure}")
                shadow = task.get("shadow") or {}
                if shadow.get("compared"):
                    print(
                        f"  shadow: primary={shadow['primary']} "
                        f"shadow={shadow['shadow']} agree={shadow['agree']}"
                    )
        print(
            f"{report['passed']} passed, {report['failed']} failed, "
            f"{report['skipped']} skipped"
        )
    return 0 if not report["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
