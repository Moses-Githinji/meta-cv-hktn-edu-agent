"""Shadow mode: run a second model beside the primary, use the primary.

compare(primary, shadow_model, call, task) calls call(shadow_model), logs
{task, shadow_model, agree} to var/routing/shadow.jsonl, and returns the
primary result untouched. A shadow that errors is logged as an error, never
raised: shadows observe, they never break the run.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Callable


def _path(var_dir: Path) -> Path:
    return Path(var_dir) / "routing" / "shadow.jsonl"


def compare(
    var_dir: Path, task: str, primary: Any, shadow_model: str, call: Callable[[str], Any]
) -> Any:
    """Log shadow agreement; always return the primary result."""
    try:
        shadow = call(shadow_model)
        entry: dict[str, Any] = {
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "task": task,
            "shadow_model": shadow_model,
            "agree": shadow == primary,
        }
    except Exception as error:  # noqa: BLE001  (shadows never break runs)
        entry = {
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "task": task,
            "shadow_model": shadow_model,
            "agree": None,
            "error": str(error)[:200],
        }
    path = _path(var_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(entry) + "\n")
    return primary


def log(var_dir: Path) -> list:
    """Shadow comparisons, oldest first."""
    path = _path(var_dir)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
