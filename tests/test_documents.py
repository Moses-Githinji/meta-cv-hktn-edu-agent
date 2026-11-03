"""Phase 5 documents: lesson plans, exams, diagrams, Word/PDF export.
Offline; never calls the API."""

from __future__ import annotations

import io
import json
import re
import unittest
import zipfile
from pathlib import Path

from diagrams import layout as layout_module
from diagrams import png as png_module
from diagrams import svg as svg_module
from diagrams.readback import ReadbackError, compare, read
from diagrams.spec import validate_spec
from edu_kit import tools
from edu_kit.case_record import CaseRecord
from edu_kit.progress import new_run
from exams.validate import validate_answers
from export.build import WHAT, ExportError, build
from export.docx import build_docx
from export.pdf import build_pdf
from tests import support

TIMETABLE = {
    "timetable": {
        "minutes_per_lesson": 40,
        "slots": [
            {"day": "Monday", "lessons": [1, 2], "kind": "double"},
            {"day": "Tuesday", "lessons": [3], "kind": "single"},
        ],
    }
}

GRAPH = {
    "kind": "graph",
    "title": "Plot",
    "x": {"min": 0, "max": 10, "label": "x"},
    "y": {"min": 0, "max": 10, "label": "y"},
    "points": [{"x": 2, "y": 3, "label": "A"}],
    "segments": [{"a": [0, 0], "b": [10, 10]}],
}
GEOMETRY = {
    "kind": "geometry",
    "title": "Shapes",
    "shapes": [
        {"shape": "triangle", "a": [0, 0], "b": [4, 0], "c": [0, 3], "label": "T"},
        {"shape": "circle", "at": [6, 2], "r": 1.5},
    ],
}
CIRCUIT = {
    "kind": "circuit",
    "title": "Loop",
    "wires": [{"a": [0, 0], "b": [4, 0]}],
    "components": [{"type": "bulb", "at": [2, 0], "label": "B1"}],
}


def painted_text_fills(pdf: bytes) -> list:
    """(text, fill) for every Tj in the content streams, tracking fill color.

    Fill starts black; `r g b rg` / `g g` ops change it (`G` is stroke, not
    fill, and must not match). Text paints with the fill color, so any
    non-black entry is text a viewer cannot read on the white page.
    """
    texts = []
    for match in re.finditer(rb"stream\n(.*?)endstream", pdf, re.S):
        ops = match.group(1).decode("ascii")
        fill = (0.0, 0.0, 0.0)
        for tok in re.finditer(
            r"(\d+(?:\.\d+)?) (\d+(?:\.\d+)?) (\d+(?:\.\d+)?) rg"
            r"|(\d+(?:\.\d+)?) g(?![A-Za-z])"
            r"|\((?:[^()\\]|\\.)*\) Tj",
            ops,
        ):
            if tok.group(0).endswith("Tj"):
                texts.append((tok.group(0), fill))
            elif tok.group(4) is not None:
                grey = float(tok.group(4))
                fill = (grey, grey, grey)
            else:
                fill = (float(tok.group(1)), float(tok.group(2)), float(tok.group(3)))
    return texts


def xref_valid(pdf: bytes) -> bool:
    """Independent check: every xref offset points at its object header."""
    match = re.search(rb"startxref\s+(\d+)", pdf)
    if not match or pdf[int(match.group(1)) :][:4] != b"xref":
        return False
    lines = pdf[int(match.group(1)) :].split(b"\n")
    count = int(lines[1].split()[1])
    for i in range(1, count):
        offset = int(lines[2 + i][:10])
        if pdf[offset : offset + len(f"{i} 0 obj")] != f"{i} 0 obj".encode():
            return False
    return True


def call(name: str, args: dict | None = None, call_id: str = "c1") -> dict:
    return {
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args or {}),
        "call_id": call_id,
    }


