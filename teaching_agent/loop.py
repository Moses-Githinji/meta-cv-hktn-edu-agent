"""The Teaching Agent: the agentic loop.

run_agent works the teaching pack; resume_run continues a run that stopped.

Loop events (started, resumed, stopped, model errors) go to the run's
hash-chained audit log; every tool call is logged by edu_kit/tools itself.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from edu_kit import settings, tools
from edu_kit.audit import append as audit_append
from edu_kit.progress import (
    add_failure_note,
    load_progress,
    new_run,
    resume,
    save_progress,
)

INSTRUCTIONS_PATH = Path(__file__).resolve().parent / "system_instructions.md"

LAST_TURN = (
    "This is your last turn. File your document now with submit_document "
    "using what you have."
)
NUDGE = "Call exactly one tool per turn. Continue with your next tool call."


def run_agent(*, root: Path, client: OpenAI, turns: int = 30) -> dict:
    root = Path(root)
    instructions = INSTRUCTIONS_PATH.read_text()
    objective = (settings.teaching_pack_dir(root) / "objective.md").read_text()
    run_id = new_run(root, instructions=instructions, objective=objective)
    audit_append(
        root, run_id, "run_started", {"model": settings.model(), "turns": turns}
    )
    messages: list = [{"role": "user", "content": objective}]
    return _loop(root, client, run_id, messages, instructions, turns)


def resume_run(*, root: Path, run_id: str, client: OpenAI, turns: int = 15) -> dict:
    root = Path(root)
    progress = load_progress(root, run_id)
    step = resume(root, run_id)
    if step["message"] is None:
        return {
            "run_id": run_id,
            "status": step["status"],
            "turn": progress["turn"],
            "note": step["note"],
        }
    instructions = (root / "workspace/runs" / run_id / "instructions.md").read_text()
    audit_append(root, run_id, "run_resumed", {"from_status": progress["status"]})
    messages = list(progress["messages"])
    messages.append({"role": "user", "content": step["message"]})
    return _loop(root, client, run_id, messages, instructions, turns)


def _loop(
    root: Path,
    client: OpenAI,
    run_id: str,
    messages: list,
    instructions: str,
    turns: int,
) -> dict:
    for n in range(turns):
        if n == turns - 1:
            messages.append({"role": "user", "content": LAST_TURN})
        try:
            response = client.responses.create(
                model=settings.model(),
                instructions=instructions,
                input=messages,
                tools=tools.definitions(root, run_id),
                parallel_tool_calls=False,
            )
        except Exception as error:
            add_failure_note(
                root,
                run_id,
                {
                    "turn": _turn_no(root, run_id),
                    "kind": "model_error",
                    "error": str(error)[:200],
                },
            )
            audit_append(
                root,
                run_id,
                "model_error",
                {"turn": _turn_no(root, run_id), "error": str(error)[:200]},
            )
            save_progress(root, run_id, messages, status="paused")
            return _stopped(root, run_id, "paused")
        messages.extend(response.output)
        call = _function_call(response.output)
        if call is None:
            messages.append({"role": "user", "content": NUDGE})
            save_progress(root, run_id, messages, response)
            continue
        result = tools.run(client, root, run_id, call)
        if "error" in result:
            add_failure_note(
                root,
                run_id,
                {
                    "turn": _turn_no(root, run_id),
                    "kind": "tool_error",
                    "tool": _field(call, "name"),
                    "error": str(result["error"])[:200],
                },
            )
        messages.append(
            {
                "type": "function_call_output",
                "call_id": _field(call, "call_id"),
                "output": json.dumps(result),
            }
        )
        status = result.get("status", "running")
        save_progress(root, run_id, messages, response, status=status)
        if status != "running":
            return _stopped(root, run_id, status)
    save_progress(root, run_id, messages, status="paused")
    return _stopped(root, run_id, "paused")


def _turn_no(root: Path, run_id: str) -> int:
    """The 1-based turn about to be saved (cumulative across resumes)."""
    return load_progress(root, run_id)["turn"] + 1


def _result(root: Path, run_id: str, status: str) -> dict:
    return {
        "run_id": run_id,
        "status": status,
        "turn": load_progress(root, run_id)["turn"],
    }


def _stopped(root: Path, run_id: str, status: str) -> dict:
    """End the loop: log the stop, then report it."""
    audit_append(
        root,
        run_id,
        "run_stopped",
        {"status": status, "turn": load_progress(root, run_id)["turn"]},
    )
    return _result(root, run_id, status)


def _function_call(output: list) -> Any | None:
    for item in output:
        if _field(item, "type") == "function_call":
            return item
    return None


def _field(item: Any, key: str) -> Any:
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)
