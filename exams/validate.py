"""Exam construction checks: blueprint, marks arithmetic, answers.

An exam payload has a blueprint (total marks + per-outcome sections), the
questions, and the marking scheme. validate_exam() checks the whole payload:
section counts and marks match the questions, every total adds up, every
question has exactly one scheme entry with equal marks, figures exist,
nothing is duplicated, and the wording is original (see originality.py).
validate_answers() checks an answer set on its own (the check_answers tool).
"""

from __future__ import annotations

from . import originality


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_answers(questions: list, answers: list) -> list:
    """Answer-set problems (empty = every question answered once, marks match)."""
    problems = []
    if not isinstance(questions, list) or not questions:
        return ["questions must be a non-empty list"]
    if not isinstance(answers, list):
        return ["answers must be a list"]
    expected = {}
    for question in questions:
        if not isinstance(question, dict):
            problems.append("each question must be an object")
            continue
        qid = question.get("id")
        if not qid:
            problems.append("question id is empty")
        elif qid in expected:
            problems.append(f"duplicate question id {qid!r}")
        expected[qid] = question.get("marks")
    seen: set = set()
    for answer in answers:
        if not isinstance(answer, dict):
            problems.append("each answer must be an object")
            continue
        qid = answer.get("question_id")
        if qid in seen:
            problems.append(f"duplicate answer for {qid!r}")
        seen.add(qid)
        if qid not in expected:
            problems.append(f"answer for unknown question {qid!r}")
            continue
        if answer.get("marks") != expected[qid]:
            problems.append(
                f"{qid}: answer marks {answer.get('marks')} "
                f"do not match question marks {expected[qid]}"
            )
        if not str(answer.get("answer", "")).strip():
            problems.append(f"{qid}: answer is empty")
    for qid in expected:
        if qid and qid not in seen:
            problems.append(f"{qid}: no answer")
    return problems


def validate_exam(
    payload: dict,
    outcome_ids: set,
    outcome_texts: list,
    figure_ids: set,
    finding_summaries: list,
) -> list:
    """Every problem with an exam payload (empty = valid)."""
    if not isinstance(payload, dict):
        return ["exam must be an object"]
    problems = []
    blueprint = payload.get("blueprint")
    questions = payload.get("questions")
    scheme = payload.get("marking_scheme")
    if not isinstance(blueprint, dict):
        return ["exam.blueprint must be an object"]
    if not isinstance(questions, list) or not questions:
        problems.append("exam.questions must be a non-empty list")
        questions = []
    if not isinstance(scheme, list):
        problems.append("exam.marking_scheme must be a list")
        scheme = []
    total = blueprint.get("total_marks")
    if not _is_int(total) or total <= 0:
        problems.append("blueprint.total_marks must be a positive integer")

    by_outcome: dict[str, list] = {}
    question_rows = []
    for question in questions:
        if not isinstance(question, dict):
            problems.append("each question must be an object")
            continue
        qid = question.get("id", "?")
        if not str(question.get("text", "")).strip():
            problems.append(f"{qid}: text is empty")
        if not _is_int(question.get("marks")) or question["marks"] <= 0:
            problems.append(f"{qid}: marks must be a positive integer")
        if not str(question.get("answer", "")).strip():
            problems.append(f"{qid}: answer is empty")
        oid = question.get("outcome_id")
        if oid not in outcome_ids:
            problems.append(f"{qid}: unknown outcome_id {oid!r}")
        else:
            by_outcome.setdefault(oid, []).append(question)
        for fig in question.get("figures") or []:
            if fig not in figure_ids:
                problems.append(f"{qid}: unknown figure {fig!r}")
        question_rows.append({"id": question.get("id"), "marks": question.get("marks")})

    sections = blueprint.get("sections")
    if not isinstance(sections, list) or not sections:
        problems.append("blueprint.sections must be a non-empty list")
    else:
        for section in sections:
            if not isinstance(section, dict):
                problems.append("each blueprint section must be an object")
                continue
            oid = section.get("outcome_id")
            want_n, want_m = section.get("questions"), section.get("marks_each")
            if oid not in outcome_ids:
                problems.append(f"blueprint: unknown outcome_id {oid!r}")
                continue
            if not _is_int(want_n) or want_n <= 0 or not _is_int(want_m) or want_m <= 0:
                problems.append(
                    f"blueprint: section {oid} needs positive integer questions and marks_each"
                )
                continue
            got = by_outcome.get(oid, [])
            if len(got) != want_n:
                problems.append(
                    f"blueprint: section {oid} wants {want_n} questions, "
                    f"found {len(got)}"
                )
            for question in got:
                if question.get("marks") != want_m:
                    problems.append(
                        f"blueprint: {question.get('id')} marks "
                        f"{question.get('marks')}, section wants {want_m}"
                    )
    covered = {s.get("outcome_id") for s in sections or [] if isinstance(s, dict)}
    for oid in sorted(set(by_outcome) - covered):
        problems.append(f"blueprint: no section covers outcome {oid}")

    if _is_int(total) and total > 0:
        question_total = sum(
            q.get("marks", 0) for q in questions if isinstance(q, dict) and _is_int(q.get("marks"))
        )
        if question_total != total:
            problems.append(
                f"marks add to {question_total}, blueprint total is {total}"
            )
    problems.extend(validate_answers(question_rows, scheme))

    texts = [q.get("text", "") for q in questions if isinstance(q, dict)]
    seen_texts: set[str] = set()
    for qid, text in (
        (q.get("id", "?"), t) for q, t in zip(questions, texts) if isinstance(q, dict)
    ):
        key = " ".join(str(text).split()).lower()
        if key and key in seen_texts:
            problems.append(f"{qid}: duplicate question text")
        seen_texts.add(key)
    sources = [{"label": f"outcome {o['id']}", "text": o["text"]} for o in outcome_texts]
    sources += [
        {"label": f"scheme finding {item}", "text": summary}
        for item, summary in finding_summaries
    ]
    problems.extend(
        originality.check(
            [{"id": q.get("id", "?"), "text": q.get("text", "")} for q in questions if isinstance(q, dict)],
            sources,
        )
    )
    return problems
