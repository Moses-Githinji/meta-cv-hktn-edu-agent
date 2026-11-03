#!/usr/bin/env python3
"""Build documents/00-pack-index.pdf (stdlib only, deterministic).

The teaching pack needs one PDF in documents/ so ./helper setup and preflight
have an inbox to seed. This index PDF carries no outcomes: exact outcome text
lives in curriculum/grade7-mathematics-term1.json and is read natively.
Re-run to regenerate: python3 packs/grade7-mathematics-term1/build_index_pdf.py
"""

from __future__ import annotations

from pathlib import Path

LINES = [
    "Grade 7 Mathematics - Term 1 pack index (Phase 1)",
    "Strand 1: NUMBERS - Whole Numbers; Factors; Fractions;",
    "Decimals; Squares and Square Roots (weeks 1-12).",
    "Exact outcome text: curriculum/grade7-mathematics-term1.json",
    "(read natively by the agent - this PDF carries no outcomes).",
    "Calendar + timetable: teacher_context/term_calendar.json,",
    "teacher_context/timetable.json.",
]


def build_pdf(lines: list[str]) -> bytes:
    text = "BT /F1 14 Tf 72 740 Td " + " 0 -24 Td ".join(
        f"({line}) Tj" for line in lines
    ) + " ET"
    stream = text.encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref)
    )
    return bytes(out)


def main() -> None:
    root = Path(__file__).resolve().parent
    documents = root / "documents"
    documents.mkdir(exist_ok=True)
    target = documents / "00-pack-index.pdf"
    target.write_bytes(build_pdf(LINES))
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
