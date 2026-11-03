"""set_checklist: the term outcomes that must be covered by the scheme of work.

With verification on, the checklist check runs first: the teaching set
comparison (verification/verify_teaching_checklist.py) on roots that work a
teaching pack, else the legal ground-truth judge
(verification/verify_checklist.py). A checklist that fails is refused with the
check's feedback; after MAX_TRIES the checklist is accepted, and the score
and feedback stay in the record for the reviewer.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from . import pack as pack_loader

if TYPE_CHECKING:
    from . import Context

MAX_TRIES = 3

ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "description": "snake_case id, e.g. whole_numbers"},
        "question": {
            "type": "string",
            "description": "what term coverage must be established for the scheme of work",
        },
        "evidence_needed": {
            "type": "string",
            "description": "what outcome citation would cover this item",
        },
    },
    "required": ["id", "question", "evidence_needed"],
}

DEFINITION = {
    "type": "function",
    "name": "set_checklist",
    "description": "Set the checklist: the term outcomes that must be covered by the scheme of work, each with "
    "the outcome citation that would cover it. Call it after list_curriculum, before planning. Calling it again "
    "replaces the checklist; items that already have facts or requests must be kept.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"items": {"type": "array", "items": ITEM, "minItems": 1}},
        "required": ["items"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    items = args.get("items") or []
    if ctx.verification:
        ctx.case.parse_checklist(items)  # malformed items are refused before any check
        module = (
            "verification.verify_teaching_checklist"
            if pack_loader.exists(ctx.root)
            else "verification.verify_checklist"
        )
        check = normalize_result(
            importlib.import_module(module).run_verification(ctx, items)
        )
        if (
            check["score"] is not None
        ):  # None: the case has no ground truth to check against
            attempt = len(ctx.case.data["checklist_checks"]) + 1
            accepted = check["passed"] or attempt >= MAX_TRIES
            ctx.case.record_checklist_check(
                items, dict(check, attempt=attempt, accepted=accepted)
            )
            if not accepted:
                return {"error": "checklist refused", "feedback": check["feedback"]}
    return {"checklist": list(ctx.case.set_checklist(items))}


def normalize_result(result: dict) -> dict:
    """A checklist check's result as {"passed", "score", "feedback"}."""
    if not isinstance(result, dict) or "passed" not in result:
        raise ValueError(
            "the checklist check must return {'passed', 'score', 'feedback'}"
        )
    passed = bool(result["passed"])
    score = result.get("score")
    try:
        score = None if score is None else round(float(score), 2)
    except (TypeError, ValueError):
        score = 1.0 if passed else 0.0
    return {
        "passed": passed,
        "score": score,
        "feedback": "" if passed else str(result.get("feedback") or ""),
    }
