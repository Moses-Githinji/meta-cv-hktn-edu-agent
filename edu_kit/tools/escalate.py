"""escalate: formally escalate one checklist item to a person with a reason code.

Unlike ask_teacher (a question for the teacher), an escalation names a reason
code from edu_kit/escalation.py and stops the run as "escalated" until a
person acts. One open request at a time. See ESCALATION_RULES.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import document_text
from ..escalation import REASON_CODES

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "escalate",
    "description": "Escalate one checklist item to a person with a reason code "
    "(missing_outcome_text, timetable_clash, calendar_clash, exam_signoff). "
    "Name the item, the code, and exactly what is needed. The run stops as "
    "escalated until the person acts. One open request at a time. For "
    "missing_outcome_text, tell the person how to reply: proceed-and-list-"
    "as-gap, or transcribing-now-and-resume (their answer itself cannot "
    "supply official wording).",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "item": {
                "type": "string",
                "description": "id of an item in your checklist (set_checklist)",
            },
            "reason_code": {
                "type": "string",
                "description": "one of: missing_outcome_text, timetable_clash, calendar_clash, exam_signoff",
            },
            "need": {"type": "string"},
        },
        "required": ["item", "reason_code", "need"],
    },
}

AGENT_CODES = (
    "missing_outcome_text",
    "timetable_clash",
    "calendar_clash",
    "exam_signoff",
)


def run(ctx: Context, args: dict) -> dict:
    item = str(args.get("item", ""))
    code = str(args.get("reason_code", ""))
    need = str(args.get("need", ""))
    checklist = ctx.case.data["checklist"]
    if not checklist:
        return {"error": "there is no checklist yet: call set_checklist first"}
    if item not in checklist:
        return {
            "error": f"unknown checklist item {item!r}; "
            f"valid items: {', '.join(checklist)}"
        }
    if checklist[item]["status"] == "proven":
        return {"error": f"{item} is already covered: no need to escalate"}
    if code not in REASON_CODES:
        return {
            "error": f"unknown reason code {code!r}; "
            f"valid codes: {', '.join(AGENT_CODES)}"
        }
    if code not in AGENT_CODES:
        return {
            "error": f"reason code {code!r} is not for the agent to raise; "
            f"valid codes: {', '.join(AGENT_CODES)}"
        }
    if any(r["status"] == "open" for r in ctx.case.open_requests()):
        return {"error": "a request is already open: wait for the person's answer"}
    if not need.strip():
        return {"error": "need must say exactly what is missing"}
    return escalate_request(ctx, item, need, code)


def escalate_request(ctx: Context, item: str, need: str, reason_code: str) -> dict:
    """Open a formal escalation for one item; the run stops (escalated)."""
    visible = [d["id"] for d in document_text.list_documents(ctx.root)]
    request = ctx.case.open_request(item, need, reason_code, visible)
    return {
        "escalated": True,
        "request": request["id"],
        "item": item,
        "reason_code": reason_code,
        "need": need,
        "status": "escalated",
    }
