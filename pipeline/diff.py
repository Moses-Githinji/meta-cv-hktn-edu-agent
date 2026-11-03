"""Diff two curriculum packs, outcome by outcome.

diff_packs(old, new) reports what a candidate pack would change: added and
removed outcome ids, pending outcomes it transcribes, transcribed text it
rewrites (blocked by the gates), and anything it reverts to pending.
"""

from __future__ import annotations


def outcome_map(pack: dict) -> dict:
    """Every outcome by id, with strand context."""
    found = {}
    for strand in pack.get("strands", []):
        for sub in strand.get("sub_strands", []):
            for outcome in sub.get("outcomes", []):
                found[outcome.get("id")] = {
                    "strand": strand.get("name"),
                    "sub_strand": sub.get("name"),
                    **outcome,
                }
    return found


def diff_packs(old: dict, new: dict) -> dict:
    """The outcome-level difference between two packs, in pack order."""
    before, after = outcome_map(old), outcome_map(new)
    added = [oid for oid in after if oid not in before]
    removed = [oid for oid in before if oid not in after]
    transcribed, changed, reverted, unchanged = [], [], [], 0
    for oid in before:
        if oid not in after:
            continue
        was, now = before[oid], after[oid]
        if was.get("status") == "pending_transcription" and now.get("status") == "transcribed":
            transcribed.append(oid)
        elif was.get("status") == "transcribed" and now.get("status") != "transcribed":
            reverted.append(oid)
        elif (
            was.get("status") == "transcribed"
            and now.get("status") == "transcribed"
            and was.get("outcome_text") != now.get("outcome_text")
        ):
            changed.append(oid)
        else:
            unchanged += 1
    return {
        "added": added,
        "removed": removed,
        "transcribed": transcribed,
        "changed": changed,
        "reverted": reverted,
        "unchanged": unchanged,
        "old_version": (old.get("pack") or {}).get("version"),
        "new_version": (new.get("pack") or {}).get("version"),
    }
