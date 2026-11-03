"""Does the agent's checklist cover what the case needs? run_verification is not implemented yet.

Called when the agent calls set_checklist with VERIFICATION=on, and by
./helper verify RUN --checklist.

    run_verification(ctx, items) -> {"passed": bool, "score": float, "feedback": str}

- items: the agent's checklist items: [{"id", "question", "evidence_needed", ...}, ...]
- load_reference(ctx.root) (pre-built, below) returns the case's ground truth,
  [{"id": "...", "question": "..."}, ...], or None when the case has none (then the
  checklist passes).

1. Ask Muse Spark (ctx.client.responses.create, JSON output) to mark each reference item
   covered or not by some agent item, even if worded differently, and to write feedback.
2. score = covered reference items / all reference items; passed = every one is covered.
3. feedback: what kind of question the checklist is missing, and any item that only
   restates background. It goes to the agent, so it must point to the direction only:
   never quote, paraphrase, or count the reference items. Empty when it passes.

Only passed and feedback reach the agent; the score is shown in the console.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from edu_kit.settings import teaching_pack_dir, model
from openai.types.responses import Response

# ---- pre-built: the ground truth (don't change) ----------------------------------------
# It lives outside this folder (GROUND_TRUTH_DIR, default ../ground_truth), one
# <case folder name>.json per case. Read it only through load_reference.


def reference_path(root: Path) -> Path:
    folder = Path(os.environ.get("GROUND_TRUTH_DIR") or "../ground_truth").expanduser()
    if not folder.is_absolute():
        folder = (Path(root) / folder).resolve()
    return folder / f"{teaching_pack_dir(root).name}.json"


def load_reference(root: Path) -> list | None:
    """The case's ground-truth items, or None if the case has none."""
    path = reference_path(root)
    return json.loads(path.read_text())["items"] if path.is_file() else None


# ---- yours ---------------------------------------------------------------------------


PROMPT = """REFERENCE CHECKLIST. A good investigation of this case must answer every reference question below. Mark each one covered or not: covered when some agent item asks the same question, even if worded differently.

Reference questions:
{reference}

Agent checklist:
{agent}

Answer only with JSON: {{"covered": {{"<reference id>": true}}, "feedback": "<text>"}}. Feedback goes to the agent: say what kind of question is missing, and flag any agent item that only restates background. Never quote, paraphrase, count, or name the reference questions. Empty feedback when every reference question is covered."""

GENERIC_FEEDBACK = (
    "The checklist leaves out an area the case turns on. Look again at what "
    "the question needs and what evidence would settle it."
)


def run_verification(ctx, items: list) -> dict:
    reference = load_reference(ctx.root)
    if not reference:
        return {"passed": True, "score": None, "feedback": ""}
    response = cast(
        Response,
        ctx.client.responses.create(
            model=model(),
            input=PROMPT.format(
                reference=json.dumps(reference, indent=1),
                agent=json.dumps(items, indent=1),
            ),
            text={"format": {"type": "json_object"}},
        ),
    )
    try:
        judgement = json.loads(response.output_text)
    except (ValueError, AttributeError):
        judgement = {}
    covered = judgement.get("covered")
    if not isinstance(covered, dict):
        covered = {}
    done = sum(1 for ref in reference if covered.get(ref.get("id")))
    passed = done == len(reference)
    feedback = ""
    if not passed:
        feedback = str(judgement.get("feedback") or "").strip() or GENERIC_FEEDBACK
    return {"passed": passed, "score": round(done / len(reference), 2), "feedback": feedback}
