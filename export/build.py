"""Export content: case records in, titled flows with numbered figures out.

build(root, run_id, what) returns (title, flow, footer) for the Word and PDF
writers, which share the flow blocks. Figures number sequentially in order
of appearance ("Figure 1: ..."); the marking scheme embeds each answer's
figures beside its answer. Missing content (no memo, wrong kind, no plans,
unreadable figure PNG) raises ExportError naming it.
"""

from __future__ import annotations

from pathlib import Path

from edu_kit.case_record import CaseRecord

WHAT = ("scheme", "exam", "marking-scheme", "lesson-plan")

TABLE_HEAD = [
    "Wk", "Pd", "Topic", "Sub-topic", "Objectives",
    "Teaching Methods", "Learning Activities", "References", "Remarks",
]
TABLE_WIDTHS = [0.045, 0.04, 0.10, 0.11, 0.17, 0.12, 0.17, 0.11, 0.135]
TABLE_ALIGN = ["center", "center", "left", "left", "left", "left", "left", "left", "left"]


class ExportError(ValueError):
    """The export cannot be built. Safe to show."""


def build(root: Path, run_id: str, what: str) -> tuple:
    """(title, flow, footer) for one export kind."""
    if what not in WHAT:
        raise ExportError(f"what must be one of {', '.join(WHAT)}")
    root = Path(root)
    record = CaseRecord(root, run_id).data
    memo = record.get("memo")
    if not memo:
        raise ExportError(f"{run_id} has no filed document to export")
    figures = {
        f.get("id"): f for f in record.get("figures", []) if isinstance(f, dict)
    }
    meta = _pack_meta(root, record)
    footer = _footer(meta, run_id)
    if what == "scheme":
        return _scheme(memo, footer, meta, run_id)
    if what == "lesson-plan":
        plans = record.get("lesson_plans") or []
        if not plans:
            raise ExportError(f"{run_id} has no lesson plans to export")
        return _lesson_plans(plans, figures, root, footer, meta)
    if memo.get("kind") != "exam" or not isinstance(memo.get("exam"), dict):
        raise ExportError(f"{run_id} has no filed exam to export")
    if what == "exam":
        return _exam(memo, figures, root, footer, meta)
    return _marking_scheme(memo, figures, root, footer, meta)


def _pack_meta(root: Path, record: dict) -> dict:
    """The run's own pack metadata for titles (empty when unreadable)."""
    try:
        from curriculum.loader import PackError, load_pack

        from edu_kit.tools import pack as pack_loader

        resolved = pack_loader.resolve(root, record.get("pack"))
        if resolved is None:
            return {}
        return load_pack(resolved).get("pack") or {}
    except (PackError, OSError, ValueError):
        return {}


def _subject(meta: dict) -> str:
    if not meta:
        return ""
    return f"Grade {meta.get('grade', '?')} {meta.get('learning_area', '?')}, Term {meta.get('term', '?')}"


def _footer(meta: dict, run_id: str) -> str:
    if not meta:
        return run_id
    return (
        f"Grade {meta.get('grade', '?')} {meta.get('learning_area', '?')} "
        f"({meta.get('curriculum', '?')}) - Term {meta.get('term', '?')} - {run_id}"
    )


def _figure_block(fig_id: str, number: int, figures: dict, root: Path) -> tuple:
    figure = figures.get(fig_id)
    if figure is None:
        raise ExportError(f"unknown figure {fig_id!r}")
    try:
        png = (root / figure["png"]).read_bytes()
    except (OSError, KeyError) as error:
        raise ExportError(f"figure {fig_id} PNG unreadable: {error}") from None
    from diagrams.layout import HEIGHT, WIDTH

    return (
        "figure",
        {
            "png": png,
            "width": WIDTH,
            "height": HEIGHT,
            "caption": f"Figure {number}: {figure.get('caption', figure.get('title', ''))}",
        },
    )


class _Numbering:
    """Sequential figure numbers in order of appearance."""

    def __init__(self, figures: dict, root: Path) -> None:
        self.figures = figures
        self.root = root
        self.count = 0

    def block(self, fig_id: str) -> tuple:
        self.count += 1
        return _figure_block(fig_id, self.count, self.figures, self.root)


