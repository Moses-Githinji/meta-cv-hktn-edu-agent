"""The memo rules. run_verification is not implemented yet.

Called when the agent calls submit_memo with VERIFICATION=on, and by
./helper verify RUN --memo.

    run_verification(ctx, memo) -> {"passed": bool, "feedback": [problem, ...]}

memo = {"conclusion": str, "findings": [{"item", "status", "summary", "citations": [
{"document_id", "page", "quote"}]}], "gaps": str}. ctx.case is the run's CaseRecord:
case.data["checklist"], case.data["facts"], case.data["signature_checks"] (each with
document_id, page, verdict), case.flagged(document_id), case.open_requests(). Compare
quotes with edu_kit.document_text.normalize.

Rules (one problem string per break, which the agent reads and fixes; passed = no problems):
- every checklist item has a finding, and is proven or escalated (status "open" is a problem);
- a finding marked "proven" has a recorded fact for its item, and cites at least one;
- every citation matches a recorded fact (same document, page, and quote);
- no citation is from a document flagged confidential;
- an item with needs_signature_check that is marked proven has a signature check on a
  document it cites, and every such check's verdict is "consistent" (otherwise the item
  is not proven: say so, and name it as a gap);
- no evidence request is still open.
"""

from __future__ import annotations

from edu_kit.document_text import normalize


def run_verification(ctx, memo: dict) -> dict:
    case = ctx.case
    checklist = case.data["checklist"]
    facts = case.data["facts"]
    findings = {
        f["item"]: f
        for f in memo.get("findings") or []
        if isinstance(f, dict) and f.get("item")
    }
    problems: list[str] = []

    def matches(fact: dict, citation: dict) -> bool:
        return (
            fact["document_id"] == citation.get("document_id")
            and fact["page"] == citation.get("page")
            and normalize(fact["quote"]) == normalize(citation.get("quote") or "")
        )

    for item, entry in checklist.items():
        finding = findings.get(item)
        if finding is None:
            problems.append(f"no finding for {item}")
        if entry.get("status") == "open":
            problems.append(f"{item} is neither proven nor escalated in the case record")
        if finding is not None and finding.get("status") == "proven":
            item_facts = [f for f in facts if f["item"] == item]
            citations = finding.get("citations") or []
            if not item_facts:
                problems.append(f"{item} is marked proven but has no recorded fact")
            elif not any(
                matches(f, c) for c in citations for f in item_facts
            ):
                problems.append(
                    f"{item} is marked proven but cites none of its recorded facts"
                )

    for item, finding in findings.items():
        for citation in finding.get("citations") or []:
            doc = citation.get("document_id")
            if case.flagged(doc):
                problems.append(
                    f"{item} cites {doc}, which is flagged confidential "
                    "and can never be cited"
                )
            if not any(matches(f, citation) for f in facts):
                problems.append(
                    f"{item} cites {doc} p{citation.get('page')} "
                    "with no matching recorded fact"
                )

    for item, finding in findings.items():
        if not checklist.get(item, {}).get("needs_signature_check"):
            continue
        if finding.get("status") != "proven":
            continue
        cited = {c.get("document_id") for c in finding.get("citations") or []}
        checks = [
            s for s in case.data["signature_checks"] if s.get("document_id") in cited
        ]
        if not checks:
            problems.append(
                f"{item} needs a signature check but no cited document was checked"
            )
        for check in checks:
            if check.get("verdict") != "consistent":
                problems.append(
                    f"{item}: the signature check on {check['document_id']} "
                    f"p{check['page']} is {check['verdict']}, so {item} is "
                    "not proven; name it as a gap"
                )

    for request in case.open_requests():
        problems.append(
            f"evidence request is still open: {request['id']} ({request['item']})"
        )

    return {"passed": not problems, "feedback": problems}