def exam_payload(figures: list | None = None) -> dict:
    questions = [
        {
            "id": "Q1",
            "text": "Round 45678 to the nearest thousand and explain each step.",
            "marks": 4,
            "answer": "46000, since 678 rounds up.",
            "outcome_id": "T-1.1.1",
        },
        {
            "id": "Q2",
            "text": "List all factors of 36 in ascending order.",
            "marks": 3,
            "answer": "1, 2, 3, 4, 6, 9, 12, 18, 36.",
            "outcome_id": "T-1.2.1",
        },
        {
            "id": "Q3",
            "text": "A shop packs 48 balls into equal boxes. Which box sizes work?",
            "marks": 3,
            "answer": "Every divisor of 48.",
            "outcome_id": "T-1.2.1",
        },
    ]
    if figures:
        questions[0]["figures"] = figures
    return {
        "blueprint": {
            "total_marks": 10,
            "sections": [
                {"outcome_id": "T-1.1.1", "questions": 1, "marks_each": 4},
                {"outcome_id": "T-1.2.1", "questions": 2, "marks_each": 3},
            ],
        },
        "questions": questions,
        "marking_scheme": [
            {"question_id": "Q1", "answer": "46000, since 678 rounds up.", "marks": 4},
            {"question_id": "Q2", "answer": "1, 2, 3, 4, 6, 9, 12, 18, 36.", "marks": 3},
            {"question_id": "Q3", "answer": "Every divisor of 48.", "marks": 3},
        ],
    }


class DocumentsBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        support.write_pack(self.root)
        (self.root / "teacher_context").mkdir()
        (self.root / "teacher_context/timetable.json").write_text(json.dumps(TIMETABLE))
        self.fake = support.scripted(self.root, [])
        self.client = self.fake.client
        self.run_id = new_run(
            self.root, instructions="i", objective="o", verification=False
        )

    def tool(self, name: str, args: dict | None = None, run_id: str = "") -> dict:
        return tools.run(
            self.client, self.root, run_id or self.run_id, call(name, args)
        )

    def filed_scheme(self) -> None:
        CaseRecord(self.root, self.run_id).set_checklist(
            support.TEACH_CHECKLIST[1]["items"]
        )
        self.tool("cite_outcome", support.TEACH_CITE[1])
        self.tool("ask_teacher", support.TEACH_ASK[1])
        CaseRecord(self.root, self.run_id).answer_request("R1", "proceed")
        filed = self.tool("submit_document", support.TEACH_SUBMIT[1])
        self.assertEqual("answered", filed["status"])

    def approved_scheme(self) -> None:
        self.filed_scheme()
        case = CaseRecord(self.root, self.run_id)
        case.review_item("whole_numbers", "approved", "good")
        case.review_item("factors", "approved", "good")

    def make_figure(self, spec: dict | None = None) -> dict:
        result = self.tool("make_diagram", {"spec": spec or GRAPH})
        self.assertIn("figure", result)
        return result["figure"]


