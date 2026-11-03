"""ask_teacher: ask the teacher about one checklist item you cannot cover.

Use it when an outcome is not transcribed, or nothing in the pack settles the
item. The run pauses (needs_input) until the teacher answers; resume the same
run afterwards. One open question per item.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import document_text

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "ask_teacher",
    "description": "Ask the teacher about one checklist item you cannot cover from the pack, e.g. an outcome that "
    "is not transcribed yet. Name the item and ask exactly what is missing. The run pauses until the teacher "
    "answers. One open question per item. When the block is an untranscribed outcome, end the question by telling "
    "the teacher how to reply: either say to proceed and list it as a gap, or say they are transcribing the wording "
    "into the pack and you will re-read after they resume (their answer itself cannot supply official wording).",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "item": {
                "type": "string",
                "description": "id of an item in your checklist (set_checklist)",
            },
            "question": {"type": "string"},
        },
        "required": ["item", "question"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    item = str(args.get("item", ""))
    question = str(args.get("question", ""))
    checklist = ctx.case.data["checklist"]
    if not checklist:
        return {"error": "there is no checklist yet: call set_checklist first"}
    if item not in checklist:
        return {
            "error": f"unknown checklist item {item!r}; "
            f"valid items: {', '.join(checklist)}"
        }
    if checklist[item]["status"] == "proven":
        return {"error": f"{item} is already covered: no need to ask"}
    if any(r["status"] == "open" for r in ctx.case.open_requests()):
        return {"error": "a question is already open: wait for the teacher's answer"}
    if not question.strip():
        return {"error": "question must say exactly what is missing"}
    visible = [d["id"] for d in document_text.list_documents(ctx.root)]
    request = ctx.case.open_request(item, question, "teacher_input", visible)
    return {
        "escalated": True,
        "request": request["id"],
        "item": item,
        "question": question,
        "status": "needs_input",
    }
