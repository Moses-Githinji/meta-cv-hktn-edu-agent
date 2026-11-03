"""The teaching checklist check: a set comparison against the term's outcomes.

Called when the agent calls set_checklist with VERIFICATION=on on a root that
works a teaching pack (see edu_kit/tools/pack.py), and by
./helper verify RUN --checklist on such runs.

    run_verification(ctx, items) -> {"passed": bool, "score": float, "feedback": str}

The pack is the ground truth, and the agent can already see it
(list_curriculum), so this check needs no model judge and no secrecy: an
outcome is covered when some item names its id in its question or
evidence_needed. Transcribed outcomes must be covered so they can be cited;
pending outcomes must be named too, as gaps. passed = every term outcome is
accounted for; score = covered / all outcomes.

The legal ground-truth judge stays in verify_checklist.py for roots without
a teaching pack.
"""

from __future__ import annotations

from curriculum.loader import PackError, coverage, find_outcome, load_pack
from edu_kit.tools.pack import path as pack_path


def outcome_ids(pack: dict) -> list:
    """Every outcome id in the pack, in pack order."""
    return [
        outcome["id"]
        for strand in pack.get("strands", [])
        for sub in strand.get("sub_strands", [])
        for outcome in sub.get("outcomes", [])
    ]


def referenced_outcomes(pack: dict, text: str) -> set:
    """Pack outcome ids named anywhere in `text` (exact id match)."""
    return {oid for oid in outcome_ids(pack) if oid and oid in (text or "")}


def run_verification(ctx, items: list) -> dict:
    try:
        pack = load_pack(pack_path(ctx.root))
    except PackError:
        return {"passed": True, "score": None, "feedback": ""}
    required = outcome_ids(pack)
    if not required:
        return {"passed": True, "score": None, "feedback": ""}
    covered: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = f"{item.get('question', '')} {item.get('evidence_needed', '')}"
        covered |= referenced_outcomes(pack, text)
    missing = [oid for oid in required if oid not in covered]
    score = round(len(covered) / len(required), 2)
    if not missing:
        return {"passed": True, "score": score, "feedback": ""}
    cov = coverage(pack)
    pending = set(cov["pending"])
    details = []
    for oid in missing:
        found = find_outcome(pack, oid) or {}
        weeks = found.get("week_range") or ["?", "?"]
        state = "pending transcription (name it as a gap)" if oid in pending else "transcribed"
        details.append(
            f"{oid} ({found.get('sub_strand', '?')}, weeks {weeks[0]}-{weeks[1]}, {state})"
        )
    return {
        "passed": False,
        "score": score,
        "feedback": (
            "The checklist does not account for every term outcome. "
            "Name each of these outcome ids in an item's evidence_needed: "
            + "; ".join(details)
            + "."
        ),
    }