class LessonPlanTest(DocumentsBase):
    def plan(self, **overrides) -> dict:
        plan = {
            "week": 1,
            "lessons": [
                {
                    "day": "Monday",
                    "items": ["whole_numbers"],
                    "activities": [
                        {"title": "Warm-up quiz", "minutes": 20},
                        {"title": "Guided practice", "minutes": 60},
                    ],
                },
                {
                    "day": "Tuesday",
                    "items": ["factors"],
                    "activities": [{"title": "Factor drill", "minutes": 40}],
                },
            ],
        }
        plan.update(overrides)
        return plan

    def test_valid_plan_files(self) -> None:
        self.approved_scheme()
        result = self.tool("submit_lesson_plan", self.plan())
        self.assertEqual("LP1", result["lesson_plan"]["id"])
        plans = CaseRecord(self.root, self.run_id).data["lesson_plans"]
        self.assertEqual(1, len(plans))

    def test_unapproved_and_rejected_rows_refuse(self) -> None:
        self.filed_scheme()
        refused = self.tool("submit_lesson_plan", self.plan())
        self.assertIn("not approved yet", refused["problems"][0])
        CaseRecord(self.root, self.run_id).review_item("whole_numbers", "approved")
        CaseRecord(self.root, self.run_id).review_item("factors", "rejected", "redo")
        refused = self.tool("submit_lesson_plan", self.plan())
        self.assertTrue(any("factors is not approved" in p for p in refused["problems"]))

    def test_timing_must_sum_exactly_to_the_slot(self) -> None:
        self.approved_scheme()
        plan = self.plan()
        plan["lessons"][1]["activities"] = [{"title": "Short drill", "minutes": 30}]
        refused = self.tool("submit_lesson_plan", plan)
        self.assertTrue(any("sum to 30 minutes" in p and "slot is 40" in p for p in refused["problems"]))

    def test_bad_day_week_and_figure_refuse(self) -> None:
        self.approved_scheme()
        plan = self.plan()
        plan["lessons"][0]["day"] = "Thursday"
        self.assertIn("no mathematics slot", self.tool("submit_lesson_plan", plan)["problems"][0])
        plan = self.plan(week=99)
        self.assertIn("1..4", self.tool("submit_lesson_plan", plan)["problems"][0])
        plan = self.plan()
        plan["lessons"][0]["figures"] = ["fig-9"]
        self.assertIn("unknown figure", self.tool("submit_lesson_plan", plan)["problems"][0])


class CheckAnswersTest(DocumentsBase):
    def test_matching_answers_pass_with_total(self) -> None:
        payload = exam_payload()
        result = self.tool(
            "check_answers",
            {
                "questions": [{"id": q["id"], "marks": q["marks"]} for q in payload["questions"]],
                "answers": payload["marking_scheme"],
            },
        )
        self.assertEqual((True, 10), (result["ok"], result["total_marks"]))

    def test_missing_mismatched_and_unknown_answers_fail(self) -> None:
        questions = [{"id": "Q1", "marks": 4}, {"id": "Q2", "marks": 3}]
        missing = validate_answers(questions, [{"question_id": "Q1", "answer": "a", "marks": 4}])
        self.assertIn("Q2: no answer", missing)
        mismatched = validate_answers(
            questions,
            [
                {"question_id": "Q1", "answer": "a", "marks": 4},
                {"question_id": "Q2", "answer": "b", "marks": 9},
            ],
        )
        self.assertTrue(any("do not match" in p for p in mismatched))
        unknown = validate_answers(questions, [{"question_id": "Q9", "answer": "a", "marks": 1}])
        self.assertTrue(any("unknown question" in p for p in unknown))


class ExamFilingTest(DocumentsBase):
    def submit_exam(self, payload: dict | None, **overrides) -> dict:
        args = dict(support.TEACH_SUBMIT[1], kind="exam")
        if payload is not None:
            args["exam"] = payload
        args.update(overrides)
        return self.tool("submit_document", args)

    def test_exam_without_payload_refuses(self) -> None:
        self.filed_scheme()
        result = self.submit_exam(None)
        self.assertTrue(any("needs an exam payload" in p for p in result["problems"]))

    def test_good_exam_files(self) -> None:
        self.filed_scheme()
        result = self.submit_exam(exam_payload())
        self.assertEqual("answered", result["status"])
        memo = CaseRecord(self.root, self.run_id).data["memo"]
        self.assertEqual("exam", memo["kind"])
        self.assertEqual(10, memo["exam"]["blueprint"]["total_marks"])

    def test_marks_arithmetic_is_checked(self) -> None:
        self.filed_scheme()
        payload = exam_payload()
        payload["blueprint"]["total_marks"] = 99
        result = self.submit_exam(payload)
        self.assertTrue(any("add to 10" in p and "total is 99" in p for p in result["problems"]))
        payload = exam_payload()
        payload["blueprint"]["sections"][0]["questions"] = 5
        result = self.submit_exam(payload)
        self.assertTrue(any("wants 5 questions" in p for p in result["problems"]))

    def test_copied_and_duplicate_questions_refuse(self) -> None:
        self.filed_scheme()
        payload = exam_payload()
        payload["questions"][0]["text"] = support.WHOLE_NUMBERS_TEXT
        result = self.submit_exam(payload)
        self.assertTrue(any("shares a" in p and "run with outcome" in p for p in result["problems"]))
        payload = exam_payload()
        payload["questions"][1]["text"] = payload["questions"][0]["text"]
        result = self.submit_exam(payload)
        self.assertTrue(any("duplicate question" in p for p in result["problems"]))

    def test_scheme_payload_with_exam_is_refused(self) -> None:
        self.filed_scheme()
        args = dict(support.TEACH_SUBMIT[1], exam=exam_payload())
        result = self.tool("submit_document", args)
        self.assertIn("needs kind exam", result["problems"][0])


