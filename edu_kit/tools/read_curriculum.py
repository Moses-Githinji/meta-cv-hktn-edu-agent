"""read_curriculum: one outcome's exact text, with its strand context.

Offline: reads the curriculum pack natively, so the text is always exact.
Refused for an unknown outcome id, and for an outcome still pending
transcription: that is missing information, not a failure — ask the teacher.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from curriculum.loader import PackError, find_outcome

from . import pack as pack_loader

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "read_curriculum",
    "description": "Read one curriculum outcome's exact text by its id (from list_curriculum), with strand, "
    "sub-strand, and week range. One outcome per call.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "outcome_id": {
                "type": "string",
                "description": "e.g. G7M-T1-1.1.1",
            },
        },
        "required": ["outcome_id"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    outcome_id = str(args.get("outcome_id", "")).strip()
    if not outcome_id:
        return {"error": "outcome_id must be non-empty"}
    try:
        pack = pack_loader.load(ctx)
    except PackError as error:
        return {"error": f"curriculum pack unreadable: {error}"}
    found = find_outcome(pack, outcome_id)
    if found is None:
        return {"error": f"unknown outcome {outcome_id!r}; use list_curriculum first"}
    if found["status"] != "transcribed":
        return {
            "error": f"outcome {outcome_id} is not transcribed yet ({found['sub_strand']}, "
            f"weeks {found['week_range'][0]}-{found['week_range'][1]}). "
            "This is missing information: ask the teacher with ask_teacher."
        }
    ctx.case.mark_read([outcome_id])
    outcome = {
        "id": found["id"],
        "outcome_text": found["outcome_text"],
        "source_ref": found["source_ref"],
        "strand": found["strand"],
        "sub_strand": found["sub_strand"],
        "week_range": found["week_range"],
    }
    for field in ("suggested_learning_experiences", "key_inquiry_questions",
                  "assessment", "learning_resources"):
        if found.get(field):
            outcome[field] = found[field]
    return {"outcome": outcome}
