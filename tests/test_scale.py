"""Phase 6 scale and operate: golden evals, model routing, dashboard,
multi-pack loading, retention. Offline; live paths take injected clients."""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path

from evals.runner import load_tasks, run_all
from pipeline import alerts as pipeline_alerts
from routing import performance, registry, shadow
from routing.table import RoutingError, resolve, resolve_pair
from scripts import dashboard
from scripts.retention import expired, purge
from tests import support


def tmpdir(test: unittest.TestCase) -> Path:
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return Path(tmp.name)


def clean_env(test: unittest.TestCase, *names: str) -> None:
    saved = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)

    def restore() -> None:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    test.addCleanup(restore)


class EvalRunnerTest(unittest.TestCase):
    def test_offline_tasks_pass_and_pending_packs_skip(self) -> None:
        report = run_all(load_tasks(), workdir=tmpdir(self))
        self.assertEqual([], [t for t in report["tasks"] if not t["pass"]])
        self.assertEqual((11, 0, 2), (report["passed"], report["failed"], report["skipped"]))
        skipped = sorted(t["id"] for t in report["tasks"] if t.get("skipped"))
        self.assertEqual(["math-level-8-scheme", "science-scheme"], skipped)

    def test_refusal_goldens_pin_their_errors(self) -> None:
        report = run_all(load_tasks(), workdir=tmpdir(self), only="originality-refusal")
        self.assertEqual(1, report["passed"])
        report = run_all(load_tasks(), workdir=tmpdir(self), only="lesson-timing-refusal")
        self.assertEqual(1, report["passed"])

    def test_live_run_scores_with_an_injected_client(self) -> None:
        root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        actions = [
            ("set_checklist", {"items": [
                {"id": "whole_numbers", "question": "Cover T-1.1.1",
                 "evidence_needed": "Outcome T-1.1.1 exact text"}]}),
            ("cite_outcome", {
                "item": "whole_numbers", "outcome_id": "T-1.1.1",
                "quote": support.WHOLE_NUMBERS_TEXT, "claim": "covered"}),
            ("submit_document", {
                "conclusion": "Done.", "gaps": "None.",
                "findings": [{"item": "whole_numbers", "status": "proven",
                              "summary": "Covered.",
                              "citations": [{"outcome_id": "T-1.1.1",
                                             "quote": support.WHOLE_NUMBERS_TEXT}]}],
                "lessons": support.scheme_lessons(items=("whole_numbers",))}),
        ]
        fake = support.scripted(root, actions)
        task = {
            "id": "live-smoke", "subject": "mathematics", "level": 7,
            "pack": "tiny-pack", "mode": "live", "objective": "File one item.",
            "expect": {"status": "answered", "cited": ["T-1.1.1"]},
        }
        report = run_all([task], workdir=tmpdir(self), live=True, client=fake.client)
        self.assertEqual(1, report["passed"])

    def test_shadow_compares_judges_on_filed_memos(self) -> None:
        clean_env(self, "JUDGE_MODEL")
        root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        support.write_pack(root)
        fake = support.scripted(root, [])
        report = run_all(
            load_tasks(), workdir=tmpdir(self), only="exam-filing",
            client=fake.client, shadow_judge="judge-model",
        )
        task = report["tasks"][0]
        self.assertTrue(task["pass"])
        self.assertTrue(task["shadow"]["compared"])
        self.assertTrue(task["shadow"]["agree"])


