"""submit_lesson_plan: file one week's lesson plan.

Each lesson ties to approved scheme rows (reviewer verdict approved/edited)
and fits its activities into a real timetable slot: minutes must sum exactly
to the slot. Refused with the problems when rows are unapproved or timing
does not add up. Filed plans are LPn on the case record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from curriculum.loader import PackError

from . import pack as pack_loader

if TYPE_CHECKING:
    from . import Context

ACTIVITY = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "minutes": {"type": "integer"},
    },
    "required": ["title", "minutes"],
}
LESSON = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "day": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
        "activities": {"type": "array", "items": ACTIVITY},
        "figures": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["day", "items", "activities"],
}

DEFINITION = {
    "type": "function",
    "name": "submit_lesson_plan",
    "description": "File one week's lesson plan: each lesson names its day, the approved scheme rows "
    "it teaches, and activities whose minutes sum exactly to the timetable slot.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "week": {"type": "integer"},
            "lessons": {"type": "array", "items": LESSON},
        },
        "required": ["week", "lessons"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    from lessons.validate import TimetableError, load_timetable, validate_plan

    plan = {"week": args.get("week"), "lessons": args.get("lessons")}
    try:
        pack = pack_loader.load(ctx)
    except PackError as error:
        return {"error": f"curriculum pack unreadable: {error}"}
    try:
        timetable = load_timetable(ctx.root)
    except TimetableError as error:
        return {"error": str(error)}
    problems = validate_plan(plan, ctx.case.data, timetable, pack["term"]["weeks"])
    if problems:
        return {"error": "lesson plan refused", "problems": problems}
    filed = ctx.case.add_lesson_plan(plan)
    return {"lesson_plan": filed}
