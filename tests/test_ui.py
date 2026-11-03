"""The browser console (ui/): layout discovery, pack reading, timeline events, review
passthrough, and the HTTP API. Everything runs against demo repositories in temp
dirs; the real workspace is never touched."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from ui.make_demo import build as build_demo
from ui.ui import (
    Console,
    _walk_outcomes,
    build_events,
    make_handler,
)


def demo_root(test: unittest.TestCase) -> Path:
    root = Path(tempfile.mkdtemp(prefix="console-test-"))
    test.addCleanup(shutil.rmtree, root, True)
    build_demo(root)
    return root


class LayoutTest(unittest.TestCase):
    def test_rejects_a_folder_without_helper(self):
        empty = Path(tempfile.mkdtemp(prefix="console-empty-"))
        self.addCleanup(shutil.rmtree, empty, True)
        with self.assertRaises(RuntimeError):
            Console(empty)

    def test_accepts_the_flat_layout(self):
        console = Console(demo_root(self))
        self.assertTrue((console.agent / "helper").is_file())

    def test_accepts_the_old_nested_layout(self):
        outer = Path(tempfile.mkdtemp(prefix="console-nested-"))
        self.addCleanup(shutil.rmtree, outer, True)
        (outer / "agent").mkdir()
        (outer / "agent/helper").write_text("#!/bin/sh\n")
        console = Console(outer)
        self.assertEqual(console.agent, outer / "agent")

    def test_info_names_the_pack_task_and_model(self):
        info = Console(demo_root(self)).info()
        self.assertEqual(info["task"], "packs/grade7-maths-term2")
        self.assertEqual([t["id"] for t in info["tasks"]], ["packs/grade7-maths-term2"])
        self.assertIn("Term 2", info["tasks"][0]["title"])
        self.assertEqual(info["pack"]["files"], ["grade7_mathematics.sample.json"])
        self.assertTrue(info["pack"]["version"])
        self.assertEqual(info["model"], "demo-model")
        self.assertTrue(info["agent_ready"])
        self.assertFalse(info["api_key_configured"])

    def test_pack_hash_ignores_schema_json(self):
        root = demo_root(self)
        (root / "curriculum/schema.json").write_text('{"$schema": "x"}')
        info = Console(root).info()
        self.assertEqual(info["pack"]["files"], ["grade7_mathematics.sample.json"])

    def test_select_task_repoints_the_pack(self):
        root = demo_root(self)
        (root / "packs/second").mkdir()
        (root / "packs/second/objective.md").write_text("# Second pack\n")
        console = Console(root)
        console.select_task("packs/second")
        self.assertIn("TEACHING_PACK_DIR=./packs/second", (root / ".env").read_text())
        with self.assertRaises(FileNotFoundError):
            console.select_task("packs/missing")

    def test_select_task_refuses_while_a_job_runs(self):
        console = Console(demo_root(self))
        console.jobs.items.append({"run_id": "", "running": True, "returncode": None})
        with self.assertRaises(RuntimeError):
            console.select_task("packs/grade7-maths-term2")


class OutcomeTest(unittest.TestCase):
    def test_outcome_text_and_strand_context(self):
        found = Console(demo_root(self)).outcome("NUM.1.a")
        self.assertTrue(found["text"].startswith("read and write whole numbers"))
        self.assertEqual(found["sub_strand"], "NUM.1 Whole numbers")
        self.assertEqual(found["strand"], "NUM Numbers")
        self.assertEqual(found["subject"], "Mathematics")
        self.assertEqual(found["file"], "grade7_mathematics.sample.json")

    def test_unknown_outcome_is_not_found(self):
        with self.assertRaises(FileNotFoundError):
            Console(demo_root(self)).outcome("NOPE.1")

    def test_walk_accepts_text_and_outcome_text(self):
        data = {
            "strands": [
                {
                    "id": "S",
                    "name": "Strand",
                    "sub_strands": [
                        {
                            "id": "S.1",
                            "name": "Sub",
                            "outcomes": [
                                {"id": "A", "outcome_text": "new wording", "status": "transcribed"},
                                {"id": "B", "text": "old wording"},
                            ],
                        }
                    ],
                }
            ]
        }
        got = {o["id"]: o for o in _walk_outcomes(data, {})}
        self.assertEqual(got["A"]["text"], "new wording")
        self.assertEqual(got["A"]["status"], "transcribed")
        self.assertEqual(got["B"]["text"], "old wording")
        self.assertEqual(got["A"]["sub_strand"], "S.1 Sub")


RUN2 = "run-demo-2-awaiting-review"


def progress_for(name: str, args: dict, result: dict, status: str) -> dict:
    call = json.dumps(args)
    return {
        "run_id": "run-x",
        "started": "2026-11-02T09:00:00+00:00",
        "status": status,
        "turn": 1,
        "verification": True,
        "model": "m",
        "messages": [
            {"role": "user", "content": "task"},
            {"type": "function_call", "name": name, "call_id": "call_1", "arguments": call},
            {"type": "function_call_output", "call_id": "call_1", "output": json.dumps(result)},
        ],
        "turns": [
            {
                "turn": 1, "time": "2026-11-02T09:01:00+00:00", "saw": 1,
                "output": 2, "end": 3, "input_tokens": 5, "output_tokens": 6,
                "status": status, "model": "m",
            }
        ],
    }


class EventsTest(unittest.TestCase):
    def test_ask_teacher_becomes_an_escalation_with_the_request_text(self):
        progress = progress_for(
            "ask_teacher", {"item": "x", "question": "q?"},
            {"escalated": True, "request": "R1", "item": "x", "status": "needs_input"},
            "needs_input",
        )
        record = {"requests": [{"id": "R1", "item": "x", "rule": "teacher_input", "need": "q?"}]}
        kinds = {(e["event_type"], (e["payload"].get("rule"), e["payload"].get("need"))) for e in build_events(progress, record, None)}
        self.assertIn(("escalation", ("teacher_input", "q?")), kinds)

    def test_filed_document_for_signoff_asks_for_teacher_review(self):
        progress = progress_for(
            "submit_document", {"kind": "scheme"},
            {"filed": True, "document": "awaiting_signoff", "status": "awaiting_signoff"},
            "awaiting_signoff",
        )
        rules = [e["payload"].get("rule") for e in build_events(progress, {}, None) if e["event_type"] == "escalation"]
        self.assertIn("teacher_signoff", rules)

    def test_refused_document_becomes_a_failed_check(self):
        progress = progress_for(
            "submit_document", {"kind": "scheme"},
            {"error": "document refused", "check": "scheme", "problems": ["coverage short"]},
            "running",
        )
        failed = [e for e in build_events(progress, {}, None) if e["event_type"] == "verification" and e["payload"].get("passed") is False]
        self.assertEqual(failed[0]["payload"]["check"], "scheme")

    def test_checklist_draft_match_becomes_a_passed_check(self):
        progress = progress_for(
            "set_checklist", {"items": [{"id": "a"}]},
            {"checklist": {"a": {}}}, "running",
        )
        record = {"checklist_checks": [{"draft": ["a"], "passed": True, "score": 1.0, "feedback": "", "attempt": 1, "accepted": True}]}
        passed = [e for e in build_events(progress, record, None) if e["event_type"] == "verification" and e["payload"].get("passed") is True]
        self.assertEqual(passed[0]["payload"]["check"], "checklist")


class RunDetailTest(unittest.TestCase):
    def test_review_run_detail(self):
        detail = Console(demo_root(self)).run_detail(RUN2)
        self.assertEqual(detail["status"], "awaiting_signoff")
        self.assertTrue(detail["events"])
        self.assertEqual(detail["record"]["memo"]["status"], "awaiting_signoff")
        self.assertTrue(detail["audit_available"])
        self.assertGreaterEqual(detail["metrics"]["tool_calls"], 8)

    def test_unknown_run_is_not_found(self):
        with self.assertRaises(FileNotFoundError):
            Console(demo_root(self)).run_detail("run-missing")
        with self.assertRaises(FileNotFoundError):
            Console(demo_root(self)).run_detail("../escape")

    def test_figure_and_audit(self):
        console = Console(demo_root(self))
        body, kind = console.figure(RUN2, "fig-1")
        self.assertEqual(kind, "image/svg+xml")
        self.assertIn(b"<svg", body)
        with self.assertRaises(FileNotFoundError):
            console.figure(RUN2, "missing")
        with self.assertRaises(FileNotFoundError):
            console.figure(RUN2, "../x")
        audit = console.audit(RUN2)
        self.assertEqual(audit["total"], 4)
        self.assertEqual(audit["events"][0]["event"], "run_started")

    def test_review_rows_come_with_curriculum_text(self):
        rows = Console(demo_root(self)).review_rows(RUN2)["rows"]
        by_item = {r["item"]: r for r in rows}
        self.assertEqual(len(rows), 4)
        self.assertEqual(by_item["number_sense"]["curriculum"][0]["outcome_id"], "NUM.1.a")
        self.assertIn("whole numbers", by_item["number_sense"]["curriculum"][0]["outcome_text"])
        self.assertEqual(by_item["angles"]["curriculum"], [])

    def test_describe_lists_demo_tools(self):
        described = Console(demo_root(self)).describe()
        self.assertIn("Term 2", described["objective"])
        self.assertIsNone(described["tools_error"])
        self.assertEqual(len(described["tools"]), 8)

    def test_step_mode_control_roundtrip(self):
        console = Console(demo_root(self))
        self.assertFalse(console.control()["step"])
        console.set_control({"step": True})
        console.set_control({"next": True})
        control = console.control()
        self.assertTrue(control["step"])
        self.assertEqual(control["credits"], 1)

    def test_export_builds_fresh_bytes(self):
        console = Console(demo_root(self))
        data, kind, name = console.export_file(RUN2, "scheme", "pdf")
        self.assertTrue(data.startswith(b"%PDF-1.4"))
        self.assertEqual(kind, "application/pdf")
        self.assertEqual(name, f"{RUN2}-scheme.pdf")
        data, kind, _ = console.export_file(RUN2, "scheme", "docx")
        self.assertTrue(data.startswith(b"PK"))
        self.assertIn("wordprocessingml", kind)
        with self.assertRaises(RuntimeError):
            console.export_file("run-demo-1-needs-input", "scheme", "pdf")
        with self.assertRaises(RuntimeError):
            console.export_file(RUN2, "syllabus", "pdf")

    def test_send_returns_the_summary(self):
        result = Console(demo_root(self)).send_document(
            RUN2, "scheme", "pdf", "a@b.co", "S", ""
        )
        self.assertEqual(result["to"], ["a@b.co"])
        self.assertEqual(result["file"], f"{RUN2}-scheme.pdf")
        with self.assertRaises(RuntimeError):
            Console(demo_root(self)).send_document(RUN2, "scheme", "pdf", "nope", "", "")
        with self.assertRaises(RuntimeError):
            Console(demo_root(self)).send_document(RUN2, "scheme", "pdf", "  ", "", "")

    def test_info_reports_smtp_unconfigured(self):
        self.assertFalse(Console(demo_root(self)).info()["smtp_configured"])


class ActionsTest(unittest.TestCase):
    def test_answer_records_the_response(self):
        root = demo_root(self)
        console = Console(root)
        console.review("run-demo-1-needs-input", "answer", "Weeks 9-10.", request_id="R1")
        record = json.loads((root / "workspace/case_records/run-demo-1-needs-input.json").read_text())
        self.assertEqual(record["requests"][0]["status"], "answered")
        progress = json.loads((root / "workspace/runs/run-demo-1-needs-input/progress.json").read_text())
        self.assertEqual(progress["status"], "answered")

    def test_approve_and_item_and_hod_passthrough(self):
        root = demo_root(self)
        console = Console(root)
        console.review(RUN2, "approve", "fine", item="angles")
        memo = json.loads((root / "workspace/case_records" / f"{RUN2}.json").read_text())["memo"]
        self.assertEqual(memo["item_reviews"]["angles"]["decision"], "approved")
        console.review(RUN2, "approve", "good")
        memo = json.loads((root / "workspace/case_records" / f"{RUN2}.json").read_text())["memo"]
        self.assertEqual(memo["status"], "approved")

    def test_review_rejects_bad_decisions(self):
        console = Console(demo_root(self))
        with self.assertRaises(RuntimeError):
            console.review(RUN2, "maybe", "")
        with self.assertRaises(RuntimeError):
            console.review(RUN2, "edit", "new words")
        with self.assertRaises(RuntimeError):
            console.review(RUN2, "approve", "", item="../x")

    def test_verify_maps_the_document_check_to_memo(self):
        result = Console(demo_root(self)).verify(RUN2, "document")
        self.assertEqual(result["what"], "memo")
        self.assertFalse(result["passed"])
        self.assertTrue(any("DAT.1.a" in p for p in result["problems"]))
        with self.assertRaises(RuntimeError):
            Console(demo_root(self)).verify(RUN2, "nope")

    def test_reset_passes_through(self):
        message = Console(demo_root(self)).reset(False)["message"]
        self.assertIn("reset", message)


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.console = Console(demo_root(self))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.console))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        # Localhost must never go through a proxy, whatever the environment says.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path: str):
        with self.opener.open(f"http://127.0.0.1:{self.port}{path}") as response:
            return response.status, response.read()

    def post(self, path: str, body: dict):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_info_runs_and_detail(self):
        status, body = self.get("/api/info")
        self.assertEqual(status, 200)
        self.assertIn("grade7-maths-term2", body.decode())
        status, body = self.get("/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)), 3)
        status, body = self.get(f"/api/runs/{RUN2}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "awaiting_signoff")

    def test_outcome_figure_and_review_rows(self):
        status, body = self.get("/api/outcome?id=NUM.1.a")
        self.assertEqual(status, 200)
        self.assertIn("whole numbers", body.decode())
        status, body = self.get(f"/api/figure?run={RUN2}&id=fig-1")
        self.assertEqual(status, 200)
        self.assertIn(b"<svg", body)
        status, body = self.get(f"/api/runs/{RUN2}/review-rows")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["rows"]), 4)

    def test_review_and_verify_posts(self):
        status, _ = self.post(
            "/api/runs/run-demo-1-needs-input/review",
            {"decision": "answer", "notes": "Weeks 9-10.", "request_id": "R1"},
        )
        self.assertEqual(status, 200)
        status, body = self.post(f"/api/runs/{RUN2}/verify", {"what": "document"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["what"], "memo")
        status, body = self.post(f"/api/runs/{RUN2}/verify", {"what": "nope"})
        self.assertEqual(status, 409)
        self.assertIn("error", json.loads(body))

    def test_export_download_and_send_posts(self):
        with self.opener.open(
            f"http://127.0.0.1:{self.port}/api/export?run={RUN2}&what=scheme&format=pdf&download=1"
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "application/pdf")
            self.assertIn(f"{RUN2}-scheme.pdf", response.headers["Content-Disposition"])
            self.assertTrue(response.read().startswith(b"%PDF-1.4"))
        status, body = self.post(
            f"/api/runs/{RUN2}/send",
            {"what": "scheme", "format": "pdf", "to": "a@b.co", "subject": "S", "message": ""},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["to"], ["a@b.co"])
        status, body = self.post(
            f"/api/runs/{RUN2}/send",
            {"what": "scheme", "format": "pdf", "to": "nope", "subject": "", "message": ""},
        )
        self.assertEqual(status, 409)
        self.assertIn("error", json.loads(body))

    def test_index_and_unknown_paths(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Education Agent Console", body)
        try:
            self.get("/api/nope")
            self.fail("expected 404")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 404)

    def test_index_hides_email_and_marking_scheme(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        page = body.decode("utf-8")
        self.assertNotIn("Send email", page)
        self.assertNotIn("marking-scheme", page)
        self.assertNotIn("docSubject", page)
        self.assertNotIn("sendDoc", page)
        self.assertIn("Send answer and resume", page)
        self.assertIn("downloadDoc", page)
        self.assertIn("Preparing…", page)


if __name__ == "__main__":
    unittest.main()