class RoutingTest(unittest.TestCase):
    def test_static_table_defaults_and_roles(self) -> None:
        clean_env(self, "MODEL_API_MODEL", "JUDGE_MODEL")
        self.assertEqual("muse-spark-1.3", resolve("agent"))
        self.assertEqual("muse-spark-1.3-judge", resolve("judge"))
        with self.assertRaises(RoutingError):
            resolve("nope")

    def test_judge_never_equals_generator(self) -> None:
        generator, judge = resolve_pair("model-a", "model-b")
        self.assertEqual(("model-a", "model-b"), (generator, judge))
        with self.assertRaisesRegex(RoutingError, "must differ"):
            resolve_pair("same", "same")

    def test_registry_prices_and_cost(self) -> None:
        var = tmpdir(self)
        self.assertEqual({}, registry.prices(var))
        self.assertIsNone(registry.cost_usd(var, "muse-spark-1.3", 1000, 1000))
        prices_dir = var / "routing"
        prices_dir.mkdir(parents=True)
        (prices_dir / "prices.json").write_text(json.dumps(
            {"muse-spark-1.3": {"in_per_1k": 3.0, "out_per_1k": 6.0}}))
        self.assertEqual(4.5, registry.cost_usd(var, "muse-spark-1.3", 1000, 250))
        self.assertIsNone(registry.cost_usd(var, "unknown-model", 1, 1))
        with self.assertRaises(registry.RegistryError):
            registry.get("unknown-model")

    def test_performance_chooses_after_min_samples(self) -> None:
        var = tmpdir(self)
        for _ in range(5):
            performance.record(var, "t", "agent", "model-a", True)
        for _ in range(5):
            performance.record(var, "t", "agent", "model-b", False)
        self.assertEqual("model-a", performance.choose(var, "agent"))
        self.assertIsNone(performance.choose(var, "judge"))
        stats = performance.stats(var, "agent")
        self.assertEqual((1.0, 0.0), (stats["model-a"]["pass_rate"], stats["model-b"]["pass_rate"]))

    def test_shadow_returns_primary_and_logs(self) -> None:
        var = tmpdir(self)
        self.assertEqual("p", shadow.compare(var, "t", "p", "s", lambda model: "p"))
        self.assertEqual("p", shadow.compare(var, "t", "p", "s", lambda model: "other"))
        def boom(model: str):
            raise RuntimeError("down")
        self.assertEqual("p", shadow.compare(var, "t", "p", "s", boom))
        log = shadow.log(var)
        self.assertEqual([True, False, None], [e["agree"] for e in log])
        self.assertIn("down", log[2]["error"])


