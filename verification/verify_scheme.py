"""The scheme rules: is the filed document consistent with the record and the pack?

Called when the agent calls submit_document with VERIFICATION=on, and by
./helper verify RUN --memo and independent verification on teaching runs.

    run_verification(ctx, document) -> {"passed": bool, "feedback": [problem, ...]}

document = {"conclusion": str, "findings": [{"item", "status",
"summary", "citations": [{"outcome_id", "quote"}]}], "gaps": str, "kind": str,
"lessons": [{"week", "period", "item", cells, "citations"}] for kind scheme}.
ctx.case is the run's CaseRecord.

Rules (one problem string per break, which the agent reads and fixes;
passed = no problems):

- the document shape rules (conclusion and gaps non-empty, one finding per
  checklist item, proven findings cite recorded citations, and for kind
  scheme the full lesson table: one row per week and period, every slot
  exactly once) — shared with the verification-off path via
  edu_kit.tools.submit_document.check;
- every checklist item is proven or escalated in the record (no open items);
- every recorded citation still matches the pack's exact outcome text;
- no teacher question or escalation is still open.
"""

from __future__ import annotations

from curriculum.loader import PackError, find_outcome
from edu_kit import document_text
from edu_kit.tools import pack as pack_loader


def run_verification(ctx, document: dict) -> dict:
    from edu_kit.tools.submit_document import check

    problems = check(ctx, dict(document))
    case = ctx.case
    for item, entry in case.data["checklist"].items():
        if entry.get("status") == "open":
            problems.append(
                f"{item} is still open in the record: cite it or escalate it"
            )
    try:
        pack = pack_loader.load(ctx)
    except PackError as error:
        return {"passed": False, "feedback": problems + [f"curriculum pack unreadable: {error}"]}
    for fact in case.data["facts"]:
        outcome_id = fact.get("outcome_id")
        if not outcome_id:
            continue
        found = find_outcome(pack, outcome_id)
        if found is None:
            problems.append(
                f"{fact['item']}: cited outcome {outcome_id} is not in the pack"
            )
        elif found["status"] != "transcribed":
            problems.append(
                f"{fact['item']}: cited outcome {outcome_id} is not transcribed"
            )
        elif not document_text.quote_on_page(
            fact.get("quote", ""), found["outcome_text"]
        ):
            problems.append(
                f"{fact['item']}: recorded citation is not the exact text of {outcome_id}"
            )
    for request in case.open_requests():
        problems.append(
            f"request {request['id']} ({request['item']}) is still open: "
            "wait for the answer before filing"
        )
    return {"passed": not problems, "feedback": problems}
