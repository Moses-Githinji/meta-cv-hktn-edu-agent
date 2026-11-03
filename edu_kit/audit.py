"""The run's audit log: a hash-chained event log, one file per run.

Every tool call (from edu_kit/tools/) and every loop event (run started,
resumed, stopped, model errors) is appended to
workspace/runs/<run-id>/audit.jsonl, one JSON object per line. Each entry
carries the SHA-256 of the previous entry's hash, so any edit, deletion, or
reorder breaks the chain:

    audit.append(root, run_id, "tool_call", {"tool": "cite_outcome", ...})
    audit.verify(root, run_id)   # {"ok": True, "events": n} or {"ok": False, ...}

Independent verification (scripts/independent_verify.py) replays the chain
instead of trusting it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .progress import now

GENESIS = "genesis"


def _path(root: Path, run_id: str) -> Path:
    return Path(root) / "workspace/runs" / run_id / "audit.jsonl"


def _hash(entry: dict) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def read(root: Path, run_id: str) -> list:
    """Every audit entry for a run, oldest first (empty when nothing is logged yet)."""
    path = _path(root, run_id)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def append(
    root: Path, run_id: str, event: str, detail: dict | None = None, actor: str = "agent"
) -> dict:
    """Append one event and return its entry (with its chain hash)."""
    entries = read(root, run_id)
    entry = {
        "seq": len(entries) + 1,
        "at": now(),
        "actor": actor,
        "event": event,
        "detail": detail or {},
        "prev": entries[-1]["hash"] if entries else GENESIS,
    }
    entry["hash"] = _hash(entry)
    path = _path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(entry, default=str) + "\n")
    return entry


def verify(root: Path, run_id: str) -> dict:
    """Replay the chain: linkage, order, and every hash. Fails closed on any break."""
    entries = read(root, run_id)
    prev = GENESIS
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            return _broken(position, "entry is not an object")
        if entry.get("seq") != position:
            return _broken(position, f"seq is {entry.get('seq')}, expected {position}")
        if entry.get("prev") != prev:
            return _broken(position, "previous hash does not match")
        stored = entry.get("hash")
        recomputed = _hash({k: v for k, v in entry.items() if k != "hash"})
        if not stored or stored != recomputed:
            return _broken(position, "entry hash does not match its contents")
        prev = stored
    return {"ok": True, "events": len(entries)}


def _broken(position: int, error: str) -> dict[str, Any]:
    return {"ok": False, "events": position - 1, "error": f"entry {position}: {error}"}
