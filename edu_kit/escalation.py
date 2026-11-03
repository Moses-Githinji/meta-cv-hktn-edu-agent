"""Escalation reason codes: why a run stops for a person.

Every request a tool opens names one code (CaseRecord.open_request refuses
anything else). The code tells the reviewer what happened and what unblocks
the run; see ESCALATION_RULES.md.
"""

from __future__ import annotations

REASON_CODES = {
    "teacher_input": {
        "description": "The agent asked the teacher a question it cannot answer from the pack.",
        "unblocks": "Answer the question (./helper review RUN --answer R1 --notes ...), then resume.",
    },
    "missing_outcome_text": {
        "description": "A term outcome is still pending transcription, so coverage cannot be confirmed.",
        "unblocks": "Transcribe the outcome into the pack, or confirm it stays a gap, then resume.",
    },
    "timetable_clash": {
        "description": "The planned coverage does not fit the week's timetable slots.",
        "unblocks": "Confirm the real slots or re-plan around them, then resume.",
    },
    "calendar_clash": {
        "description": "The plan conflicts with the term calendar (half-term, closing, catch-up days).",
        "unblocks": "Confirm the calendar dates, then resume.",
    },
    "document_refused": {
        "description": "The document was refused 3 times by the inline checks.",
        "unblocks": "Reply with guidance (./helper review RUN --answer Rn --notes ...), then resume.",
    },
    "exam_signoff": {
        "description": "An exam document needs head-of-department review before use.",
        "unblocks": "The head of department reviews (./helper review RUN --hod-approve ...).",
    },
    "missing_evidence": {
        "description": "Legal follow-up: a checklist item cannot be proven from the visible documents.",
        "unblocks": "Release documents into the inbox, or reply, then resume.",
    },
    "memo_refused": {
        "description": "Legal follow-up: the memo was refused 3 times.",
        "unblocks": "Reply with guidance, then resume.",
    },
}


def check(rule: str) -> str:
    """The rule, or raise ValueError naming the valid codes."""
    if rule not in REASON_CODES:
        raise ValueError(
            f"unknown reason code {rule!r}; valid codes: {', '.join(REASON_CODES)}"
        )
    return rule
