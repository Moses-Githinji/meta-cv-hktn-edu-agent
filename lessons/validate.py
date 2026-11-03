"""Lesson plans: validate a week's lessons against the approved scheme.

A lesson plan ties each lesson to approved scheme rows (checklist items the
reviewer approved or edited) and fits its activities into a real timetable
slot: activity minutes must sum exactly to the slot's minutes. Weeks are
pack weeks (1..term weeks); days and slot lengths come from
teacher_context/timetable.json.
"""

from __future__ import annotations

import json
from pathlib import Path

APPROVED_VERDICTS = ("approved", "edited")


class TimetableError(ValueError):
    """The timetable is missing or unreadable."""


def load_timetable(root: Path) -> dict:
    """teacher_context/timetable.json: days, slots, and minutes per lesson."""
    path = Path(root) / "teacher_context" / "timetable.json"
    if not path.is_file():
        raise TimetableError(f"no timetable at {path}")
    try:
        return json.loads(path.read_text())
    except ValueError as error:
        raise TimetableError(f"timetable unreadable: {error}") from None


def day_minutes(timetable: dict, day: str) -> int | None:
    """A day's mathematics minutes, or None when the day has no slot."""
    table = timetable.get("timetable", timetable)
    per_lesson = table.get("minutes_per_lesson", 0)
    total = 0
    for slot in table.get("slots", []):
        if not isinstance(slot, dict) or slot.get("day") != day:
            continue
        total += len(slot.get("lessons") or []) * per_lesson
    return total if total > 0 else None


def validate_plan(plan: dict, record: dict, timetable: dict, pack_weeks: int) -> list:
    """Every problem with a lesson plan (empty = valid)."""
    problems = []
    if not isinstance(plan, dict):
        return ["lesson plan must be an object"]
    week = plan.get("week")
    if not isinstance(week, int) or isinstance(week, bool) or not 1 <= week <= pack_weeks:
        problems.append(f"week must be an integer 1..{pack_weeks}")
    lessons = plan.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        return problems + ["lessons must be a non-empty list"]
    checklist = record.get("checklist", {})
    memo = record.get("memo") or {}
    reviews = memo.get("item_reviews") or {}
    figures = {f.get("id") for f in record.get("figures", []) if isinstance(f, dict)}
    for n, lesson in enumerate(lessons, start=1):
        problems.extend(_lesson(n, lesson, checklist, reviews, figures, timetable))
    return problems


def _lesson(
    n: int,
    lesson: dict,
    checklist: dict,
    reviews: dict,
    figures: set,
    timetable: dict,
) -> list:
    tag = f"lesson {n}"
    if not isinstance(lesson, dict):
        return [f"{tag} must be an object"]
    problems = []
    minutes = day_minutes(timetable, lesson.get("day", ""))
    if minutes is None:
        problems.append(f"{tag}: {lesson.get('day')!r} has no mathematics slot")
    items = lesson.get("items")
    if not isinstance(items, list) or not items:
        problems.append(f"{tag}: items must name at least one scheme row")
    else:
        for item in items:
            if item not in checklist:
                problems.append(f"{tag}: unknown scheme row {item!r}")
            elif (reviews.get(item) or {}).get("decision") not in APPROVED_VERDICTS:
                problems.append(
                    f"{tag}: scheme row {item} is not approved yet"
                )
    activities = lesson.get("activities")
    if not isinstance(activities, list) or not activities:
        problems.append(f"{tag}: activities must be a non-empty list")
    else:
        total = 0
        for activity in activities:
            if not isinstance(activity, dict):
                problems.append(f"{tag}: each activity must be an object")
                continue
            if not str(activity.get("title", "")).strip():
                problems.append(f"{tag}: activity title is empty")
            mins = activity.get("minutes")
            if not isinstance(mins, int) or isinstance(mins, bool) or mins <= 0:
                problems.append(
                    f"{tag}: activity {activity.get('title', '?')!r} needs positive integer minutes"
                )
            else:
                total += mins
        if minutes is not None and total != minutes:
            problems.append(
                f"{tag}: activities sum to {total} minutes, "
                f"but the {lesson.get('day')} slot is {minutes}"
            )
    for fig in lesson.get("figures") or []:
        if fig not in figures:
            problems.append(f"{tag}: unknown figure {fig!r}")
    return problems
