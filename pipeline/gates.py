"""Automated gates: what a candidate pack must pass before publishing.

run_all(candidate, current, records) runs every gate and reports failures by
gate name; passed = no failures. Gates fail closed: anything unexpected
(unmapped records, mirror-sourced wording, rewritten text, suspicious
content) blocks publishing. Suspicious content is quarantined
(var/quarantine/) by publish, never published.
"""

from __future__ import annotations

import datetime
import json
import re
import tempfile
from pathlib import Path

from curriculum.loader import PackError, load_pack

from .diff import diff_packs, outcome_map
from .sources import SourceError, is_authority

SUSPICIOUS_PATTERNS = [
    (r"<script\b", "script tag"),
    (r"javascript:", "javascript: URL"),
    (r"ignore (all |any |your )?previous instructions", "instruction override"),
    (r"ignore the .*instructions above", "instruction override"),
    (r"\bsystem prompt\b", "system-prompt reference"),
    (r"you are now ", "role-reassignment phrase"),
    (r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "control characters"),
]
_COMPILED = [(re.compile(pattern, re.IGNORECASE), label) for pattern, label in SUSPICIOUS_PATTERNS]


def scan_suspicious(records: list) -> dict:
    """Records whose text matches a suspicious pattern: {outcome_id: [reasons]}."""
    flagged: dict[str, list] = {}
    for record in records:
        text = record.get("outcome_text", "")
        reasons = sorted(
            {label for pattern, label in _COMPILED if pattern.search(text)}
        )
        if reasons:
            flagged[record.get("outcome_id", "?")] = reasons
    return flagged


def quarantine(var_dir: Path, records: list, reasons: dict) -> Path:
    """Hold suspicious records outside the pack for human review; return the file."""
    folder = Path(var_dir) / "quarantine"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"{stamp}-{len(list(folder.glob('*.json'))):03d}.json"
    path.write_text(
        json.dumps(
            {"at": stamp, "reasons": reasons, "records": records}, indent=1
        )
    )
    return path


def run_all(candidate: dict, current: dict, records: list) -> dict:
    """Every gate on a candidate pack: {"passed", "failures": {gate: [msgs]}}."""
    failures: dict[str, list] = {}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "candidate.json"
        path.write_text(json.dumps(candidate))
        try:
            load_pack(path)
        except PackError as error:
            failures["schema"] = [f"candidate pack invalid: {error}"]

    known = set(outcome_map(current))
    unmapped = sorted({r.get("outcome_id", "?") for r in records} - known)
    if unmapped:
        failures["unmapped"] = [
            f"{oid}: not an outcome in the pack; add a pending entry first"
            for oid in unmapped
        ]

    difference = diff_packs(current, candidate)
    if difference["removed"]:
        failures["removals"] = [
            f"{oid}: outcomes are never removed" for oid in difference["removed"]
        ]
    if difference["reverted"]:
        failures["reverted"] = [
            f"{oid}: transcribed outcomes stay transcribed"
            for oid in difference["reverted"]
        ]
    if difference["changed"]:
        failures["immutable_text"] = [
            f"{oid}: transcribed wording is immutable; human re-review required"
            for oid in difference["changed"]
        ]

    after = outcome_map(candidate)
    authority_problems = []
    for oid in difference["transcribed"]:
        url = ((after[oid].get("provenance") or {}).get("source_url")) or ""
        try:
            allowed = is_authority(url)
        except SourceError:
            allowed = False
        if not allowed:
            authority_problems.append(
                f"{oid}: transcribed wording must come from an authority, not {url!r}"
            )
    if authority_problems:
        failures["authority"] = authority_problems

    stubs = [
        oid
        for oid in difference["transcribed"]
        if (after[oid].get("outcome_text") or "") in ("", "TODO_TRANSCRIBE")
    ]
    if stubs:
        failures["stubs"] = [
            f"{oid}: transcribed text is still a stub" for oid in stubs
        ]

    flagged = scan_suspicious(records)
    if flagged:
        failures["suspicious"] = [
            f"{oid}: quarantined ({', '.join(reasons)})"
            for oid, reasons in sorted(flagged.items())
        ]
    return {"passed": not failures, "failures": failures}