class DiagramToolsTest(DocumentsBase):
    def test_check_accepts_all_three_kinds(self) -> None:
        for spec in (GRAPH, GEOMETRY, CIRCUIT):
            self.assertEqual({"ok": True}, self.tool("check_diagram", {"spec": spec}))

    def test_check_reports_spec_problems(self) -> None:
        bad_kind = self.tool("check_diagram", {"spec": {"kind": "pie", "title": "P"}})
        self.assertIn("kind must be", bad_kind["problems"][0])
        outside = dict(GRAPH, points=[{"x": 99, "y": 1}])
        result = self.tool("check_diagram", {"spec": outside})
        self.assertTrue(any("outside the x range" in p for p in result["problems"]))
        typo = dict(GRAPH, pooints=[])
        self.assertTrue(any("unknown key" in p for p in self.tool("check_diagram", {"spec": typo})["problems"]))
        bad_component = dict(CIRCUIT, components=[{"type": "toaster", "at": [0, 0]}])
        result = self.tool("check_diagram", {"spec": bad_component})
        self.assertTrue(any("must be one of" in p for p in result["problems"]))
        self.assertIn("spec must be an object", self.tool("check_diagram", {})["error"])
        self.assertEqual([], validate_spec(GEOMETRY))

    def test_make_renders_and_files_a_figure(self) -> None:
        figure = self.make_figure()
        self.assertEqual(("fig-1", "graph"), (figure["id"], figure["kind"]))
        svg_path = self.root / figure["svg"]
        png_path = self.root / figure["png"]
        self.assertTrue(svg_path.read_text().startswith("<svg"))
        png = png_path.read_bytes()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IHDR", png[:32])

    def test_make_refuses_bad_specs_without_filing(self) -> None:
        result = self.tool("make_diagram", {"spec": {"kind": "graph"}})
        self.assertEqual("spec invalid", result["error"])
        self.assertEqual([], CaseRecord(self.root, self.run_id).data.get("figures", []))

    def test_renders_are_deterministic(self) -> None:
        first = svg_module.emit(layout_module.layout(GRAPH))
        second = svg_module.emit(layout_module.layout(GRAPH))
        self.assertEqual(first, second)


APPARATUS = {
    "kind": "apparatus",
    "title": "Bench",
    "components": [
        {"type": "beaker", "at": [0, 0], "label": "B"},
        {"type": "burner", "at": [2, 0]},
    ],
}
RAY = {
    "kind": "ray",
    "title": "Reflection",
    "rays": [{"a": [0, 2], "b": [3, 0], "label": "in"}],
    "optics": [{"type": "mirror", "at": [3, 0], "label": "M"}],
}


