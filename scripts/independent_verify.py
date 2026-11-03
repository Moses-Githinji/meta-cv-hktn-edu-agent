#!/usr/bin/env python3
"""Independent verification: recompute everything about a filed teaching document.

./helper verify RUN_ID --independent

A separate process from the agent run. It reads only the saved artifacts (the
case record, the run's progress, the curriculum pack, the audit log) and
recomputes every check from scratch instead of trusting the inline results:

- the scheme rules (verification/verify_scheme.py) against the record + pack;
- the checklist set comparison (verification/verify_teaching_checklist.py);
- the claims judgement, with the independent judge model (JUDGE_MODEL), which
  must differ from the model that wrote the document (fails closed if equal);
- the hash chain of the run's audit log (edu_kit/audit.py).

It also hashes the filed document (SHA-256 over its canonical JSON) so any
later edit is detectable: re-running must reproduce the same hash.

The report is saved with the run (workspace/runs/RUN_ID/independent_verification.json);
the run itself is not changed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))  # after the test runner's own paths

from edu_kit import audit, tools  # noqa: E402
from edu_kit.case_record import CaseRecord  # noqa: E402
from edu_kit.client import make_client, MissingKeyError  # noqa: E402
from edu_kit.progress import load_progress, now  # noqa: E402
from edu_kit.settings import judge_model  # noqa: E402
from edu_kit.tools import pack as pack_loader  # noqa: E402
from verification import verify_claims, verify_scheme, verify_teaching_checklist  # noqa: E402

TEACHING_KINDS = ("scheme", "exam")


def document_hash(document: dict) -> str:
    """SHA-256 over the filed document's canonical JSON (conclusion, findings, gaps, kind, exam, lessons)."""
    canonical = json.dumps(
        {k: document.get(k) for k in ("conclusion", "findings", "gaps", "kind", "exam", "lessons")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_independent_verification(ctx: tools.Context, judge: str) -> dict:
    """Recompute every check for a run's filed document. Fails closed throughout."""
    record = ctx.case.data.get("memo")
    if not record:
        return _report(ctx, judge, None, {"document": ["no document has been filed"]})
    kind = record.get("kind")
    if kind not in TEACHING_KINDS:
        if kind is None:
            detail = "no kind recorded (filed before the trust layer); refile to verify"
        else:
            detail = f"not a teaching document (kind {kind!r})"
        return _report(ctx, judge, record, {"document": [detail]})
    document = {
        "conclusion": record.get("conclusion", ""),
        "findings": record.get("findings", []),
        "gaps": record.get("gaps", ""),
        "kind": record.get("kind"),
    }
    if record.get("exam") is not None:
        document["exam"] = record["exam"]
    if record.get("lessons") is not None:
        document["lessons"] = record["lessons"]
    agent_model = load_progress(ctx.root, ctx.run_id).get("model")
    problems: dict[str, list] = {}

    scheme = verify_scheme.run_verification(ctx, document)
    if not scheme.get("passed"):
        problems["scheme"] = [str(p) for p in scheme.get("feedback") or ["refused"]]

    if pack_loader.exists(ctx.root):
        keys = ("question", "evidence_needed")
        items = [
            {"id": k, **{f: v.get(f) for f in keys}}
            for k, v in ctx.case.data["checklist"].items()
        ]
        checklist = verify_teaching_checklist.run_verification(ctx, items)
        if not checklist.get("passed"):
            problems["checklist"] = [str(checklist.get("feedback") or "refused")]
        checklist_score = checklist.get("score")
    else:
        problems["checklist"] = ["the curriculum pack is missing: cannot recompute coverage"]
        checklist_score = None

    from routing.table import RoutingError, resolve_pair

    try:
        resolve_pair(agent_model, judge)
    except RoutingError as error:
        problems["claims"] = [str(error)]
    else:
        claims = verify_claims.run_verification(ctx, document, judge=judge)
        if not claims.get("passed"):
            problems["claims"] = [str(p) for p in claims.get("feedback") or ["refused"]]

    chain = audit.verify(ctx.root, ctx.run_id)
    if not chain.get("ok"):
        problems["audit"] = [str(chain.get("error") or "audit chain broken")]

    report = _report(ctx, judge, record, problems)
    report["agent_model"] = agent_model
    report["checklist_score"] = checklist_score
    report["audit_events"] = chain.get("events", 0)
    return report


def _report(
    ctx: tools.Context, judge: str, record: dict | None, problems: dict
) -> dict:
    return {
        "what": "independent",
        "passed": not problems,
        "problems": problems,
        "document_sha256": document_hash(record) if record else None,
        "judge_model": judge,
        "run_id": ctx.run_id,
    }


def save(root: Path, run_id: str, result: dict) -> dict:
    path = root / "workspace/runs" / run_id / "independent_verification.json"
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        saved = []
    result = dict(result, at=now())
    path.write_text(json.dumps(saved + [result], indent=1))
    return result


def main(argv: list | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("run_id")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    if not (ROOT / "workspace/runs" / args.run_id / "progress.json").is_file():
        sys.exit(f"no such run: {args.run_id}")
    try:
        with contextlib.redirect_stdout(sys.stderr):  # stdout carries only the result
            ctx = tools.Context(
                make_client(), ROOT, args.run_id, CaseRecord(ROOT, args.run_id), True
            )
            result = run_independent_verification(ctx, judge_model())
    except (MissingKeyError, RuntimeError, FileNotFoundError) as error:
        sys.exit(str(error))
    result = save(ROOT, args.run_id, result)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("INDEPENDENT " + ("passes" if result["passed"] else "fails"))
        print(f"  document: {result['document_sha256']}")
        print(f"  judge:    {result['judge_model']}")
        for check, items in (result["problems"] or {}).items():
            for problem in items:
                print(f"  {check}: {problem}")


if __name__ == "__main__":
    main()
