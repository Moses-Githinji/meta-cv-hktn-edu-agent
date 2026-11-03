"""Teaching tools (Phase 2): list/read curriculum, cite_outcome, ask_teacher,
submit_document, and the loop's saved failure notes. Offline; never calls the API."""

from __future__ import annotations

import json
import unittest

from edu_kit.case_record import CaseRecord
from edu_kit.progress import add_failure_note, load_progress, new_run, resume
from edu_kit.settings import verification_enabled
from edu_kit import tools
from teaching_agent.loop import run_agent
from tests import support
from tests.fake_model import Refused


def call(name: str, args: dict | None = None, call_id: str = "c1") -> dict:
    return {
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args or {}),
        "call_id": call_id,
    }


class TeachingToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        support.write_pack(self.root)
        self.fake = support.scripted(self.root, [])
        self.client = self.fake.client
        self.run_id = new_run(
            self.root, instructions="i", objective="o", verification=False
        )

    def tool(self, name: str, args: dict | None = None, run_id: str = "") -> dict:
        return tools.run(
            self.client, self.root, run_id or self.run_id, call(name, args)
        )

    def checklist(self) -> CaseRecord:
        case = CaseRecord(self.root, self.run_id)
        case.set_checklist(support.TEACH_CHECKLIST[1]["items"])
        return case

    # ---- list/read curriculum ----
    def test_list_curriculum_shows_strands_and_coverage(self) -> None:
        result = self.tool("list_curriculum")
        self.assertEqual("test-pack", result["pack"])
        self.assertEqual("NUMBERS", result["strands"][0]["name"])
        subs = result["strands"][0]["sub_strands"]
        self.assertEqual([1, 2], subs[0]["week_range"])
        self.assertEqual(
            (2, 3, ["T-1.1.2"]),
            (
                result["coverage"]["transcribed"],
                result["coverage"]["total"],
                result["coverage"]["pending"],
            ),
        )

    def test_read_curriculum_returns_exact_text(self) -> None:
        outcome = self.tool("read_curriculum", {"outcome_id": "T-1.1.1"})["outcome"]
        self.assertEqual(support.WHOLE_NUMBERS_TEXT, outcome["outcome_text"])
        self.assertEqual("Whole Numbers", outcome["sub_strand"])

    def test_read_curriculum_refuses_unknown_and_pending(self) -> None:
        self.assertIn("unknown outcome", self.tool("read_curriculum", {"outcome_id": "NOPE"})["error"])
        pending = self.tool("read_curriculum", {"outcome_id": "T-1.1.2"})["error"]
        self.assertIn("not transcribed yet", pending)
        self.assertIn("ask_teacher", pending)

    def test_read_curriculum_surfaces_enrichment_fields(self) -> None:
        outcome = self.tool("read_curriculum", {"outcome_id": "T-1.1.1"})["outcome"]
        self.assertEqual(
            ["Learners count bottle tops in groups of ten."],
            outcome["suggested_learning_experiences"],
        )
        self.assertEqual(
            ["How do we count large groups quickly?"], outcome["key_inquiry_questions"]
        )
        self.assertEqual(["Observe learners counting in groups."], outcome["assessment"])
        self.assertEqual(["Bottle tops."], outcome["learning_resources"])
        bare = self.tool("read_curriculum", {"outcome_id": "T-1.2.1"})["outcome"]
        for field in ("suggested_learning_experiences", "key_inquiry_questions",
                      "assessment", "learning_resources"):
            self.assertNotIn(field, bare)

    # ---- cite_outcome ----
    def test_cite_outcome_records_exact_quotes_and_refuses_paraphrase(self) -> None:
        self.checklist()
        recorded = self.tool("cite_outcome", support.TEACH_CITE[1])["recorded"]
        self.assertEqual("whole_numbers", recorded["item"])
        self.assertEqual("T-1.1.1", recorded["outcome_id"])
        case = CaseRecord(self.root, self.run_id)
        self.assertEqual("proven", case.data["checklist"]["whole_numbers"]["status"])
        bad = dict(support.TEACH_CITE[1], quote="Learners can kinda count big numbers")
        self.assertIn("exact text", self.tool("cite_outcome", bad)["error"])
        no_item = dict(support.TEACH_CITE[1], item="fractions")
        self.assertIn("unknown checklist item", self.tool("cite_outcome", no_item)["error"])

    def test_cite_outcome_refuses_pending_outcomes(self) -> None:
        self.checklist()
        args = dict(
            support.TEACH_CITE[1],
            item="factors",
            outcome_id="T-1.1.2",
            quote="TODO_TRANSCRIBE",
            claim="x",
        )
        self.assertIn("not transcribed yet", self.tool("cite_outcome", args)["error"])

    # ---- ask_teacher ----
    def test_ask_teacher_pauses_and_resume_waits_for_the_answer(self) -> None:
        self.checklist()
        asked = self.tool("ask_teacher", support.TEACH_ASK[1])
        self.assertEqual(("needs_input", "R1"), (asked["status"], asked["request"]))
        # Second question while one is open is refused.
        again = self.tool(
            "ask_teacher", {"item": "whole_numbers", "question": "another?"}
        )
        self.assertIn("already open", again["error"])
        # Resume before the answer: nothing to continue.
        from edu_kit.progress import save_progress

        save_progress(self.root, self.run_id, [], status="needs_input")
        step = resume(self.root, self.run_id)
        self.assertIsNone(step["message"])
        # The teacher answers; resume continues with the answer.
        CaseRecord(self.root, self.run_id).answer_request("R1", "proceed with gaps")
        step = resume(self.root, self.run_id)
        self.assertIn("R1", step["message"])
        self.assertIn("proceed with gaps", step["message"])

    def test_ask_teacher_refuses_covered_and_unknown_items(self) -> None:
        self.checklist()
        self.tool("cite_outcome", support.TEACH_CITE[1])
        covered = self.tool(
            "ask_teacher", {"item": "whole_numbers", "question": "covered?"}
        )
        self.assertIn("already covered", covered["error"])
        unknown = self.tool("ask_teacher", {"item": "nope", "question": "x"})
        self.assertIn("unknown checklist item", unknown["error"])

    # ---- submit_document ----
    def test_submit_document_files_when_consistent(self) -> None:
        self.checklist()
        self.tool("cite_outcome", support.TEACH_CITE[1])
        self.tool("ask_teacher", support.TEACH_ASK[1])
        result = self.tool("submit_document", support.TEACH_SUBMIT[1])
        self.assertEqual(("answered", "unverified"), (result["status"], result["document"]))
        memo = CaseRecord(self.root, self.run_id).data["memo"]
        self.assertEqual("unverified", memo["status"])

    def test_submit_document_refuses_inconsistencies(self) -> None:
        self.checklist()
        self.tool("cite_outcome", support.TEACH_CITE[1])
        missing = dict(
            support.TEACH_SUBMIT[1],
            findings=[support.TEACH_SUBMIT[1]["findings"][0]],
        )
        problems = self.tool("submit_document", missing)["problems"]
        self.assertIn("no finding for checklist item(s): factors", problems)
        invented = dict(
            support.TEACH_SUBMIT[1]["findings"][0],
            citations=[{"outcome_id": "T-1.1.1", "quote": "invented words here"}],
        )
        bad = dict(
            support.TEACH_SUBMIT[1], findings=[invented, support.TEACH_SUBMIT[1]["findings"][1]]
        )
        problems = self.tool("submit_document", bad)["problems"]
        self.assertTrue(any("does not match a recorded citation" in p for p in problems))

    def test_submit_document_refuses_lesson_table_problems(self) -> None:
        self.checklist()
        self.tool("cite_outcome", support.TEACH_CITE[1])

        def attempt(lessons):
            args = dict(support.TEACH_SUBMIT[1], lessons=lessons)
            return self.tool("submit_document", args)

        cases = [
            (None, "needs a lessons table"),
            ([], "needs a lessons table"),
        ]
        for lessons, message in cases:
            problems = attempt(lessons)["problems"]
            self.assertIn(message, " ".join(problems))

        rows = support.scheme_lessons()
        rows[1]["week"], rows[1]["period"] = rows[0]["week"], rows[0]["period"]
        problems = attempt(rows)["problems"]
        self.assertTrue(any("duplicate lesson row" in p for p in problems))

        rows = support.scheme_lessons()
        rows[0]["week"] = 9
        problems = attempt(rows)["problems"]
        self.assertTrue(any("week must be an integer 1..4" in p for p in problems))

        rows = support.scheme_lessons()
        rows[0]["objectives"] = "  "
        problems = attempt(rows)["problems"]
        self.assertTrue(any("objectives is empty" in p for p in problems))

        rows = support.scheme_lessons()
        rows[0]["item"] = "nope"
        problems = attempt(rows)["problems"]
        self.assertTrue(any("unknown checklist item" in p for p in problems))

        rows = support.scheme_lessons()
        rows[0]["citations"] = [{"outcome_id": "T-1.1.1", "quote": "invented words here"}]
        problems = attempt(rows)["problems"]
        self.assertTrue(any("does not match a recorded citation" in p for p in problems))

        problems = attempt(support.scheme_lessons()[:19])["problems"]
        self.assertTrue(any("missing 1 slots" in p for p in problems))

    def test_submit_document_accepts_recorded_lesson_citations(self) -> None:
        self.checklist()
        self.tool("cite_outcome", support.TEACH_CITE[1])
        rows = support.scheme_lessons()
        rows[0]["item"] = "whole_numbers"
        rows[0]["citations"] = [
            {"outcome_id": "T-1.1.1", "quote": support.WHOLE_NUMBERS_TEXT}
        ]
        args = dict(support.TEACH_SUBMIT[1], lessons=rows)
        result = self.tool("submit_document", args)
        self.assertEqual("answered", result["status"])

    def test_submit_document_runs_scheme_checks_with_verification_on(self) -> None:
        run_id = new_run(self.root, instructions="i", objective="o", verification=True)
        CaseRecord(self.root, run_id).set_checklist(
            support.TEACH_CHECKLIST[1]["items"]
        )
        self.tool("cite_outcome", support.TEACH_CITE[1], run_id)
        self.tool("ask_teacher", support.TEACH_ASK[1], run_id)
        CaseRecord(self.root, run_id).answer_request("R1", "proceed with gaps")
        result = self.tool("submit_document", support.TEACH_SUBMIT[1], run_id)
        self.assertEqual(
            ("awaiting_signoff", "awaiting_signoff"),
            (result["status"], result["document"]),
        )
        self.assertEqual(
            "awaiting_signoff", CaseRecord(self.root, run_id).data["memo"]["status"]
        )

    def test_submit_document_refuses_open_requests_with_verification_on(self) -> None:
        run_id = new_run(self.root, instructions="i", objective="o", verification=True)
        CaseRecord(self.root, run_id).set_checklist(
            support.TEACH_CHECKLIST[1]["items"]
        )
        self.tool("cite_outcome", support.TEACH_CITE[1], run_id)
        self.tool("ask_teacher", support.TEACH_ASK[1], run_id)  # left open
        result = self.tool("submit_document", support.TEACH_SUBMIT[1], run_id)
        self.assertEqual("document refused", result["error"])
        self.assertTrue(any("still open" in p for p in result["problems"]))

    # ---- failure notes ----
    def test_failure_notes_accumulate_on_the_run(self) -> None:
        add_failure_note(
            self.root, self.run_id, {"kind": "tool_error", "tool": "cite_outcome"}
        )
        notes = load_progress(self.root, self.run_id)["failure_notes"]
        self.assertEqual("cite_outcome", notes[0]["tool"])

    @unittest.skipIf(
        verification_enabled(),
        "verification-on teaching checklist checks belong to the later phase",
    )
    def test_loop_saves_a_note_when_a_tool_is_refused(self) -> None:
        bad_cite = ("cite_outcome", dict(support.TEACH_CITE[1], quote="made up"))
        fake = support.scripted(self.root, [support.TEACH_CHECKLIST, bad_cite])
        result = run_agent(root=self.root, client=fake.client, turns=2)
        self.assertEqual("paused", result["status"])  # turn limit, document not filed
        notes = load_progress(self.root, result["run_id"])["failure_notes"]
        self.assertEqual(1, len(notes))
        self.assertEqual(("tool_error", "cite_outcome"), (notes[0]["kind"], notes[0]["tool"]))
        self.assertEqual(2, notes[0]["turn"])

    def test_loop_saves_a_note_when_the_model_call_fails(self) -> None:
        fake = support.scripted(self.root, [support.TEACH_LIST])
        original, failures = fake.responder, []

        def outage(kind, payload):
            if kind == "respond" and "tools" in payload and not failures:
                failures.append(1)
                raise Refused("service_overloaded")
            return original(kind, payload)

        fake.responder = outage
        result = run_agent(root=self.root, client=fake.client, turns=5)
        self.assertEqual("paused", result["status"])
        notes = load_progress(self.root, result["run_id"])["failure_notes"]
        self.assertEqual("model_error", notes[0]["kind"])

    def test_loop_offers_the_teaching_tools(self) -> None:
        fake = support.scripted(self.root, [support.TEACH_LIST])
        run_agent(root=self.root, client=fake.client, turns=1)
        offered = {t["name"] for t in support.first_agent_request(fake)["tools"]}
        for name in (
            "list_curriculum",
            "read_curriculum",
            "cite_outcome",
            "ask_teacher",
            "submit_document",
        ):
            self.assertIn(name, offered)


if __name__ == "__main__":
    unittest.main()
