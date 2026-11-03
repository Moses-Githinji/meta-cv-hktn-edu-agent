"""Exam originality: questions must be original compositions, not copies.

check() flags a question that shares a long verbatim word run with a citable
source (a transcribed outcome, a scheme finding): ten or more consecutive
words, normalised. Short shared phrases ("whole numbers", "factor of") pass;
a copied sentence does not. Threshold and matches are reported, never hidden.
"""

from __future__ import annotations

from edu_kit.document_text import normalize

WORD_RUN = 10


def longest_run(a: list, b: list) -> int:
    """The longest run of consecutive words shared by two word lists."""
    best, prev = 0, [0] * (len(b) + 1)
    for i, word_a in enumerate(a, start=1):
        current = [0] * (len(b) + 1)
        for j, word_b in enumerate(b, start=1):
            if word_a == word_b:
                current[j] = prev[j - 1] + 1
                best = max(best, current[j])
        prev = current
    return best


def check(questions: list, sources: list) -> list:
    """Originality problems for questions against [{label, text}] sources."""
    problems = []
    texts = [(s.get("label", "?"), normalize(s.get("text", "")).split()) for s in sources]
    for question in questions:
        qid = question.get("id", "?")
        words = normalize(question.get("text", "")).split()
        if not words:
            continue
        for label, source_words in texts:
            if not source_words:
                continue
            run = longest_run(words, source_words)
            if run >= WORD_RUN:
                problems.append(
                    f"{qid}: shares a {run}-word run with {label}; "
                    "write original wording"
                )
    return problems
