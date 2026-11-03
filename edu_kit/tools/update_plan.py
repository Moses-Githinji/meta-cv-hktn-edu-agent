"""update_plan: the coverage plan. Nothing is stored; the plan stays in the conversation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "update_plan",
    "description": "Replace the coverage plan. Cover every checklist item; say what you will read or cite next for each.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"plan": {"type": "array", "items": {"type": "string"}}},
        "required": ["plan"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    return {"plan": [str(step) for step in args.get("plan") or []]}
