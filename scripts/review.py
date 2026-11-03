#!/usr/bin/env python3
"""The review console: a person reviews the filed document (not the agent).

    ./helper review RUN_ID --list [--json]
    ./helper review RUN_ID --item ITEM --approve | --reject --notes "what to fix"
    ./helper review RUN_ID --item ITEM --edit --notes "corrected finding summary"
    ./helper review RUN_ID --approve [--notes "..."]
    ./helper review RUN_ID --reject --notes "what to fix"
    ./helper review RUN_ID --hod-approve [--notes "..."]       # exam documents only
    ./helper review RUN_ID --hod-reject --notes "what to fix"  # exam documents only
    ./helper review RUN_ID --answer R1 --notes "reply to the request"

--list shows one row per checklist item with the curriculum text beside it:
each cited outcome's exact wording, or its pending-transcription marker.
Item verdicts are stored on the document; --edit also replaces the filed
finding summary. Approving an exam document moves it to await the head of
department; other documents are done once the teacher approves.

Then resume the same run: ./helper run --resume RUN_ID
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from curriculum.loader import PackError, find_outcome, load_pack  # noqa: E402
from edu_kit.case_record import CaseError, CaseRecord  # noqa: E402
from edu_kit.tools import pack as pack_loader  # noqa: E402
from verification.verify_teaching_checklist import referenced_outcomes  # noqa: E402


def item_rows(root: Path, run_id: str) -> list:
    """One row per checklist item: the finding, its review, and the curriculum text beside it."""
    case = CaseRecord(root, run_id)
    try:
        resolved = pack_loader.resolve(root, case.data.get("pack"))
        pack = load_pack(resolved) if resolved else None
    except PackError:
        pack = None
    memo = case.data.get("memo") or {}
    findings = {
        f["item"]: f
        for f in memo.get("findings") or []
        if isinstance(f, dict) and f.get("item")
    }
    facts_by_item: dict[str, list] = {}
    for fact in case.data.get("facts") or []:
        facts_by_item.setdefault(fact.get("item", ""), []).append(fact)
    rows = []
    for item, entry in case.data["checklist"].items():
        outcome_ids = _outcome_ids(pack, entry, findings.get(item), facts_by_item.get(item, []))
        rows.append(
            {
                "item": item,
                "status": entry.get("status"),
                "question": entry.get("question"),
                "finding": findings.get(item),
                "review": (memo.get("item_reviews") or {}).get(item),
                "curriculum": [
                    _curriculum_entry(pack, oid) for oid in outcome_ids
                ],
            }
        )
    return rows


def _outcome_ids(pack: dict | None, entry: dict, finding: dict | None, facts: list) -> list:
    """Outcome ids for a row: cited first (pack order), then ids only named in the item text."""
    cited = []
    for source in [finding] + facts:
        for citation in (source or {}).get("citations") or []:
            oid = (citation or {}).get("outcome_id")
            if oid and oid not in cited:
                cited.append(oid)
    for fact in facts:
        oid = fact.get("outcome_id")
        if oid and oid not in cited:
            cited.append(oid)
    named: set[str] = set()
    if pack is not None:
        text = f"{entry.get('question', '')} {entry.get('evidence_needed', '')}"
        named = referenced_outcomes(pack, text)
    ordered = sorted(
        set(cited) | named,
        key=lambda oid: (
            0 if oid in cited else 1,
            _pack_index(pack, oid),
            oid,
        ),
    )
    return ordered


def _pack_index(pack: dict | None, outcome_id: str) -> int:
    if not pack:
        return 0
    ids = [
        outcome["id"]
        for strand in pack.get("strands", [])
        for sub in strand.get("sub_strands", [])
        for outcome in sub.get("outcomes", [])
    ]
    return ids.index(outcome_id) if outcome_id in ids else len(ids)


def _curriculum_entry(pack: dict | None, outcome_id: str) -> dict:
    if pack is None:
        return {"outcome_id": outcome_id, "status": "pack_missing", "outcome_text": None}
    found = find_outcome(pack, outcome_id)
    if found is None:
        return {"outcome_id": outcome_id, "status": "unknown", "outcome_text": None}
    return {
        "outcome_id": outcome_id,
        "status": found["status"],
        "outcome_text": found["outcome_text"] if found["status"] == "transcribed" else None,
        "sub_strand": found["sub_strand"],
        "week_range": found["week_range"],
    }


def render(rows: list) -> str:
    """The rows as aligned console text: item, verdict, finding, curriculum text."""
    lines = [f"{'ITEM':<16}{'STATUS':<11}{'FINDING':<44}CURRICULUM"]
    for row in rows:
        finding = row["finding"] or {}
        summary = str(finding.get("summary", "—"))
        review = row["review"] or {}
        status = row["status"] or "?"
        if review.get("decision"):
            status += f" ({review['decision']})"
        curriculum = row["curriculum"]
        if not curriculum:
            lines.append(f"{row['item']:<16}{status:<11}{_clip(summary, 42):<44}—")
            continue
        for n, entry in enumerate(curriculum):
            text = entry["outcome_text"] or f"[{entry['status']}]"
            cell = f"[{entry['outcome_id']}] {text}"
            if n == 0:
                lines.append(
                    f"{row['item']:<16}{status:<11}{_clip(summary, 42):<44}{_clip(cell, 80)}"
                )
            else:
                lines.append(f"{'':<16}{'':<11}{'':<44}{_clip(cell, 80)}")
    return "\n".join(lines)


def _clip(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_id")
    parser.add_argument("--list", action="store_true", help="show one row per item")
    parser.add_argument("--json", action="store_true", help="print rows as JSON")
    parser.add_argument("--item", metavar="ITEM", help="review one checklist item")
    parser.add_argument("--edit", action="store_true", help="replace the finding summary")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--reject", action="store_true")
    parser.add_argument("--hod-approve", action="store_true")
    parser.add_argument("--hod-reject", action="store_true")
    parser.add_argument("--answer", metavar="REQUEST_ID")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    if not (ROOT / "workspace/case_records" / f"{args.run_id}.json").is_file():
        parser.error(f"no case record for {args.run_id}")
    try:
        if args.list:
            rows = item_rows(ROOT, args.run_id)
            print(json.dumps(rows, indent=2) if args.json else render(rows))
            return
        case = CaseRecord(ROOT, args.run_id)
        if args.item:
            decisions = [
                d
                for d, flag in (
                    ("approved", args.approve),
                    ("rejected", args.reject),
                    ("edited", args.edit),
                )
                if flag
            ]
            if len(decisions) != 1:
                parser.error("--item needs exactly one of --approve, --reject, --edit")
            result = case.review_item(args.item, decisions[0], args.notes)
            print(json.dumps({"item": args.item, **result}, indent=2))
        elif args.hod_approve or args.hod_reject:
            if args.hod_approve and args.hod_reject:
                parser.error("choose one of --hod-approve, --hod-reject")
            if args.hod_reject and not args.notes:
                parser.error("--hod-reject needs --notes saying what to fix")
            result = case.hod_review(args.hod_approve, args.notes)
            print(json.dumps({"kind": "exam", "status": result["status"]}, indent=2))
        elif args.answer:
            result = case.answer_request(
                args.answer, args.notes or "Answered by reviewer."
            )
            print(json.dumps({"id": result["id"], "response": result["response"]}, indent=2))
        else:
            if not (args.approve or args.reject):
                parser.error("choose what to review (see --help)")
            if args.approve and args.reject:
                parser.error("choose one of --approve, --reject")
            if args.reject and not args.notes:
                parser.error("--reject needs --notes saying what to fix")
            result = case.review_memo(args.approve, args.notes)
            print(json.dumps({"status": result["status"], "review": result["review"]}, indent=2))
            if result["status"] == "awaiting_hod":
                print("Teacher approved; now the head of department must review (exam).")
                return
    except (CaseError, PackError) as error:
        parser.error(str(error))
    print(f"Now resume the same run: ./helper run --resume {args.run_id}")


if __name__ == "__main__":
    main()
