"""The golden-task runner: replay eval scripts, score the outcomes.

Each task in evals/tasks/*.json replays its script step by step against a
fresh fixture root (offline: no model calls; live: the agent free-runs).
Steps are tool calls ({"tool", "args", "expect_error"?, "expect_status"?})
or record ops ({"op": "answer_request"|"review_item"|"review_memo", ...}).

Final expectations (all optional): status, cited (outcome ids in the
facts), escalated, exam_total, memo (filed or not), figures (count),
lesson_plans (count), readback (specs the filed figures must match, in
order). Tasks whose pack file is absent skip with a reason instead of
failing: the set spans subjects and levels before every pack lands.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
OPS = ("answer_request", "review_item", "review_memo")


def load_tasks(tasks_dir: Path | None = None) -> list:
    """Every task, sorted by id."""
    folder = Path(tasks_dir) if tasks_dir else EVALS_DIR / "tasks"
    tasks = []
    for path in sorted(folder.glob("*.json")):
        task = json.loads(path.read_text())
        task["_path"] = str(path)
        tasks.append(task)
    return tasks


def fixture_root(pack: str, dest: Path) -> Path:
    """A fixture root for a task: curriculum pack + timetable under dest."""
    src = EVALS_DIR / "packs" / f"{pack}.json"
    if not src.is_file():
        raise FileNotFoundError(f"no pack fixture for {pack!r}")
    root = Path(dest)
    (root / "curriculum").mkdir(parents=True, exist_ok=True)
    (root / "curriculum" / "grade7-mathematics-term1.json").write_text(src.read_text())
    timetable = EVALS_DIR / "packs" / "timetable.json"
    if timetable.is_file():
        (root / "teacher_context").mkdir(exist_ok=True)
        shutil.copy(timetable, root / "teacher_context" / "timetable.json")
    return root


def run_offline(task: dict, workdir: Path, client=None) -> dict:
    """Replay a task's script; return {record, progress, status, failures}."""
    from edu_kit import tools
    from edu_kit.case_record import CaseRecord
    from edu_kit.progress import load_progress, new_run

    root = fixture_root(task["pack"], Path(workdir) / task["id"])
    run_id = new_run(
        root,
        instructions="eval",
        objective=task.get("objective", ""),
        verification=bool(task.get("verification", False)),
    )
    failures: list[str] = []
    status = "running"
    for n, step in enumerate(task.get("script", []), start=1):
        if "op" in step:
            _apply_op(root, run_id, step, failures, n)
            continue
        call = {
            "type": "function_call",
            "name": step["tool"],
            "arguments": json.dumps(step.get("args", {})),
            "call_id": f"eval-{n}",
        }
        result = tools.run(client, root, run_id, call)
        status = result.get("status", "running")
        want_error = step.get("expect_error")
        if want_error is not None and want_error not in json.dumps(result):
            failures.append(f"step {n} ({step['tool']}): expected error {want_error!r}")
        want_status = step.get("expect_status")
        if want_status is not None and status != want_status:
            failures.append(f"step {n} ({step['tool']}): status {status}, want {want_status}")
    record = CaseRecord(root, run_id).data
    progress = load_progress(root, run_id)
    failures.extend(evaluate(task.get("expect", {}), record, progress, status, root, run_id))
    return {
        "id": task["id"],
        "pass": not failures,
        "failures": failures,
        "status": status,
        "run_id": run_id,
    }


def _apply_op(root: Path, run_id: str, step: dict, failures: list, n: int) -> None:
    from edu_kit.case_record import CaseError, CaseRecord

    case = CaseRecord(root, run_id)
    try:
        if step["op"] == "answer_request":
            case.answer_request(step["id"], step.get("response", "ok"))
        elif step["op"] == "review_item":
            case.review_item(step["item"], step["decision"], step.get("notes", ""))
        elif step["op"] == "review_memo":
            case.review_memo(bool(step.get("approve", True)), step.get("notes", ""))
        else:
            failures.append(f"step {n}: unknown op {step['op']!r} (want one of {', '.join(OPS)})")
    except (CaseError, KeyError) as error:
        failures.append(f"step {n} ({step['op']}): {error}")


def evaluate(
    expect: dict, record: dict, progress: dict, status: str, root: Path, run_id: str
) -> list:
    """Final-state failures for one task (empty = pass)."""
    failures = []
    if "status" in expect and status != expect["status"]:
        failures.append(f"status {status}, want {expect['status']}")
    if "cited" in expect:
        cited = {f.get("outcome_id") for f in record.get("facts", [])}
        missing = [oid for oid in expect["cited"] if oid not in cited]
        if missing:
            failures.append(f"not cited: {', '.join(missing)}")
    if "escalated" in expect:
        escalated = bool(record.get("requests")) or status in ("needs_input", "escalated")
        if escalated != expect["escalated"]:
            failures.append(f"escalated {escalated}, want {expect['escalated']}")
    if "exam_total" in expect:
        total = ((record.get("memo") or {}).get("exam") or {}).get("blueprint", {}).get("total_marks")
        if total != expect["exam_total"]:
            failures.append(f"exam total {total}, want {expect['exam_total']}")
    if "memo" in expect:
        filed = record.get("memo") is not None
        if filed != expect["memo"]:
            failures.append(f"memo filed {filed}, want {expect['memo']}")
    if "figures" in expect:
        got = len(record.get("figures", []))
        if got != expect["figures"]:
            failures.append(f"{got} figures, want {expect['figures']}")
    if "lesson_plans" in expect:
        got = len(record.get("lesson_plans", []))
        if got != expect["lesson_plans"]:
            failures.append(f"{got} lesson plans, want {expect['lesson_plans']}")
    for n, spec in enumerate(expect.get("readback", [])):
        figures = record.get("figures", [])
        if n >= len(figures):
            failures.append(f"readback {n}: no such figure filed")
            continue
        failures.extend(_readback(spec, figures[n], root))
    return failures


