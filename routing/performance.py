"""Performance-based choice: learn pass rates, promote winners later.

record() appends one outcome (task, role, model, pass/fail, tokens, ms) to
var/routing/stats.jsonl. choose() returns the best model for a role once it
has min_samples outcomes — highest pass rate, ties broken by lower cost
(registry prices) then by name — or None when nothing qualifies, in which
case the caller keeps the static table. The router never auto-switches
production: promotion is a human reading stats() and updating the table.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

MIN_SAMPLES = 5


def _path(var_dir: Path) -> Path:
    return Path(var_dir) / "routing" / "stats.jsonl"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def record(
    var_dir: Path,
    task: str,
    role: str,
    model: str,
    passed: bool,
    input_tokens: int = 0,
    output_tokens: int = 0,
    ms: int = 0,
) -> dict:
    """Append one outcome and return it."""
    entry = {
        "at": _now(),
        "task": task,
        "role": role,
        "model": model,
        "passed": bool(passed),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "ms": ms,
    }
    path = _path(var_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(entry) + "\n")
    return entry


def outcomes(var_dir: Path, role: str | None = None) -> list:
    """Recorded outcomes, oldest first, optionally filtered by role."""
    path = _path(var_dir)
    if not path.is_file():
        return []
    entries = [
        json.loads(line) for line in path.read_text().splitlines() if line.strip()
    ]
    if role is not None:
        entries = [e for e in entries if e.get("role") == role]
    return entries


def stats(var_dir: Path, role: str) -> dict:
    """Per-model {samples, pass_rate, tokens} for a role."""
    summary: dict[str, dict] = {}
    for entry in outcomes(var_dir, role):
        model = entry.get("model", "?")
        row = summary.setdefault(model, {"samples": 0, "passed": 0, "tokens": 0})
        row["samples"] += 1
        row["passed"] += 1 if entry.get("passed") else 0
        row["tokens"] += entry.get("input_tokens", 0) + entry.get("output_tokens", 0)
    for row in summary.values():
        row["pass_rate"] = round(row["passed"] / row["samples"], 3) if row["samples"] else 0.0
    return summary


def choose(var_dir: Path, role: str, min_samples: int = MIN_SAMPLES) -> str | None:
    """The best qualified model for a role, or None (keep the static table)."""
    from .registry import prices

    summary = stats(var_dir, role)
    qualified = {m: r for m, r in summary.items() if r["samples"] >= min_samples}
    if not qualified:
        return None
    priced = prices(var_dir)

    def key(item: tuple) -> tuple:
        name, row = item
        entry = priced.get(name, {})
        cost = float(entry.get("in_per_1k", 0) or 0) + float(entry.get("out_per_1k", 0) or 0)
        return (-row["pass_rate"], cost, name)

    return sorted(qualified.items(), key=key)[0][0]
