"""cite_outcome: cite one curriculum outcome for one checklist item.

Refused unless the quote is the outcome's exact text (copy it from
read_curriculum); at most 3 citations per item. The result says which items
are still open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from curriculum.loader import PackError, find_outcome

from . import pack as pack_loader

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "cite_outcome",
    "description": "Cite one curriculum outcome for one checklist item. Refused unless the quote is the outcome's "
    "exact text as read from read_curriculum. At most 3 citations per item. The result says which items are "
    "still open.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "item": {
                "type": "string",
                "description": "id of an item in your checklist (set_checklist)",
            },
            "outcome_id": {
                "type": "string",
                "description": "e.g. G7M-T1-1.1.1",
            },
            "quote": {"type": "string"},
            "claim": {"type": "string"},
        },
        "required": ["item", "outcome_id", "quote", "claim"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    outcome_id = str(args.get("outcome_id", "")).strip()
    try:
        pack = pack_loader.load(ctx)
    except PackError as error:
        return {"error": f"curriculum pack unreadable: {error}"}
    found = find_outcome(pack, outcome_id) if outcome_id else None
    if found is None:
        return {"error": f"unknown outcome {outcome_id!r}; use list_curriculum first"}
    if found["status"] != "transcribed":
        return {
            "error": f"outcome {outcome_id} is not transcribed yet: nothing to cite. "
            "Ask the teacher with ask_teacher."
        }
    cited = ctx.case.cite_outcome(
        str(args.get("item", "")),
        outcome_id,
        str(args.get("quote", "")),
        str(args.get("claim", "")),
        found["outcome_text"],
    )
    return {"recorded": cited}