class DashboardTest(unittest.TestCase):
    def fixture(self) -> tuple:
        root = tmpdir(self)
        var = root / "var"
        (root / "curriculum").mkdir(parents=True)
        (root / "curriculum/grade7-mathematics-term1.json").write_text(
            json.dumps(support.TINY_PACK))
        runs = root / "workspace/runs"
        records = root / "workspace/case_records"
        (runs / "run-a").mkdir(parents=True)
        (runs / "run-b").mkdir(parents=True)
        records.mkdir(parents=True)
        (runs / "run-a/progress.json").write_text(json.dumps({
            "run_id": "run-a", "status": "answered", "turn": 3, "model": "model-a",
            "turns": [{"turn": 1, "input_tokens": 1000, "output_tokens": 250}]}))
        (runs / "run-b/progress.json").write_text(json.dumps({
            "run_id": "run-b", "status": "needs_input", "turn": 1, "model": "model-b",
            "turns": [{"turn": 1, "input_tokens": 500, "output_tokens": 0}]}))
        (runs / "run-a/independent_verification.json").write_text(
            json.dumps([{"passed": True}]))
        (runs / "run-b/independent_verification.json").write_text(
            json.dumps([{"passed": False}]))
        (records / "run-a.json").write_text(json.dumps({
            "checklist": {}, "facts": [],
            "requests": [
                {"id": "R1", "rule": "teacher_input", "status": "answered"},
                {"id": "R2", "rule": "missing_outcome_text", "status": "open"}],
            "memo": {"kind": "scheme", "status": "approved",
                     "item_reviews": {"a": {"decision": "approved"}, "b": {"decision": "edited"}}},
            "figures": [{"id": "fig-1"}], "lesson_plans": []}))
        (records / "run-b.json").write_text(json.dumps({
            "checklist": {}, "facts": [], "requests": [], "memo": None,
            "figures": [], "lesson_plans": [{"id": "LP1"}]}))
        (var / "routing").mkdir(parents=True)
        (var / "routing/prices.json").write_text(json.dumps(
            {"model-a": {"in_per_1k": 3.0, "out_per_1k": 6.0}}))
        pipeline_alerts.record(var, "warning", "https://kicd.ac.ke/", "slow <script>")
        pipeline_alerts.record(var, "error", "refresh", "boom")
        return root, var

    def test_collect_aggregates_everything(self) -> None:
        root, var = self.fixture()
        metrics = dashboard.collect(root, var)
        self.assertEqual(2, metrics["runs"]["total"])
        self.assertEqual({"answered": 1, "needs_input": 1}, metrics["runs"]["by_status"])
        self.assertEqual(0.5, metrics["pass_rate"])
        self.assertEqual(2, metrics["escalations"]["total"])
        self.assertEqual(1, metrics["escalations"]["open"])
        self.assertEqual(
            {"teacher_input": 1, "missing_outcome_text": 1},
            metrics["escalations"]["by_rule"])
        self.assertEqual(0.5, metrics["reviews"]["edit_rate"])
        self.assertEqual({"scheme/approved": 1}, metrics["reviews"]["memos"])
        self.assertEqual(4.5, metrics["cost"]["usd"])
        self.assertEqual(500, metrics["cost"]["unpriced_tokens"])
        self.assertFalse(metrics["scrape"]["fresh"])
        self.assertTrue(any("kicd.ac.ke" in s for s in metrics["scrape"]["stale"]))
        self.assertEqual((1, 1), (metrics["scrape"]["warnings"], metrics["scrape"]["errors"]))
        self.assertEqual((1, 1), (metrics["figures"], metrics["lesson_plans"]))

    def test_text_and_html_render_with_escaping(self) -> None:
        root, var = self.fixture()
        metrics = dashboard.collect(root, var)
        text = dashboard.render_text(metrics)
        self.assertIn("pass rate: 50%", text)
        self.assertIn("Cost: $4.5000", text)
        html = dashboard.render_html(metrics)
        self.assertIn("<title>Teaching agent - admin dashboard</title>", html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_alerts_record_thresholds(self) -> None:
        root, var = self.fixture()
        metrics = dashboard.collect(root, var)
        messages = dashboard.check_alerts(metrics, var)
        self.assertTrue(any("pass rate 50%" in m for m in messages))
        self.assertTrue(any(m.startswith("[warning] stale:") for m in messages))
        logged = pipeline_alerts.list_alerts(var)
        self.assertGreater(len(logged), 2)


class LoaderPacksTest(unittest.TestCase):
    def test_default_pack_loads_and_unknown_combos_refuse(self) -> None:
        from curriculum.loader import PackError, load_pack

        repo = Path(__file__).resolve().parents[1]
        pack = load_pack(repo / "curriculum/grade7-mathematics-term1.json")
        self.assertEqual("grade7-mathematics-term1", pack["pack"]["id"])
        other = dict(support.TINY_PACK)
        other["pack"] = dict(other["pack"], learning_area="Science")
        path = tmpdir(self) / "science.json"
        path.write_text(json.dumps(other))
        with self.assertRaisesRegex(PackError, "unsupported pack"):
            load_pack(path)

    def test_pack_id_override(self) -> None:
        from edu_kit.tools import pack as pack_loader

        clean_env(self, "CURRICULUM_PACK", "TEACHING_PACK_DIR")
        self.assertEqual("grade7-mathematics-term1", pack_loader.pack_id())
        os.environ["TEACHING_PACK_DIR"] = "./packs/grade7-cre-term1"
        self.assertEqual("grade7-cre-term1", pack_loader.pack_id())
        os.environ["TEACHING_PACK_DIR"] = "/abs/packs/grade7-french-term1"
        self.assertEqual("grade7-french-term1", pack_loader.pack_id())
        os.environ["CURRICULUM_PACK"] = "science-grade7-term1"
        self.assertEqual("science-grade7-term1", pack_loader.pack_id())
        self.assertTrue(str(pack_loader.path(Path("/r"))).endswith("science-grade7-term1.json"))

    def test_all_subject_packs_load(self) -> None:
        from curriculum.loader import SUPPORTED, coverage, load_pack

        repo = Path(__file__).resolve().parents[1]
        files = sorted((repo / "curriculum").glob("grade7-*.json"))
        self.assertEqual(6, len(files))
        areas = set()
        for path in files:
            pack = load_pack(path)
            areas.add(pack["pack"]["learning_area"])
            self.assertGreaterEqual(coverage(pack)["total"], 1)
        self.assertEqual(areas, {a for a, _, _ in SUPPORTED})

    def test_enrichment_fields_are_optional_but_shaped(self) -> None:
        import copy
        import json

        from curriculum.loader import PackError, load_pack

        pack = copy.deepcopy(support.TINY_PACK)
        path = tmpdir(self) / "pack.json"
        path.write_text(json.dumps(pack))
        load_pack(path)
        pack["strands"][0]["sub_strands"][0]["outcomes"][0]["assessment"] = "observe"
        path.write_text(json.dumps(pack))
        with self.assertRaises(PackError):
            load_pack(path)

    def test_resolve_prefers_run_pack_then_env_then_default(self) -> None:
        from edu_kit.tools import pack as pack_loader

        root = tmpdir(self)
        (root / "curriculum").mkdir()
        (root / "curriculum/grade7-mathematics-term1.json").write_text("{}")
        clean_env(self, "CURRICULUM_PACK", "TEACHING_PACK_DIR")
        self.assertEqual(
            "grade7-mathematics-term1.json",
            pack_loader.resolve(root, "grade7-cre-term1").name,
        )
        (root / "curriculum/grade7-cre-term1.json").write_text("{}")
        self.assertEqual(
            "grade7-cre-term1.json", pack_loader.resolve(root, "grade7-cre-term1").name
        )
        os.environ["TEACHING_PACK_DIR"] = "./packs/grade7-cre-term1"
        self.assertEqual("grade7-cre-term1.json", pack_loader.resolve(root).name)
        self.assertIsNone(pack_loader.resolve(tmpdir(self)))

    def test_runs_store_their_pack(self) -> None:
        from edu_kit.case_record import CaseRecord
        from edu_kit.progress import load_progress, new_run

        clean_env(self, "CURRICULUM_PACK", "TEACHING_PACK_DIR")
        os.environ["TEACHING_PACK_DIR"] = "./packs/grade7-english-term1"
        root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        os.environ["TEACHING_PACK_DIR"] = "./packs/grade7-english-term1"
        run_id = new_run(root, instructions="i", objective="o", verification=False)
        self.assertEqual("grade7-english-term1", load_progress(root, run_id)["pack"])
        self.assertEqual("grade7-english-term1", CaseRecord(root, run_id).data["pack"])

    def test_review_reads_the_runs_own_pack(self) -> None:
        import shutil

        from edu_kit.case_record import CaseRecord
        from edu_kit.progress import new_run
        from scripts.review import item_rows

        repo = Path(__file__).resolve().parents[1]
        clean_env(self, "CURRICULUM_PACK", "TEACHING_PACK_DIR")
        root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        support.write_pack(root)
        shutil.copy(
            repo / "curriculum/grade7-cre-term1.json",
            root / "curriculum/grade7-cre-term1.json",
        )
        os.environ["TEACHING_PACK_DIR"] = "./packs/grade7-cre-term1"
        run_id = new_run(root, instructions="i", objective="o", verification=False)
        CaseRecord(root, run_id).set_checklist(
            [{"id": "creation", "question": "Cover G7CRE-T1-1.1.1", "evidence_needed": "x"}]
        )
        os.environ["TEACHING_PACK_DIR"] = "./packs/grade7-mathematics-term1"
        rows = item_rows(root, run_id)
        self.assertEqual("G7CRE-T1-1.1.1", rows[0]["curriculum"][0]["outcome_id"])


class RetentionTest(unittest.TestCase):
    def fixture(self) -> Path:
        root = tmpdir(self)
        now = datetime.datetime.now(datetime.timezone.utc)
        for run_id, days in (("run-old", 100), ("run-new", 2)):
            folder = root / "workspace/runs" / run_id
            folder.mkdir(parents=True)
            started = (now - datetime.timedelta(days=days)).isoformat()
            (folder / "progress.json").write_text(json.dumps({"started": started}))
            records = root / "workspace/case_records"
            records.mkdir(parents=True, exist_ok=True)
            (records / f"{run_id}.json").write_text("{}")
        return root

    def test_expired_lists_old_runs_only(self) -> None:
        root = self.fixture()
        now = datetime.datetime.now(datetime.timezone.utc)
        self.assertEqual(["run-old"], expired(root, 90, now=now))
        self.assertEqual([], expired(root, 365, now=now))

    def test_purge_removes_only_the_run(self) -> None:
        root = self.fixture()
        (root / "curriculum").mkdir()
        (root / "curriculum/keep.json").write_text("{}")
        removed = purge(root, "run-old")
        self.assertEqual(2, len(removed))
        self.assertFalse((root / "workspace/runs/run-old").exists())
        self.assertFalse((root / "workspace/case_records/run-old.json").exists())
        self.assertTrue((root / "workspace/runs/run-new").exists())
        self.assertTrue((root / "curriculum/keep.json").exists())


if __name__ == "__main__":
    unittest.main()