def _readback(spec: dict, figure: dict, root: Path) -> list:
    from diagrams.readback import ReadbackError, compare, read

    try:
        svg_text = (root / figure["svg"]).read_text()
    except OSError as error:
        return [f"figure {figure.get('id')}: SVG unreadable: {error}"]
    try:
        parsed = read(svg_text)
    except ReadbackError as error:
        return [f"figure {figure.get('id')}: {error}"]
    return [f"figure {figure.get('id')}: {m}" for m in compare(spec, parsed)]


def run_live(task: dict, workdir: Path, client, turns: int = 20) -> dict:
    """Free-run a task with a real (or injected) client, then score it."""
    from edu_kit.case_record import CaseRecord
    from edu_kit.progress import load_progress
    from teaching_agent.loop import run_agent

    root = fixture_root(task["pack"], Path(workdir) / task["id"])
    (root / "objective.md").write_text(task.get("objective", ""))
    import os

    from edu_kit import settings

    real = settings.teaching_pack_dir
    settings.teaching_pack_dir = lambda _root: root  # noqa: E731
    saved, os.environ["VERIFICATION"] = os.environ.get("VERIFICATION"), (
        "on" if task.get("verification", False) else "off"
    )
    try:
        result = run_agent(root=root, client=client, turns=turns)
    finally:
        settings.teaching_pack_dir = real
        if saved is None:
            os.environ.pop("VERIFICATION", None)
        else:
            os.environ["VERIFICATION"] = saved
    record = CaseRecord(root, result["run_id"]).data
    progress = load_progress(root, result["run_id"])
    failures = evaluate(
        task.get("expect", {}), record, progress, result["status"], root, result["run_id"]
    )
    return {
        "id": task["id"],
        "pass": not failures,
        "failures": failures,
        "status": result["status"],
        "run_id": result["run_id"],
    }


def run_all(
    tasks: list | None = None,
    workdir: Path | None = None,
    live: bool = False,
    client=None,
    only: str | None = None,
    shadow_judge: str | None = None,
) -> dict:
    """Run tasks (offline replay, or live free-runs) and score them."""
    tasks = [t for t in (tasks if tasks is not None else load_tasks()) if only is None or t["id"] == only]
    tmp = tempfile.TemporaryDirectory() if workdir is None else None
    work = Path(workdir) if workdir else Path(tmp.name)
    results = []
    for task in tasks:
        if not (EVALS_DIR / "packs" / f"{task['pack']}.json").is_file():
            results.append(
                {"id": task["id"], "pass": True, "skipped": True,
                 "reason": f"pack {task['pack']} not landed yet", "failures": []}
            )
            continue
        if live or task.get("mode") == "live":
            if client is None:
                from edu_kit.client import make_client

                client = make_client()
            result = run_live(task, work, client)
        else:
            result = run_offline(task, work, client)
        if shadow_judge and not result.get("skipped"):
            result["shadow"] = _shadow(task, work, result["run_id"], client, shadow_judge)
        results.append(result)
    if tmp is not None:
        tmp.cleanup()
    passed = [r for r in results if r["pass"] and not r.get("skipped")]
    failed = [r for r in results if not r["pass"]]
    skipped = [r for r in results if r.get("skipped")]
    return {
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
        "tasks": results,
    }


def _shadow(task: dict, work: Path, run_id: str, client, shadow_judge: str) -> dict:
    """Shadow agreement: primary vs shadow judge on the filed memo, if any."""
    from edu_kit import tools
    from edu_kit.case_record import CaseRecord
    from scripts import independent_verify

    from routing.table import resolve_pair

    root = work / task["id"]
    if not (CaseRecord(root, run_id).data.get("memo")):
        return {"compared": False, "reason": "no memo filed"}
    ctx = tools.Context(client, root, run_id, CaseRecord(root, run_id), True)
    _, primary_judge = resolve_pair()
    primary = independent_verify.run_independent_verification(ctx, primary_judge)
    ctx = tools.Context(client, root, run_id, CaseRecord(root, run_id), True)
    shadow = independent_verify.run_independent_verification(ctx, shadow_judge)
    return {
        "compared": True,
        "primary": primary["passed"],
        "shadow": shadow["passed"],
        "agree": primary["passed"] == shadow["passed"],
    }
