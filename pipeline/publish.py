"""Publish and rollback: candidate packs in and out of curriculum/.

build_candidate(current, records) fills the records into a copy of the
current pack (transcribing their pending slots, attaching provenance) and
reports records it cannot map. publish() runs the gates, quarantines
suspicious content, backs the current pack up to var/packs/history/, and
atomically writes the candidate — but only with a human reviewer's name
(reviewed_by), per the TRANSCRIBE.md workflow. rollback() restores a backup.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
from pathlib import Path

from curriculum.loader import PACK_FILENAME

from . import gates
from .diff import diff_packs

_VERSION_TAIL = re.compile(r"^(.*?)(\d+)([^0-9]*)$")


class PublishError(ValueError):
    """Publishing or rollback refused. Safe to show and to log as an alert."""


def pack_path(root: Path) -> Path:
    return Path(root) / "curriculum" / PACK_FILENAME


def load_current(root: Path) -> dict:
    path = pack_path(root)
    if not path.is_file():
        raise PublishError(f"no curriculum pack at {path}")
    try:
        return json.loads(path.read_text())
    except ValueError as error:
        raise PublishError(f"curriculum pack unreadable: {error}") from None


def bump_version(version: str) -> str:
    """Next pack version: increment the trailing number, or start one."""
    match = _VERSION_TAIL.match(str(version))
    if not match:
        return f"{version}.1"
    head, number, tail = match.groups()
    return f"{head}{int(number) + 1}{tail}"


def build_candidate(current: dict, records: list) -> tuple:
    """The candidate pack plus records naming no outcome in it (unmapped)."""
    candidate = copy.deepcopy(current)
    slots = {}
    for strand in candidate.get("strands", []):
        for sub in strand.get("sub_strands", []):
            for outcome in sub.get("outcomes", []):
                slots[outcome.get("id")] = outcome
    unmapped = []
    for record in records:
        oid = record.get("outcome_id")
        slot = slots.get(oid)
        if slot is None:
            unmapped.append(record)
            continue
        slot["outcome_text"] = record["outcome_text"]
        if record.get("source_ref"):
            slot["source_ref"] = record["source_ref"]
        slot["status"] = "transcribed"
        slot["provenance"] = record["provenance"]
    candidate["pack"]["version"] = bump_version(
        candidate.get("pack", {}).get("version", "0")
    )
    return candidate, unmapped


def _history_dir(var_dir: Path) -> Path:
    return Path(var_dir) / "packs" / "history"


def history(var_dir: Path) -> list:
    """Backed-up packs, newest first: [{version, at, path}]."""
    folder = _history_dir(var_dir)
    if not folder.is_dir():
        return []
    entries = []
    for path in sorted(folder.glob("*.json"), reverse=True):
        try:
            pack = json.loads(path.read_text())
            version = (pack.get("pack") or {}).get("version", "?")
        except ValueError:
            version = "?"
        entries.append({"version": version, "at": path.stem, "path": str(path)})
    return entries


def _receipts_path(var_dir: Path) -> Path:
    return Path(var_dir) / "packs" / "receipts.jsonl"


def _record_receipt(var_dir: Path, receipt: dict) -> dict:
    path = _receipts_path(var_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(receipt) + "\n")
    return receipt


def publish(
    root: Path,
    var_dir: Path,
    candidate: dict,
    records: list,
    reviewed_by: str,
) -> dict:
    """Gate, back up, and publish a candidate pack. Returns the receipt."""
    if not str(reviewed_by or "").strip():
        raise PublishError(
            "publishing needs a human reviewer: pass reviewed_by=<name>"
        )
    current = load_current(root)
    verdict = gates.run_all(candidate, current, records)
    if not verdict["passed"]:
        failures = verdict["failures"]
        if "suspicious" in failures:
            flagged = gates.scan_suspicious(records)
            held = [r for r in records if r.get("outcome_id") in flagged]
            path = gates.quarantine(var_dir, held, flagged)
            failures["suspicious"].append(f"held in {path}")
        raise PublishError(
            "candidate refused: " + "; ".join(
                f"{gate}: {', '.join(msgs)}" for gate, msgs in failures.items()
            )
        )
    var_dir = Path(var_dir)
    folder = _history_dir(var_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = folder / f"{stamp}.json"
    backup.write_text(json.dumps(current, indent=2, sort_keys=True))
    target = pack_path(root)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(candidate, indent=2, sort_keys=True))
    tmp.replace(target)
    return _record_receipt(
        var_dir,
        {
            "kind": "publish",
            "at": stamp,
            "reviewed_by": str(reviewed_by).strip(),
            "version": candidate["pack"]["version"],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "diff": diff_packs(current, candidate),
            "backup": str(backup),
        },
    )


def rollback(root: Path, var_dir: Path, version: str | None = None) -> dict:
    """Restore a backed-up pack (newest, or the named version). Returns the receipt."""
    entries = history(var_dir)
    if not entries:
        raise PublishError("no backups to roll back to")
    if version is None:
        chosen = entries[0]
    else:
        chosen = next((e for e in entries if e["version"] == version), None)
        if chosen is None:
            raise PublishError(
                f"no backup of version {version!r}; "
                f"have: {', '.join(e['version'] for e in entries)}"
            )
    target = pack_path(root)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(Path(chosen["path"]).read_bytes())
    tmp.replace(target)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _record_receipt(
        var_dir,
        {
            "kind": "rollback",
            "at": stamp,
            "version": chosen["version"],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "backup": chosen["path"],
        },
    )
