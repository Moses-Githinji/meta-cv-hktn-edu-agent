"""check_answers: check an answer set against its questions, standalone.

Every question needs exactly one answer, answer marks must equal question
marks, and nothing may be empty. Run it before filing an exam's marking
scheme; the same check runs again at filing time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from exams.validate import validate_answers

if TYPE_CHECKING:
    from . import Context

ANSWER = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "question_id": {"type": "string"},
        "answer": {"type": "string"},
        "marks": {"type": "integer"},
    },
    "required": ["question_id", "answer", "marks"],
}
QUESTION = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "marks": {"type": "integer"},
    },
    "required": ["id", "marks"],
}

DEFINITION = {
    "type": "function",
    "name": "check_answers",
    "description": "Check an answer set against its questions: one answer per question, marks equal, "
    "nothing empty. Run it before filing an exam's marking scheme.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "questions": {"type": "array", "items": QUESTION},
            "answers": {"type": "array", "items": ANSWER},
        },
        "required": ["questions", "answers"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    problems = validate_answers(args.get("questions"), args.get("answers"))
    if problems:
        return {"ok": False, "problems": problems}
    total = sum(q.get("marks", 0) for q in args["questions"])
    return {"ok": True, "total_marks": total}
