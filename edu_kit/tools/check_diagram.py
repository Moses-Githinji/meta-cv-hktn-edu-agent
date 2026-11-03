"""check_diagram: validate a diagram spec without rendering it.

Returns {"ok": True} or {"ok": False, "problems": [...]}. Run it before
make_diagram to catch typos and out-of-range coordinates cheaply.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from diagrams.spec import validate_spec

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "check_diagram",
    "description": "Validate a diagram spec (kind graph, geometry, circuit, apparatus, or ray, "
    "with title and elements) without rendering it. Fix any problems, then render with make_diagram.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "spec": {
                "type": "object",
                "description": "the diagram spec to check",
            },
        },
        "required": ["spec"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    spec = args.get("spec")
    if not isinstance(spec, dict):
        return {"error": "spec must be an object"}
    problems = validate_spec(spec)
    if problems:
        return {"ok": False, "problems": problems}
    return {"ok": True}
