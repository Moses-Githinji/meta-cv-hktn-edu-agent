"""Phase 3 trust layer: the audit log, inline checks, escalation, independent
verification, and the review console. Offline; never calls the API."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from edu_kit import audit, tools
from edu_kit.case_record import CaseError, CaseRecord
from tests import support
from edu_kit.progress import load_progress, new_run, resume, save_progress
from edu_kit.settings import judge_model, model
from scripts import independent_verify
from scripts.review import item_rows, render
from teaching_agent.loop import run_agent
from tests import support
from verification import verify_claims, verify_scheme, verify_teaching_checklist


def call(name: str, args: dict | None = None, call_id: str = "c1") -> dict:
    return {
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args or {}),
        "call_id": call_id,
    }


def item(item_id: str, outcome_id: str) -> dict:
    return {
        "id": item_id,
        "question": f"Cover {outcome_id} this term",
        "evidence_needed": f"Outcome {outcome_id} exact text",
    }


# A checklist that accounts for every outcome in support.TINY_PACK.
IDS_CHECKLIST = [
    item("whole_numbers", "T-1.1.1"),
    item("factors", "T-1.2.1"),
    {
        "id": "gaps",
        "question": "Name the gaps",
        "evidence_needed": "Pending T-1.1.2 stays a gap",
    },
]

WHOLE = support.WHOLE_NUMBERS_TEXT
FACTORS = support.FACTORS_TEXT


class TrustBase(unittest.TestCase):
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

    def verified_run(self) -> str:
        return new_run(self.root, instructions="i", objective="o", verification=True)

    def ctx(self, run_id: str = ""):
        run_id = run_id or self.run_id
        return tools.Context(
            self.client, self.root, run_id, CaseRecord(self.root, run_id), True
        )

    def settle_all(self, run_id: str) -> None:
        """whole_numbers cited, factors + gaps asked/escalated and answered."""
        self.tool(
            "cite_outcome",
            {
                "item": "whole_numbers",
                "outcome_id": "T-1.1.1",
                "quote": WHOLE,
                "claim": "whole numbers are covered",
            },
            run_id,
        )
        self.tool(
            "ask_teacher",
            {"item": "factors", "question": "Factors wording missing; proceed?"},
            run_id,
        )
        CaseRecord(self.root, run_id).answer_request("R1", "proceed with gaps")
        self.tool(
            "escalate",
            {
                "item": "gaps",
                "reason_code": "missing_outcome_text",
                "need": "T-1.1.2 wording or confirm it stays a gap",
            },
            run_id,
        )
        CaseRecord(self.root, run_id).answer_request("R2", "confirmed as a gap")

    def document(self, kind: str = "scheme") -> dict:
        return {
            "conclusion": "Term coverage is planned.",
            "findings": [
                {
                    "item": "whole_numbers",
                    "status": "proven",
                    "summary": "Whole numbers covered.",
                    "citations": [{"outcome_id": "T-1.1.1", "quote": WHOLE}],
                },
                {
                    "item": "factors",
                    "status": "escalated",
                    "summary": "Factors await the teacher.",
                    "citations": [],
                },
                {
                    "item": "gaps",
                    "status": "escalated",
                    "summary": "T-1.1.2 stays a gap.",
                    "citations": [],
                },
            ],
            "gaps": "T-1.1.2 pending.",
            "kind": kind,
            "lessons": support.scheme_lessons(items=("whole_numbers", "factors", "gaps")),
        }


class AuditLogTest(TrustBase):
    def test_chain_verifies_and_tampering_breaks_it(self) -> None:
        audit.append(self.root, self.run_id, "run_started", {"model": "m"})
        audit.append(self.root, self.run_id, "tool_call", {"tool": "cite_outcome"})
        self.assertEqual({"ok": True, "events": 2}, audit.verify(self.root, self.run_id))
        path = self.root / "workspace/runs" / self.run_id / "audit.jsonl"
        lines = path.read_text().splitlines()
        forged = json.loads(lines[1])
        forged["detail"] = {"tool": "forged"}
        lines[1] = json.dumps(forged)
        path.write_text("\n".join(lines) + "\n")
        result = audit.verify(self.root, self.run_id)
        self.assertFalse(result["ok"])
        self.assertIn("entry 2", result["error"])

    def test_tool_calls_are_logged_refusals_included(self) -> None:
        self.tool("list_curriculum")
        CaseRecord(self.root, self.run_id).set_checklist(IDS_CHECKLIST)
        self.tool("read_curriculum", {"outcome_id": "T-1.1.2"})  # pending: refused
        entries = audit.read(self.root, self.run_id)
        self.assertEqual(
            ["list_curriculum", "read_curriculum"],
            [e["detail"]["tool"] for e in entries],
        )
        self.assertIn("not transcribed yet", entries[1]["detail"]["error"])
        self.assertTrue(audit.verify(self.root, self.run_id)["ok"])

    def test_loop_logs_started_and_stopped(self) -> None:
        fake = support.scripted(self.root, [support.TEACH_LIST])
        result = run_agent(root=self.root, client=fake.client, turns=1)
        events = [e["event"] for e in audit.read(self.root, result["run_id"])]
        self.assertEqual(["run_started", "tool_call", "run_stopped"], events)
        self.assertTrue(audit.verify(self.root, result["run_id"])["ok"])


class TeachingChecklistTest(TrustBase):
    def test_set_comparison_passes_when_every_outcome_is_named(self) -> None:
        result = verify_teaching_checklist.run_verification(self.ctx(), IDS_CHECKLIST)
        self.assertEqual((True, 1.0, ""), (result["passed"], result["score"], result["feedback"]))
        self.assertEqual([], [c for c in self.fake.calls if c[0] == "respond"])

    def test_missing_outcomes_fail_with_names_and_score(self) -> None:
        result = verify_teaching_checklist.run_verification(
            self.ctx(), support.TEACH_CHECKLIST[1]["items"]
        )
        self.assertFalse(result["passed"])
        self.assertEqual(0.0, result["score"])
        for oid in ("T-1.1.1", "T-1.1.2", "T-1.2.1"):
            self.assertIn(oid, result["feedback"])

    def test_set_checklist_tool_routes_to_the_set_comparison(self) -> None:
        run_id = self.verified_run()
        refused = self.tool(
            "set_checklist", support.TEACH_CHECKLIST[1], run_id
        )
        self.assertEqual("checklist refused", refused["error"])
        self.assertIn("T-1.2.1", refused["feedback"])
        accepted = self.tool("set_checklist", {"items": IDS_CHECKLIST}, run_id)
        self.assertEqual(
            ["whole_numbers", "factors", "gaps"], accepted["checklist"]
        )

    def test_roots_without_a_pack_keep_the_legal_judge(self) -> None:
        (self.root / "curriculum/grade7-mathematics-term1.json").unlink()
        run_id = self.verified_run()
        refused = self.tool(
            "set_checklist", support.PARTIAL_CHECKLIST[1], run_id
        )
        self.assertEqual("checklist refused", refused["error"])
        self.assertIn("leaves out an area", refused["feedback"])


class SchemeRulesTest(TrustBase):
    def test_good_document_passes(self) -> None:
        CaseRecord(self.root, self.run_id).set_checklist(IDS_CHECKLIST)
        self.settle_all(self.run_id)
        result = verify_scheme.run_verification(self.ctx(), self.document())
        self.assertEqual((True, []), (result["passed"], result["feedback"]))

    def test_open_items_and_open_requests_are_problems(self) -> None:
        CaseRecord(self.root, self.run_id).set_checklist(IDS_CHECKLIST)
        self.tool(
            "cite_outcome",
            {
                "item": "whole_numbers",
                "outcome_id": "T-1.1.1",
                "quote": WHOLE,
                "claim": "covered",
            },
        )
        result = verify_scheme.run_verification(self.ctx(), self.document())
        self.assertFalse(result["passed"])
        self.assertTrue(any("factors is still open" in p for p in result["feedback"]))
        self.tool("ask_teacher", {"item": "factors", "question": "open?"})
        result = verify_scheme.run_verification(self.ctx(), self.document())
        self.assertTrue(any("R1" in p and "still open" in p for p in result["feedback"]))

    def test_invented_quotes_are_problems(self) -> None:
        CaseRecord(self.root, self.run_id).set_checklist(IDS_CHECKLIST)
        self.settle_all(self.run_id)
        document = self.document()
        document["findings"][0]["citations"] = [
            {"outcome_id": "T-1.1.1", "quote": "invented words here"}
        ]
        result = verify_scheme.run_verification(self.ctx(), document)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("does not match a recorded citation" in p for p in result["feedback"])
        )

    def test_verified_filing_waits_for_signoff(self) -> None:
        run_id = self.verified_run()
        CaseRecord(self.root, run_id).set_checklist(IDS_CHECKLIST)
        self.settle_all(run_id)
        result = self.tool("submit_document", self.document(), run_id)
        self.assertEqual(
            ("awaiting_signoff", "awaiting_signoff"),
            (result["status"], result["document"]),
        )


class ClaimsFailClosedTest(TrustBase):
    def test_unreadable_judgement_refuses(self) -> None:
        original = self.fake.responder

        def garbage(kind, payload):
            if kind == "respond" and "tools" not in payload:
                return {"output_text": "not-json{{{"}
            return original(kind, payload)

        self.fake.responder = garbage
        result = verify_claims.run_verification(self.ctx(), support.MEMO[1])
        self.assertFalse(result["passed"])
        self.assertEqual([verify_claims.UNREADABLE], result["feedback"])

    def test_judge_override_uses_that_model(self) -> None:
        verify_claims.run_verification(self.ctx(), support.MEMO[1], judge="judge-model")
        judged = [c[1] for c in self.fake.calls if c[0] == "respond"][-1]
        self.assertEqual("judge-model", judged["model"])

    def test_judge_model_differs_from_agent_model_by_default(self) -> None:
        saved = os.environ.pop("JUDGE_MODEL", None)

        def restore() -> None:
            if saved is None:
                os.environ.pop("JUDGE_MODEL", None)
            else:
                os.environ["JUDGE_MODEL"] = saved

        self.addCleanup(restore)
        self.assertNotEqual(model(), judge_model())


class EscalateTest(TrustBase):
    def test_escalate_opens_a_coded_request_and_the_run_resumes_on_answer(
        self,
    ) -> None:
        CaseRecord(self.root, self.run_id).set_checklist(IDS_CHECKLIST)
        result = self.tool(
            "escalate",
            {
                "item": "factors",
                "reason_code": "missing_outcome_text",
                "need": "Outcome T-1.2.1 wording is missing",
            },
        )
        self.assertEqual(
            ("escalated", "R1", "missing_outcome_text"),
            (result["status"], result["request"], result["reason_code"]),
        )
        save_progress(self.root, self.run_id, [], status="escalated")
        self.assertIsNone(resume(self.root, self.run_id)["message"])
        CaseRecord(self.root, self.run_id).answer_request("R1", "use the draft wording")
        step = resume(self.root, self.run_id)
        self.assertIn("R1", step["message"])

    def test_escalate_in_the_loop_stops_as_escalated(self) -> None:
        fake = support.scripted(
            self.root,
            [
                ("set_checklist", {"items": IDS_CHECKLIST}),
                (
                    "escalate",
                    {
                        "item": "factors",
                        "reason_code": "timetable_clash",
                        "need": "Friday slot is a staff meeting",
                    },
                ),
            ],
        )
        result = run_agent(root=self.root, client=fake.client, turns=5)
        self.assertEqual("escalated", result["status"])

    def test_escalate_refuses_bad_codes_busy_runs_and_covered_items(self) -> None:
        CaseRecord(self.root, self.run_id).set_checklist(IDS_CHECKLIST)
        bad = self.tool(
            "escalate",
            {"item": "factors", "reason_code": "nope", "need": "x"},
        )
        self.assertIn("unknown reason code", bad["error"])
        internal = self.tool(
            "escalate",
            {"item": "factors", "reason_code": "memo_refused", "need": "x"},
        )
        self.assertIn("not for the agent to raise", internal["error"])
        self.tool(
            "ask_teacher", {"item": "factors", "question": "first?"}
        )
        busy = self.tool(
            "escalate",
            {"item": "gaps", "reason_code": "calendar_clash", "need": "x"},
        )
        self.assertIn("already open", busy["error"])

    def test_open_request_rejects_unknown_reason_codes(self) -> None:
        case = CaseRecord(self.root, self.run_id)
        case.set_checklist(IDS_CHECKLIST)
        with self.assertRaisesRegex(CaseError, "unknown reason code"):
            case.open_request("factors", "x", "nope", [])

    def test_three_refused_documents_escalate(self) -> None:
        run_id = self.verified_run()
        CaseRecord(self.root, run_id).set_checklist(IDS_CHECKLIST)
        bad = dict(self.document(), findings=[])
        for _ in range(2):
            refused = self.tool("submit_document", bad, run_id)
            self.assertEqual("document refused", refused["error"])
        escalated = self.tool("submit_document", bad, run_id)
        self.assertEqual("escalated", escalated["status"])
        self.assertEqual("document_refused", escalated["reason_code"])
        self.assertEqual(
            "document_refused",
            CaseRecord(self.root, run_id).data["requests"][0]["rule"],
        )


class IndependentVerifyTest(TrustBase):
    def filed_run(self) -> str:
        run_id = self.verified_run()
        CaseRecord(self.root, run_id).set_checklist(IDS_CHECKLIST)
        self.settle_all(run_id)
        filed = self.tool("submit_document", self.document(), run_id)
        self.assertEqual("awaiting_signoff", filed["status"])
        return run_id

    def test_independent_pass_recomputes_hashes_and_uses_the_judge(self) -> None:
        run_id = self.filed_run()
        judge = support.scripted(self.root, [])
        ctx = tools.Context(
            judge.client, self.root, run_id, CaseRecord(self.root, run_id), True
        )
        first = independent_verify.run_independent_verification(ctx, "judge-model")
        self.assertTrue(first["passed"])
        self.assertEqual({}, first["problems"])
        memo = CaseRecord(self.root, run_id).data["memo"]
        self.assertEqual(independent_verify.document_hash(memo), first["document_sha256"])
        judged = [c[1] for c in judge.calls if c[0] == "respond"][-1]
        self.assertEqual("judge-model", judged["model"])
        ctx = tools.Context(
            judge.client, self.root, run_id, CaseRecord(self.root, run_id), True
        )
        again = independent_verify.run_independent_verification(ctx, "judge-model")
        self.assertEqual(first["document_sha256"], again["document_sha256"])
        saved = independent_verify.save(self.root, run_id, first)
        self.assertTrue(saved["passed"])

    def test_independent_detects_a_tampered_document(self) -> None:
        run_id = self.filed_run()
        before = CaseRecord(self.root, run_id).data["memo"]
        old_hash = independent_verify.document_hash(before)
        path = self.root / "workspace/case_records" / f"{run_id}.json"
        record = json.loads(path.read_text())
        record["memo"]["findings"][0]["citations"][0]["quote"] = "forged words"
        path.write_text(json.dumps(record))
        ctx = tools.Context(
            self.client, self.root, run_id, CaseRecord(self.root, run_id), True
        )
        result = independent_verify.run_independent_verification(ctx, "judge-model")
        self.assertFalse(result["passed"])
        self.assertTrue(result["problems"]["scheme"])
        self.assertNotEqual(old_hash, result["document_sha256"])

    def test_independent_fails_closed_when_judge_equals_agent(self) -> None:
        run_id = self.filed_run()
        result = independent_verify.run_independent_verification(
            self.ctx(run_id), model()
        )
        self.assertFalse(result["passed"])
        self.assertIn("must differ", result["problems"]["claims"][0])

    def test_independent_refuses_non_teaching_documents(self) -> None:
        case = CaseRecord(self.root, self.run_id)
        case.set_checklist([support.checklist_item("not_ready")])
        case.file_memo({"conclusion": "c", "findings": [], "gaps": "g"}, "unverified")
        result = independent_verify.run_independent_verification(
            self.ctx(), "judge-model"
        )
        self.assertFalse(result["passed"])
        self.assertIn("not a teaching document", result["problems"]["document"][0])
        path = self.root / "workspace/case_records" / f"{self.run_id}.json"
        record = json.loads(path.read_text())
        del record["memo"]["kind"]  # filed before the trust layer
        path.write_text(json.dumps(record))
        legacy = independent_verify.run_independent_verification(
            self.ctx(), "judge-model"
        )
        self.assertFalse(legacy["passed"])
        self.assertIn("before the trust layer", legacy["problems"]["document"][0])


class ReviewConsoleTest(TrustBase):
    def filed_run(self, kind: str = "scheme") -> str:
        CaseRecord(self.root, self.run_id).set_checklist(IDS_CHECKLIST)
        self.settle_all(self.run_id)
        document = self.document(kind)
        if kind == "exam":
            document["exam"] = {
                "blueprint": {
                    "total_marks": 7,
                    "sections": [
                        {"outcome_id": "T-1.1.1", "questions": 1, "marks_each": 4},
                        {"outcome_id": "T-1.2.1", "questions": 1, "marks_each": 3},
                    ],
                },
                "questions": [
                    {
                        "id": "Q1",
                        "text": "Round 45678 to the nearest thousand.",
                        "marks": 4,
                        "answer": "46000.",
                        "outcome_id": "T-1.1.1",
                    },
                    {
                        "id": "Q2",
                        "text": "List all factors of 36.",
                        "marks": 3,
                        "answer": "1, 2, 3, 4, 6, 9, 12, 18, 36.",
                        "outcome_id": "T-1.2.1",
                    },
                ],
                "marking_scheme": [
                    {"question_id": "Q1", "answer": "46000.", "marks": 4},
                    {
                        "question_id": "Q2",
                        "answer": "1, 2, 3, 4, 6, 9, 12, 18, 36.",
                        "marks": 3,
                    },
                ],
            }
        filed = self.tool("submit_document", document)
        self.assertEqual("answered", filed["status"])
        return self.run_id

    def test_list_shows_curriculum_text_beside_each_row(self) -> None:
        run_id = self.filed_run()
        rows = item_rows(self.root, run_id)
        self.assertEqual(["whole_numbers", "factors", "gaps"], [r["item"] for r in rows])
        whole = rows[0]
        self.assertEqual("T-1.1.1", whole["curriculum"][0]["outcome_id"])
        self.assertEqual(WHOLE, whole["curriculum"][0]["outcome_text"])
        gaps = rows[2]["curriculum"]
        self.assertEqual("T-1.1.2", gaps[0]["outcome_id"])
        self.assertEqual("pending_transcription", gaps[0]["status"])
        self.assertIsNone(gaps[0]["outcome_text"])
        text = render(rows)
        self.assertIn("T-1.1.1", text)
        self.assertIn("Learners count", text)

    def test_item_approve_reject_and_edit(self) -> None:
        run_id = self.filed_run()
        case = CaseRecord(self.root, run_id)
        approved = case.review_item("whole_numbers", "approved", "looks right")
        self.assertEqual("approved", approved["decision"])
        with self.assertRaisesRegex(CaseError, "needs notes"):
            case.review_item("factors", "rejected", "")
        case.review_item("factors", "rejected", "say which weeks")
        edited = case.review_item("gaps", "edited", "T-1.1.2 stays a gap for now.")
        self.assertEqual("edited", edited["decision"])
        memo = CaseRecord(self.root, run_id).data["memo"]
        self.assertEqual(
            "T-1.1.2 stays a gap for now.",
            [f for f in memo["findings"] if f["item"] == "gaps"][0]["summary"],
        )
        with self.assertRaisesRegex(CaseError, "unknown checklist item"):
            case.review_item("nope", "approved")

    def test_exam_needs_hod_after_teacher(self) -> None:
        run_id = self.filed_run(kind="exam")
        case = CaseRecord(self.root, run_id)
        with self.assertRaisesRegex(CaseError, "after the teacher"):
            case.hod_review(True)
        teacher = case.review_memo(True, "fine")
        self.assertEqual("awaiting_hod", teacher["status"])
        save_progress(self.root, run_id, [], status="awaiting_signoff")
        waiting = resume(self.root, run_id)
        self.assertIsNone(waiting["message"])
        self.assertIn("head of department", waiting["note"])
        hod = CaseRecord(self.root, run_id).hod_review(True, "cleared")
        self.assertEqual("approved", hod["status"])
        done = resume(self.root, run_id)
        self.assertEqual((None, "done"), (done["message"], done["status"]))

    def test_hod_rejection_goes_back_to_the_agent(self) -> None:
        run_id = self.filed_run(kind="exam")
        case = CaseRecord(self.root, run_id)
        case.review_memo(True, "fine")
        CaseRecord(self.root, run_id).hod_review(False, "fix the gaps list")
        save_progress(self.root, run_id, [], status="awaiting_signoff")
        step = resume(self.root, run_id)
        self.assertIn("head of department rejected", step["message"])
        self.assertIn("fix the gaps list", step["message"])

    def test_hod_refuses_non_exam_documents(self) -> None:
        run_id = self.filed_run(kind="scheme")
        CaseRecord(self.root, run_id).review_memo(True, "fine")
        with self.assertRaisesRegex(CaseError, "only exam documents"):
            CaseRecord(self.root, run_id).hod_review(True)

    def test_teacher_rejection_sends_notes_back(self) -> None:
        run_id = self.filed_run()
        CaseRecord(self.root, run_id).review_memo(False, "tighten the conclusion")
        save_progress(self.root, run_id, [], status="awaiting_signoff")
        step = resume(self.root, run_id)
        self.assertIn("rejected", step["message"])
        self.assertIn("tighten the conclusion", step["message"])

    def test_scheme_approval_ends_the_run(self) -> None:
        run_id = self.filed_run()
        CaseRecord(self.root, run_id).review_memo(True, "fine")
        save_progress(self.root, run_id, [], status="awaiting_signoff")
        done = resume(self.root, run_id)
        self.assertEqual((None, "done"), (done["message"], done["status"]))


if __name__ == "__main__":
    unittest.main()
