"""The agent's tools, one file per tool: its DEFINITION (what the model sees) and
run(ctx, args) (what happens when the model calls it).

    tools.definitions(root, run_id)        # the tools to offer the model in this run
    result = tools.run(client, root, run_id, call)   # run the tool the model chose
    result.get("status", "running")        # "running", or why the run must stop

BASE_TOOLS are the tools the agent always has: the six kit tools plus the ten
teaching tools. VERIFIER_TOOLS are added for runs started with VERIFICATION=on,
and with it on, set_checklist, analyze_document, submit_memo and submit_document
also run the checks in verification/ at their fixed points.

A result is what the model sees next. A refused call comes back as {"error": ...} so the
model can correct it. A result carries "status" only when the run must stop:
"answered" (filed, verification off), "needs_input" (a teacher question is open),
"escalated" (a formal escalation is open), "awaiting_signoff" (the document passed
the checks), or "paused" (a check is not built yet).

Every call is appended to the run's hash-chained audit log (edu_kit/audit.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from ..audit import append as audit_append
from ..case_record import CaseRecord
from ..progress import load_progress
from . import (
    analyze_document,
    ask_teacher,
    check_answers,
    check_diagram,
    check_signatures,
    cite_outcome,
    escalate,
    flag_privileged,
    list_curriculum,
    list_documents,
    make_diagram,
    read_curriculum,
    record_fact,
    request_evidence,
    set_checklist,
    submit_document,
    submit_lesson_plan,
    submit_memo,
    update_plan,
)

BASE_TOOLS = [
    "set_checklist",
    "update_plan",
    "list_documents",
    "analyze_document",
    "record_fact",
    "submit_memo",
    "list_curriculum",
    "read_curriculum",
    "cite_outcome",
    "ask_teacher",
    "escalate",
    "submit_document",
    "check_answers",
    "check_diagram",
    "make_diagram",
    "submit_lesson_plan",
]
VERIFIER_TOOLS = ["flag_privileged", "request_evidence", "check_signatures"]

MODULES: dict[str, Any] = {
    str(m.DEFINITION["name"]): m
    for m in (
        set_checklist,
        update_plan,
        list_documents,
        analyze_document,
        record_fact,
        submit_memo,
        list_curriculum,
        read_curriculum,
        cite_outcome,
        ask_teacher,
        escalate,
        submit_document,
        check_answers,
        check_diagram,
        make_diagram,
        submit_lesson_plan,
        flag_privileged,
        request_evidence,
        check_signatures,
    )
}
DEFINITIONS: dict[str, dict] = {
    name: module.DEFINITION for name, module in MODULES.items()
}


@dataclass
class Context:
    """What a tool gets besides its arguments."""

    client: OpenAI
    root: Path
    run_id: str
    case: CaseRecord
    verification: bool


def names(verification: bool) -> list:
    return BASE_TOOLS + VERIFIER_TOOLS if verification else list(BASE_TOOLS)


def definitions(root: Path, run_id: str) -> list:
    """The tool definitions to offer the model in this run."""
    verification = bool(load_progress(root, run_id).get("verification"))
    return [DEFINITIONS[name] for name in names(verification)]


def run(client: OpenAI, root: Path, run_id: str, call: Any) -> dict:
    """Run the tool the model chose (an item of response.output, or the same as a dict).

    Every call against a known run is appended to the run's audit log, refused
    calls included, so the log shows what the model tried, not just what worked.
    """
    name, raw = _field(call, "name"), _field(call, "arguments") or "{}"
    try:
        args = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError) as error:
        return {"error": f"tool arguments are not valid JSON: {error}"}
    if not isinstance(args, dict):
        return {"error": "tool arguments must be a JSON object"}
    root = Path(root)
    verification = bool(load_progress(root, run_id).get("verification"))
    if name not in names(verification):
        result = {"error": f"unknown tool: {name!r}"}
    else:
        ctx = Context(client, root, run_id, CaseRecord(root, run_id), verification)
        try:
            outcome = MODULES[name].run(ctx, args)
        except NotImplementedError as error:  # a check that is not built yet: stop the run
            outcome = {"error": str(error), "status": "paused"}
        except Exception as error:  # the model reads the error and tries again
            outcome = {"error": str(error) or type(error).__name__}
        result = outcome if isinstance(outcome, dict) else {"result": outcome}
    audit_append(
        root,
        run_id,
        "tool_call",
        {
            "tool": name,
            "status": result.get("status", "running"),
            "error": result.get("error"),
        },
    )
    return result


def _field(call: Any, key: str) -> Any:
    return call.get(key) if isinstance(call, dict) else getattr(call, key, None)
