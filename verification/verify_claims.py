"""Is each finding supported by the quotes it cites?

Called by the submit_memo tool after verify_memo passes, by the
submit_document tool after verify_scheme passes, and by ./helper verify.

    run_verification(ctx, memo, judge=None) -> {"passed": bool, "feedback": [problem, ...]}

One judge call assesses every proven finding against its quotes. The judge
fails closed: an unreadable judgement refuses the document instead of
passing it. `judge` overrides the judge model (independent verification
uses a different model from the agent); by default it is the agent model.
"""

from __future__ import annotations

import json
from typing import cast

from edu_kit.settings import model
from openai.types.responses import Response

PROMPT = """CLAIMS TO CHECK. Each finding below states a claim and the exact quotes cited for it.
For each finding, decide whether the quotes support the claim as written. A claim that goes
beyond what its quotes say is unsupported.

{findings}

Answer only with JSON: {{"unsupported": [{{"item": "<item>", "reason": "one sentence"}}]}}
(an empty list when every claim is supported)."""


UNREADABLE = "the claims judge could not be read; refile the document"


def run_verification(ctx, memo: dict, judge: str | None = None) -> dict:
    findings = [
        {
            "item": f.get("item"),
            "claim": f.get("summary", ""),
            "quotes": [c.get("quote", "") for c in f.get("citations") or []],
        }
        for f in memo.get("findings") or []
        if isinstance(f, dict) and f.get("status") == "proven" and f.get("citations")
    ]
    if not findings:
        return {"passed": True, "feedback": []}
    response = cast(
        Response,
        ctx.client.responses.create(
            model=judge or model(),
            input=PROMPT.format(findings=json.dumps(findings, indent=1)),
            text={"format": {"type": "json_object"}},
        ),
    )
    try:
        unsupported = json.loads(response.output_text).get("unsupported")
    except (ValueError, AttributeError):
        return {"passed": False, "feedback": [UNREADABLE]}  # fail closed
    if not isinstance(unsupported, list):
        return {"passed": False, "feedback": [UNREADABLE]}  # fail closed
    problems = [
        f"{u.get('item')}: the finding is not supported by its quotes ({u.get('reason', '')})"
        for u in unsupported
        if isinstance(u, dict)
    ]
    return {"passed": not problems, "feedback": problems}
