"""submit_document: file the scheme-of-work document (or an exam document).

Verification off: the document is filed unverified and the run ends (answered).
Verification on: the scheme rules (verification/verify_scheme.py) run first,
then the claims check (verification/verify_claims.py). A document that fails
is refused with the problems; after MAX_REFUSALS refused documents the run
escalates to a person with reason code document_refused. A document that
passes both waits for teacher sign-off (awaiting_signoff); kind "exam" also
needs head-of-department review afterwards.

Kind "exam" additionally carries the exam payload (blueprint, questions,
marking_scheme), checked by exams/validate.py: blueprint counts and marks
match the questions, every total adds up, every question has one scheme
entry, and the wording is original. Check answers first with check_answers.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from ..document_text import normalize

if TYPE_CHECKING:
    from . import Context

MAX_REFUSALS = 3
KINDS = ("scheme", "exam")

ITEM = {
    "type": "string",
    "description": "id of an item in your checklist (set_checklist)",
}
CITATION = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "outcome_id": {"type": "string"},
        "quote": {"type": "string"},
    },
    "required": ["outcome_id", "quote"],
}
FINDING = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "item": ITEM,
        "status": {"type": "string", "enum": ["proven", "not_proven", "escalated"]},
        "summary": {"type": "string"},
        "citations": {"type": "array", "items": CITATION, "maxItems": 3},
    },
    "required": ["item", "status", "summary", "citations"],
}
# One row of the week-by-week lesson table: week and period pin the slot,
# item ties it to a checklist item, the seven cells are the table columns.
LESSON_CELLS = (
    "topic",
    "subtopic",
    "objectives",
    "methods",
    "activities",
    "references",
    "remarks",
)
LESSON = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "week": {"type": "integer"},
        "period": {"type": "integer"},
        "item": ITEM,
        **{cell: {"type": "string"} for cell in LESSON_CELLS},
        "citations": {"type": "array", "items": CITATION, "maxItems": 3},
    },
    "required": ["week", "period", "item", *LESSON_CELLS],
}

DEFINITION = {
    "type": "function",
    "name": "submit_document",
    "description": "File the document: the term plan in 2-3 sentences, one finding per checklist "
    "item in one sentence citing its recorded citations, the remaining gaps as a short list, and (kind scheme) "
    "the week-by-week lesson table: one row per week and period, every slot exactly once, cells in 1-2 sentences. "
    "File only when every item is covered or escalated.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "conclusion": {"type": "string"},
            "findings": {"type": "array", "items": FINDING},
            "gaps": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": ["scheme", "exam"],
                "description": "scheme (default) or exam (needs head-of-department review)",
            },
            "lessons": {
                "type": "array",
                "items": LESSON,
                "description": "required for kind scheme: the week-by-week lesson table",
            },
            "exam": {
                "type": "object",
                "description": "required for kind exam: {blueprint: {total_marks, sections: "
                "[{outcome_id, questions, marks_each}]}, questions: [{id, text, marks, answer, "
                "outcome_id}], marking_scheme: [{question_id, answer, marks}]}",
            },
        },
        "required": ["conclusion", "findings", "gaps"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    document = {
        "conclusion": str(args.get("conclusion", "")),
        "findings": args.get("findings") or [],
        "gaps": str(args.get("gaps", "")),
        "kind": str(args.get("kind") or "scheme"),
    }
    if args.get("exam") is not None:
        document["exam"] = args["exam"]
    if args.get("lessons") is not None:
        document["lessons"] = args["lessons"]
    if not ctx.verification:
        problems = check(ctx, document)
        if problems:
            return {"error": "document refused", "problems": problems}
        ctx.case.file_memo(document, "unverified")
        return {"filed": True, "document": "unverified", "status": "answered"}
    from verification import verify_claims

    from .escalate import escalate_request

    verify_scheme = importlib.import_module("verification.verify_scheme")
    name, result = "scheme", verify_scheme.run_verification(ctx, document)
    if result.get("passed"):
        ctx.case.record_memo_check("scheme", [])
        name, result = "claims", verify_claims.run_verification(ctx, document)
    problems = (
        []
        if result.get("passed")
        else [str(p) for p in result.get("feedback") or ["refused"]]
    )
    ctx.case.record_memo_check(name, problems)
    if problems:
        if ctx.case.memo_refusals() >= MAX_REFUSALS:
            checklist = ctx.case.data["checklist"]
            item = next(
                (k for k, v in checklist.items() if v["status"] == "open"),
                next(iter(checklist), ""),
            )
            need = (
                f"The document was refused {ctx.case.memo_refusals()} times. Last problems: "
                + "; ".join(problems)
            )
            return escalate_request(ctx, item, need, "document_refused")
        return {"error": "document refused", "check": name, "problems": problems}
    ctx.case.file_memo(document, "awaiting_signoff")
    return {"filed": True, "document": "awaiting_signoff", "status": "awaiting_signoff"}


def check(ctx: Context, document: dict) -> list:
    """Every inconsistency between the document and the record, as problems."""
    problems = []
    if document.get("kind") not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}")
    if not str(document.get("conclusion", "")).strip():
        problems.append("conclusion is empty")
    if not str(document.get("gaps", "")).strip():
        problems.append("gaps is empty: name what remains, or say there is none")
    findings = document.get("findings")
    if not isinstance(findings, list) or not findings:
        return problems + ["findings must be a non-empty list"]
    checklist = ctx.case.data["checklist"]
    if not checklist:
        return problems + ["there is no checklist yet: call set_checklist first"]
    seen: set[str] = set()
    quotes = {
        (fact["item"], normalize(fact.get("quote", "")))
        for fact in ctx.case.data["facts"]
    }
    for raw in findings:
        if not isinstance(raw, dict):
            problems.append("each finding must be an object")
            continue
        item = str(raw.get("item", ""))
        if item in seen:
            problems.append(f"duplicate finding for {item}")
        seen.add(item)
        if item not in checklist:
            problems.append(f"unknown checklist item {item!r}")
            continue
        if raw.get("status") not in ("proven", "not_proven", "escalated"):
            problems.append(f"{item}: status must be proven, not_proven, or escalated")
        if not str(raw.get("summary", "")).strip():
            problems.append(f"{item}: summary is empty")
        citations = raw.get("citations") or []
        if raw.get("status") == "proven" and not citations:
            problems.append(f"{item}: a proven finding needs at least one citation")
        for citation in citations:
            quote = normalize(str((citation or {}).get("quote", "")))
            if (item, quote) not in quotes:
                problems.append(
                    f"{item}: citation does not match a recorded citation: "
                    f"{str((citation or {}).get('quote', ''))[:60]}"
                )
    missing = [k for k in checklist if k not in seen]
    if missing:
        problems.append(f"no finding for checklist item(s): {', '.join(missing)}")
    if document.get("kind") == "exam":
        problems.extend(_exam_problems(ctx, document, findings))
    elif document.get("exam") is not None:
        problems.append("exam payload needs kind exam")
    else:
        problems.extend(_lesson_problems(ctx, document))
    return problems


def _grid(ctx: Context) -> tuple:
    """(weeks, periods) the lesson table must fill exactly.

    Weeks come from the pack, periods from the timetable; the defaults
    cover roots without either. Capped so corrupt data cannot demand an
    absurd table.
    """
    from curriculum.loader import PackError

    from lessons.validate import TimetableError, load_timetable

    from . import pack as pack_loader

    weeks, periods = 12, 5
    try:
        weeks = int(pack_loader.load(ctx).get("term", {}).get("weeks") or 12)
    except (PackError, ValueError, TypeError):
        pass
    try:
        table = load_timetable(ctx.root).get("timetable", {})
        periods = int(table.get("lessons_per_week") or 5)
    except (TimetableError, ValueError, TypeError, AttributeError):
        pass
    return min(max(weeks, 1), 52), min(max(periods, 1), 10)


def _lesson_problems(ctx: Context, document: dict) -> list:
    """Kind-scheme problems: the week-by-week lesson table.

    One row per pack week and timetable period, every slot exactly once;
    rows tie to checklist items and cite only recorded citations. Skipped
    on roots without a teaching pack (the finding-only document stays).
    """
    from . import pack as pack_loader

    if not pack_loader.exists(ctx.root):
        return []
    lessons = document.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        return ["kind scheme needs a lessons table: one row per week and period"]
    weeks, periods = _grid(ctx)
    checklist = ctx.case.data["checklist"]
    quotes = {
        (fact["item"], normalize(fact.get("quote", "")))
        for fact in ctx.case.data["facts"]
    }
    problems, seen = [], set()
    for n, raw in enumerate(lessons, start=1):
        tag = f"lesson row {n}"
        if not isinstance(raw, dict):
            problems.append(f"{tag} must be an object")
            continue
        week, period = raw.get("week"), raw.get("period")
        slot_ok = True
        if not isinstance(week, int) or isinstance(week, bool) or not 1 <= week <= weeks:
            problems.append(f"{tag}: week must be an integer 1..{weeks}")
            slot_ok = False
        if (
            not isinstance(period, int)
            or isinstance(period, bool)
            or not 1 <= period <= periods
        ):
            problems.append(f"{tag}: period must be an integer 1..{periods}")
            slot_ok = False
        if slot_ok:
            if (week, period) in seen:
                problems.append(f"duplicate lesson row for week {week} period {period}")
            seen.add((week, period))
        item = str(raw.get("item", ""))
        if item not in checklist:
            problems.append(f"{tag}: unknown checklist item {item!r}")
            continue
        for cell in LESSON_CELLS:
            if not str(raw.get(cell, "")).strip():
                problems.append(f"{tag}: {cell} is empty")
        for citation in raw.get("citations") or []:
            entry = citation if isinstance(citation, dict) else {}
            quote = normalize(str(entry.get("quote", "")))
            if (item, quote) not in quotes:
                problems.append(
                    f"{tag}: citation does not match a recorded citation: "
                    f"{str(entry.get('quote', ''))[:60]}"
                )
    missing = [(w, p) for w in range(1, weeks + 1) for p in range(1, periods + 1)
               if (w, p) not in seen]
    if missing:
        shown = ", ".join(f"week {w} period {p}" for w, p in missing[:6])
        problems.append(f"lessons table is missing {len(missing)} slots, e.g. {shown}")
    return problems


def _exam_problems(ctx: Context, document: dict, findings: list) -> list:
    """Kind-exam problems: the exam payload against the pack and the record."""
    from curriculum.loader import PackError

    from exams.validate import validate_exam

    from . import pack as pack_loader

    payload = document.get("exam")
    if not isinstance(payload, dict):
        return ["kind exam needs an exam payload (blueprint, questions, marking_scheme)"]
    try:
        pack = pack_loader.load(ctx)
    except PackError as error:
        return [f"curriculum pack unreadable: {error}"]
    outcome_ids, outcome_texts = set(), []
    for strand in pack.get("strands", []):
        for sub in strand.get("sub_strands", []):
            for outcome in sub.get("outcomes", []):
                outcome_ids.add(outcome.get("id"))
                if outcome.get("status") == "transcribed":
                    outcome_texts.append(
                        {"id": outcome.get("id"), "text": outcome.get("outcome_text", "")}
                    )
    figures = {
        f.get("id") for f in ctx.case.data.get("figures", []) if isinstance(f, dict)
    }
    summaries = [
        (f.get("item", "?"), f.get("summary", ""))
        for f in findings
        if isinstance(f, dict)
    ]
    return validate_exam(payload, outcome_ids, outcome_texts, figures, summaries)