class NewKindsTest(DocumentsBase):
    def test_apparatus_and_ray_check_render_and_read_back(self) -> None:
        for spec in (APPARATUS, RAY):
            self.assertEqual({"ok": True}, self.tool("check_diagram", {"spec": spec}))
            svg_text = svg_module.emit(layout_module.layout(spec))
            self.assertEqual([], compare(spec, read(svg_text)))
        figure = self.make_figure(APPARATUS)
        self.assertEqual("apparatus", figure["kind"])

    def test_new_kind_problems(self) -> None:
        bad_type = dict(APPARATUS, components=[{"type": "toaster", "at": [0, 0]}])
        result = self.tool("check_diagram", {"spec": bad_type})
        self.assertTrue(any("must be one of" in p for p in result["problems"]))
        no_rays = self.tool("check_diagram", {"spec": {"kind": "ray", "title": "R", "rays": []}})
        self.assertTrue(any("at least one ray" in p for p in no_rays["problems"]))
        bad_optic = dict(RAY, optics=[{"type": "prism", "at": [0, 0]}])
        result = self.tool("check_diagram", {"spec": bad_optic})
        self.assertTrue(any("must be one of" in p for p in result["problems"]))


class ReadbackTest(DocumentsBase):
    def test_round_trip_matches(self) -> None:
        for spec in (GRAPH, GEOMETRY, CIRCUIT):
            svg_text = svg_module.emit(layout_module.layout(spec))
            self.assertEqual([], compare(spec, read(svg_text)))

    def test_tampered_and_broken_svg_mismatch(self) -> None:
        svg_text = svg_module.emit(layout_module.layout(GRAPH))
        tampered = svg_text.replace('data-kind="graph"', 'data-kind="geometry"')
        self.assertTrue(any("kind" in m for m in compare(GRAPH, read(tampered))))
        dropped = "\n".join(
            line for line in svg_text.splitlines() if 'data-el="0"' not in line
        )
        self.assertTrue(compare(GRAPH, read(dropped)))
        with self.assertRaises(ReadbackError):
            read("not svg at all {{{")


class PngFontTest(DocumentsBase):
    def test_glyph_shape_and_ink(self) -> None:
        self.assertEqual(".###.", png_module.FONT["A"][0])
        canvas = png_module.Canvas(60, 20)
        canvas.text(2, 2, "A0", 1, png_module.BLACK)
        ink = sum(1 for i in range(0, len(canvas.pixels), 3) if canvas.pixels[i] == 0)
        self.assertGreater(ink, 20)
        canvas.text(2, 10, "~", 1, png_module.BLACK)  # unknown chars fall back to "?"
        self.assertIn("?", png_module.FONT)