def _scheme(memo: dict, footer: str, meta: dict, run_id: str) -> tuple:
    lessons = [r for r in memo.get("lessons") or [] if isinstance(r, dict)]
    if not lessons:
        raise ExportError(
            f"{run_id} scheme has no lesson table: resume the run and file again"
        )
    def _slot(row: dict) -> tuple:
        week, period = row.get("week"), row.get("period")
        return (
            week if isinstance(week, int) else 0,
            period if isinstance(period, int) else 0,
        )

    rows = []
    for row in sorted(lessons, key=_slot):
        objectives = str(row.get("objectives", ""))
        oids = [
            c.get("outcome_id")
            for c in row.get("citations") or []
            if isinstance(c, dict) and c.get("outcome_id")
        ]
        if oids:
            objectives += f" [{', '.join(oids)}]"
        rows.append(
            [
                str(row.get("week", "")),
                str(row.get("period", "")),
                str(row.get("topic", "")),
                str(row.get("subtopic", "")),
                objectives,
                str(row.get("methods", "")),
                str(row.get("activities", "")),
                str(row.get("references", "")),
                str(row.get("remarks", "")),
            ]
        )
    subject = _subject(meta)
    flow: list = [
        ("h1", "Scheme of Work"),
        ("p", f"{subject} - {len(rows)} lessons" if subject else f"{len(rows)} lessons"),
        (
            "table",
            {"head": TABLE_HEAD, "widths": TABLE_WIDTHS, "align": TABLE_ALIGN, "rows": rows},
        ),
        ("h1", "Coverage notes"),
        ("p", memo.get("conclusion", "")),
        ("h1", "Coverage gaps"),
        ("p", memo.get("gaps", "")),
    ]
    title = f"Scheme of Work - {subject}" if subject else "Scheme of Work"
    return title, flow, footer


def _exam(memo: dict, figures: dict, root: Path, footer: str, meta: dict) -> tuple:
    exam = memo.get("exam")
    numbering = _Numbering(figures, root)
    total = (exam.get("blueprint") or {}).get("total_marks", "?")
    flow: list = [
        ("h1", f"Exam ({total} marks)"),
        ("p", memo.get("conclusion", "")),
    ]
    for question in exam.get("questions") or []:
        if not isinstance(question, dict):
            continue
        flow.append(("h2", f"Q{question.get('id')} ({question.get('marks')} marks)"))
        flow.append(("p", question.get("text", "")))
        for fig_id in question.get("figures") or []:
            flow.append(numbering.block(fig_id))
    subject = _subject(meta)
    return f"Exam - {subject}" if subject else "Exam", flow, footer


def _marking_scheme(memo: dict, figures: dict, root: Path, footer: str, meta: dict) -> tuple:
    exam = memo.get("exam")
    numbering = _Numbering(figures, root)
    questions = {
        q.get("id"): q for q in exam.get("questions") or [] if isinstance(q, dict)
    }
    flow: list = [("h1", "Marking scheme")]
    for entry in exam.get("marking_scheme") or []:
        if not isinstance(entry, dict):
            continue
        qid = entry.get("question_id", "?")
        flow.append(("h2", f"Q{qid} ({entry.get('marks')} marks)"))
        flow.append(("p", f"Answer: {entry.get('answer', '')}"))
        for fig_id in (questions.get(qid) or {}).get("figures") or []:
            flow.append(numbering.block(fig_id))
    subject = _subject(meta)
    return f"Marking Scheme - {subject}" if subject else "Marking Scheme", flow, footer


def _lesson_plans(plans: list, figures: dict, root: Path, footer: str, meta: dict) -> tuple:
    numbering = _Numbering(figures, root)
    flow: list = []
    for plan in plans:
        flow.append(("h1", f"Week {plan.get('week', '?')} ({plan.get('id', '?')})"))
        for lesson in plan.get("lessons") or []:
            if not isinstance(lesson, dict):
                continue
            rows = ", ".join(lesson.get("items") or [])
            flow.append(("h2", f"{lesson.get('day', '?')} - {rows}"))
            for activity in lesson.get("activities") or []:
                flow.append(
                    ("bullet", f"{activity.get('title', '')} ({activity.get('minutes', '?')} min)")
                )
            for fig_id in lesson.get("figures") or []:
                flow.append(numbering.block(fig_id))
    subject = _subject(meta)
    return f"Lesson Plans - {subject}" if subject else "Lesson Plans", flow, footer
