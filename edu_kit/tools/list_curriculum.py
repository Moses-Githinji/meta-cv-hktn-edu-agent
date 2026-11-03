"""list_curriculum: the term's strands, sub-strands, and transcription coverage.

Offline: reads the curriculum pack natively (no document transcription), so the
overview is always exact. Call it first to see what the term covers and which
outcomes are transcribed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from curriculum.loader import PackError, coverage

from . import pack as pack_loader

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "list_curriculum",
    "description": "List the term's curriculum: strands, sub-strands with week ranges, and how many outcomes "
    "are transcribed. Call it first, before setting the checklist.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    },
}


def run(ctx: Context, args: dict) -> dict:
    try:
        pack = pack_loader.load(ctx)
    except PackError as error:
        return {"error": f"curriculum pack unreadable: {error}"}
    strands = []
    for strand in pack["strands"]:
        subs = []
        for sub in strand["sub_strands"]:
            outcomes = sub["outcomes"]
            subs.append(
                {
                    "id": sub["id"],
                    "name": sub["name"],
                    "week_range": sub["week_range"],
                    "outcomes": len(outcomes),
                    "transcribed": sum(
                        1 for o in outcomes if o["status"] == "transcribed"
                    ),
                }
            )
        strands.append(
            {"id": strand["id"], "name": strand["name"], "sub_strands": subs}
        )
    cov = coverage(pack)
    return {
        "pack": pack["pack"]["id"],
        "term_weeks": pack["term"]["weeks"],
        "lessons_per_week": pack["term"]["lessons_per_week"],
        "strands": strands,
        "coverage": {
            "transcribed": cov["transcribed"],
            "total": cov["total"],
            "pending": cov["pending"],
        },
    }