class ExportTest(DocumentsBase):
    def exam_run(self) -> None:
        self.filed_scheme()
        figure = self.make_figure()
        args = dict(support.TEACH_SUBMIT[1], kind="exam", exam=exam_payload([figure["id"]]))
        del args["lessons"]
        result = self.tool("submit_document", args)
        self.assertEqual("answered", result["status"])

    def test_whats_are_known(self) -> None:
        self.assertEqual(("scheme", "exam", "marking-scheme", "lesson-plan"), WHAT)

    def test_scheme_docx_and_pdf(self) -> None:
        self.filed_scheme()
        title, flow, footer = build(self.root, self.run_id, "scheme")
        self.assertIn("table", [kind for kind, _ in flow])
        for builder in (build_docx, build_pdf):
            data = builder(title, flow, footer, landscape=True)
            self.assertGreater(len(data), 500)
        document = zipfile.ZipFile(io.BytesIO(build_docx(title, flow, footer, landscape=True))).read("word/document.xml").decode()
        self.assertIn("Term coverage is planned.", document)
        self.assertIn("Objectives", document)
        self.assertIn("Week 1 period 1 subtopic", document)
        self.assertIn("tblHeader", document)
        self.assertIn('orient="landscape"', document)
        pdf = build_pdf(title, flow, footer, landscape=True)
        self.assertIn(b"MediaBox [0 0 842 595]", pdf)
        self.assertIn(b"Objectives", pdf)
        self.assertIn(b"Teaching Methods", pdf)

    def test_scheme_pdf_text_is_painted_black(self) -> None:
        self.filed_scheme()
        title, flow, footer = build(self.root, self.run_id, "scheme")
        painted = painted_text_fills(build_pdf(title, flow, footer, landscape=True))
        self.assertGreater(len(painted), 10)
        for text, fill in painted:
            self.assertEqual((0.0, 0.0, 0.0), fill, f"unreadable text: {text[:60]}")

    def test_scheme_export_needs_lessons(self) -> None:
        self.exam_run()
        with self.assertRaisesRegex(ExportError, "no lesson table"):
            build(self.root, self.run_id, "scheme")

    def test_exam_exports_number_figures_and_footers(self) -> None:
        self.exam_run()
        title, flow, footer = build(self.root, self.run_id, "exam")
        package = zipfile.ZipFile(io.BytesIO(build_docx(title, flow, footer)))
        self.assertIn("word/media/figure1.png", package.namelist())
        document = package.read("word/document.xml").decode()
        self.assertIn("Figure 1:", document)
        self.assertIn("Q1", document)
        footer_xml = package.read("word/footer1.xml").decode()
        self.assertIn(self.run_id, footer_xml)
        self.assertIn("PAGE", footer_xml)
        pdf = build_pdf(title, flow, footer)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"Figure 1:", pdf)
        self.assertIn(self.run_id.encode(), pdf)
        self.assertEqual(1, pdf.count(b"/Subtype /Image"))
        self.assertTrue(xref_valid(pdf))

    def test_marking_scheme_embeds_answer_figures(self) -> None:
        self.exam_run()
        title, flow, footer = build(self.root, self.run_id, "marking-scheme")
        texts = " ".join(str(payload) for kind, payload in flow if kind in ("p", "h2"))
        self.assertIn("46000", texts)
        captions = [payload["caption"] for kind, payload in flow if kind == "figure"]
        self.assertEqual(1, len(captions))
        self.assertTrue(captions[0].startswith("Figure 1:"))

    def test_lesson_plan_export_and_sequential_numbering(self) -> None:
        self.approved_scheme()
        first = self.make_figure()
        second = self.make_figure(GEOMETRY)
        plan = {
            "week": 1,
            "lessons": [
                {
                    "day": "Monday",
                    "items": ["whole_numbers"],
                    "activities": [{"title": "Graph work", "minutes": 80}],
                    "figures": [first["id"], second["id"]],
                }
            ],
        }
        self.assertIn("lesson_plan", self.tool("submit_lesson_plan", plan))
        title, flow, footer = build(self.root, self.run_id, "lesson-plan")
        captions = [payload["caption"] for kind, payload in flow if kind == "figure"]
        self.assertEqual(["Figure 1: Plot", "Figure 2: Shapes"], captions)
        pdf = build_pdf(title, flow, footer)
        self.assertEqual(2, pdf.count(b"/Subtype /Image"))

    def test_export_errors_name_the_problem(self) -> None:
        with self.assertRaisesRegex(ExportError, "one of"):
            build(self.root, self.run_id, "syllabus")
        with self.assertRaisesRegex(ExportError, "no filed document"):
            build(self.root, self.run_id, "scheme")
        self.filed_scheme()
        with self.assertRaisesRegex(ExportError, "no filed exam"):
            build(self.root, self.run_id, "exam")
        with self.assertRaisesRegex(ExportError, "no lesson plans"):
            build(self.root, self.run_id, "lesson-plan")
        self.exam_run()
        png_path = next((self.root / "workspace/runs" / self.run_id / "figures").glob("*.png"))
        png_path.unlink()
        with self.assertRaisesRegex(ExportError, "PNG unreadable"):
            build(self.root, self.run_id, "exam")


if __name__ == "__main__":
    unittest.main()
