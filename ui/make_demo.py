#!/usr/bin/env python3
"""Build a small demo repository so you can try the console before running the agent.

    python3 ui/make_demo.py demo_repo
    python3 ui/ui.py --root demo_repo

It creates three sample runs (waiting for the teacher, waiting for review, approved), a
stand-in ./helper that supports describe, review, verify, export, send and reset, a
sample teaching pack, and a SAMPLE curriculum pack. The pack's wording is placeholder
text for trying the console. It is NOT official KICD wording. Replace it with outcomes
copied exactly from the official designs.
"""

from __future__ import annotations

import hashlib
import json
import stat
import sys
from pathlib import Path

PACK = {
    "pack": {
        "id": "grade7-mathematics-term2-sample",
        "learning_area": "Mathematics",
        "grade": 7,
        "curriculum": "CBC",
        "term": 2,
        "version": "0.0.0-sample",
    },
    "source": {
        "title": "SAMPLE ONLY: placeholder wording for trying the console. Not official KICD text.",
        "publisher": "demo",
    },
    "strands": [
        {
            "id": "NUM",
            "number": "1.0",
            "name": "Numbers",
            "sub_strands": [
                {
                    "id": "NUM.1",
                    "name": "Whole numbers",
                    "week_range": [1, 2],
                    "outcomes": [
                        {"id": "NUM.1.a", "outcome_text": "read and write whole numbers up to 1,000,000,000 in symbols and in words", "source_ref": "SAMPLE sub-strand NUM.1", "status": "transcribed"},
                        {"id": "NUM.1.b", "outcome_text": "work out the place value and total value of digits in whole numbers", "source_ref": "SAMPLE sub-strand NUM.1", "status": "transcribed"},
                    ],
                },
                {
                    "id": "NUM.2",
                    "name": "Fractions",
                    "week_range": [3, 4],
                    "outcomes": [
                        {"id": "NUM.2.a", "outcome_text": "add and subtract fractions with different denominators in everyday situations", "source_ref": "SAMPLE sub-strand NUM.2", "status": "transcribed"},
                    ],
                },
            ],
        },
        {
            "id": "DAT",
            "number": "2.0",
            "name": "Data handling",
            "sub_strands": [
                {
                    "id": "DAT.1",
                    "name": "Graphs",
                    "week_range": [5, 5],
                    "outcomes": [
                        {"id": "DAT.1.a", "outcome_text": "draw and interpret bar graphs using a suitable scale", "source_ref": "SAMPLE sub-strand DAT.1", "status": "transcribed"},
                    ],
                }
            ],
        },
    ],
}

OBJECTIVE = """# Grade 7 Mathematics · Term 2 scheme of work (demo)

Prepare the Term 2 scheme of work for Grade 7 Mathematics: **5 lessons per week, 40 minutes each**.

- Use only outcomes from the curriculum pack, and cite each one with its exact words.
- Cover every required sub-strand for the term.
- If you do not know something the curriculum pack and the teacher's files cannot tell you, ask the teacher.

**Sample task:** this is demo text for the console, not a real assignment.
"""

TOOLS = [
    {"name": "list_curriculum", "description": "List strands and sub-strands in the curriculum pack.", "parameters": []},
    {"name": "read_curriculum", "description": "Read one outcome from the curriculum pack.", "parameters": ["outcome_id"]},
    {"name": "set_checklist", "description": "Record what the document must cover.", "parameters": ["items"]},
    {"name": "cite_outcome", "description": "Cite an outcome with its exact words. Refused if the words are not in the outcome.", "parameters": ["item", "outcome_id", "quote", "claim"]},
    {"name": "ask_teacher", "description": "Pause and ask the teacher for missing information.", "parameters": ["item", "question"]},
    {"name": "escalate", "description": "Flag an item you cannot verify, with the reason code.", "parameters": ["item", "reason_code", "need"]},
    {"name": "submit_document", "description": "File the finished document for checking.", "parameters": ["conclusion", "findings", "gaps", "kind"]},
    {"name": "update_plan", "description": "Record the next steps.", "parameters": ["plan"]},
]

HELPER = r'''#!/usr/bin/env python3
"""Stand-in for ./helper in the demo repository (describe, review, verify, export, send, reset)."""
import json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WS = ROOT / "workspace"
PACK = ROOT / "curriculum"
args = sys.argv[1:]
cmd = args[0] if args else ""


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def load(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2))


def norm(s):
    return re.sub(r"\s+", " ", str(s).lower().replace("\u2018", "'").replace("\u2019", "'")).strip()


def outcomes():
    found = {}
    def walk(n, ctx=None):
        ctx = dict(ctx or {})
        if isinstance(n, dict):
            if "id" in n and "name" in n and "sub_strands" in n:
                ctx["strand"] = f"{n['id']} {n['name']}"
            if "id" in n and "name" in n and "outcomes" in n:
                ctx["sub_strand"] = str(n["name"])
            text = n.get("text") or n.get("outcome_text")
            if "id" in n and isinstance(text, str) and "outcomes" not in n and "sub_strands" not in n:
                found[str(n["id"])] = {"outcome_text": text, "status": n.get("status", "transcribed"), **ctx}
            for v in n.values():
                walk(v, ctx)
        elif isinstance(n, list):
            for v in n:
                walk(v, ctx)
    for f in sorted(PACK.glob("*.json")):
        if f.name != "schema.json":
            walk(load(f))
    return found


def review_rows(rec):
    known = outcomes()
    memo = rec.get("memo") or {}
    findings = {f["item"]: f for f in memo.get("findings") or [] if isinstance(f, dict) and f.get("item")}
    rows = []
    for item, entry in (rec.get("checklist") or {}).items():
        finding = findings.get(item)
        oids = []
        for c in (finding or {}).get("citations") or []:
            oid = (c or {}).get("outcome_id")
            if oid and oid not in oids:
                oids.append(oid)
        rows.append({
            "item": item,
            "status": entry.get("status"),
            "question": entry.get("question"),
            "finding": finding,
            "review": (memo.get("item_reviews") or {}).get(item),
            "curriculum": [{"outcome_id": o, **known.get(o, {"outcome_text": None, "status": "missing"})} for o in oids],
        })
    return rows


if cmd == "describe":
    objective = (ROOT / "packs" / "grade7-maths-term2" / "objective.md").read_text()
    print(json.dumps({"objective": objective, "tools": json.loads(%(TOOLS)r)}))
elif cmd == "review":
    run = args[1]
    rec_path = WS / "case_records" / f"{run}.json"
    prog_path = WS / "runs" / run / "progress.json"
    rec, prog = load(rec_path), load(prog_path)
    notes = opt("--notes", "")
    memo = rec.get("memo") or {}
    if "--list" in args:
        print(json.dumps(review_rows(rec), indent=2))
    elif opt("--item"):
        item = opt("--item")
        decision = "edited" if "--edit" in args else ("approved" if "--approve" in args else ("rejected" if "--reject" in args else None))
        if decision is None:
            sys.exit("--item needs exactly one of --approve, --reject, --edit")
        memo.setdefault("item_reviews", {})[item] = {"decision": decision, "notes": notes}
        if decision == "edited":
            for f in memo.get("findings") or []:
                if isinstance(f, dict) and f.get("item") == item:
                    f["summary"] = notes or f.get("summary")
        rec["memo"] = memo
        print(json.dumps({"item": item, "decision": decision}))
    elif "--hod-approve" in args or "--hod-reject" in args:
        approved = "--hod-approve" in args
        if not approved and not notes:
            sys.exit("--hod-reject needs --notes saying what to fix")
        memo["hod_review"] = {"decision": "approved" if approved else "rejected", "notes": notes}
        memo["status"] = "approved" if approved else "rejected"
        prog["status"] = "done" if approved else "paused"
        print(json.dumps({"kind": "exam", "status": memo["status"]}))
    elif "--approve" in args:
        memo["status"] = "awaiting_hod" if memo.get("kind") == "exam" else "approved"
        memo["review"] = {"notes": notes}
        prog["status"] = "awaiting_hod" if memo.get("kind") == "exam" else "done"
        print(f"{run}: approved" + ("; now the head of department must review (exam)" if memo["status"] == "awaiting_hod" else ""))
    elif "--reject" in args:
        if not notes:
            sys.exit("--reject needs --notes saying what to fix")
        memo["status"] = "rejected"; memo["review"] = {"notes": notes}; prog["status"] = "paused"
        print(f"{run}: rejected, notes saved for the agent")
    elif "--answer" in args:
        rid = opt("--answer")
        for r in rec.get("requests", []):
            if r["id"] == rid:
                r["status"] = "answered"; r["response"] = notes or "Answered by reviewer."
        prog["status"] = "answered"
        print(f"{run}: answer recorded for {rid}")
    else:
        sys.exit("choose what to review (see --help)")
    save(rec_path, rec); save(prog_path, prog)
elif cmd == "verify":
    run = args[1]
    rec = load(WS / "case_records" / f"{run}.json")
    flag = next((a for a in args if a in ("--memo", "--document", "--checklist", "--independent")), "--memo")
    what = {"--memo": "memo", "--document": "memo"}.get(flag, flag[2:])
    result = {"what": what, "time": time.strftime("%%H:%%M:%%S")}
    if what == "checklist":
        ck = rec.get("checklist", {})
        done = sum(1 for e in ck.values() if e.get("status") == "proven")
        result.update(passed=bool(ck) and done == len(ck), score=(done / len(ck)) if ck else 0, feedback="" if ck and done == len(ck) else "Some items are not settled yet.")
    else:
        known, problems, unverified = outcomes(), [], []
        memo = rec.get("memo") or {}
        for row in memo.get("findings", []):
            if row.get("status") in ("unverified", "escalated"):
                unverified.append(f"{row['item']}: marked {row.get('status')}")
            for c in row.get("citations", []):
                text = (known.get(c.get("outcome_id")) or {}).get("outcome_text")
                if text is None:
                    problems.append(f"{row['item']}: outcome {c.get('outcome_id')} is not in the curriculum pack")
                elif norm(c.get("quote", "")) not in norm(text):
                    problems.append(f"{row['item']}: the quoted words are not in {c['outcome_id']}")
        result.update(passed=not problems and (what != "independent" or not unverified), problems=problems, unverified=unverified if what == "independent" else [])
    vpath = WS / "runs" / run / "verification.json"
    history = load(vpath) if vpath.exists() else []
    history.append(result); save(vpath, history)
    print("checked")
    print(json.dumps(result))
elif cmd == "export":
    run = args[1]
    rec = load(WS / "case_records" / f"{run}.json")
    if not rec.get("memo"):
        sys.exit(f"export failed: {run} has no filed document to export")
    what, fmt = opt("--what", "scheme"), opt("--format", "pdf")
    if fmt == "pdf":
        data = (b"%%PDF-1.4\n%% demo\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
                b"trailer<</Root 1 0 R>>\n%%EOF")
    else:
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
            z.writestr("word/document.xml", f"<doc>Demo {what}</doc>")
        data = buf.getvalue()
    out = opt("--out", "") or f"demo-{what}.{fmt}"
    Path(out).write_bytes(data)
    print(f"{what} -> {out} ({len(data)} bytes)")
elif cmd == "send":
    run = args[1]
    rec = load(WS / "case_records" / f"{run}.json")
    if not rec.get("memo"):
        sys.exit(f"send failed: {run} has no filed document to export")
    what, fmt = opt("--what"), opt("--format")
    if what not in ("scheme", "exam", "marking-scheme", "lesson-plan"):
        sys.exit("send failed: bad document kind")
    tos = [a.strip() for a in opt("--to", "").split(",") if a.strip()]
    if not tos or any("@" not in a for a in tos):
        sys.exit("send failed: not an email address")
    result = {"run_id": run, "what": what, "format": fmt, "to": tos,
              "subject": opt("--subject", f"Demo {what}"),
              "file": f"{run}-{what}.{fmt}", "bytes": 1234,
              "dry_run": "--dry-run" in args}
    print(json.dumps(result, indent=2) if "--json" in args else f"sent {result['file']} to {', '.join(tos)}")
elif cmd == "reset":
    print("workspace reset (demo: nothing to clear)")
elif cmd == "run":
    sys.exit("This demo repository has no agent to run. Point the console at the real repository instead.")
else:
    sys.exit(f"unknown command: {cmd}")
'''

FIGURE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 120" width="220" height="120">'
    '<rect width="220" height="120" fill="#fff"/><line x1="30" y1="100" x2="210" y2="100" stroke="#000"/><line x1="30" y1="10" x2="30" y2="100" stroke="#000"/>'
    '<rect x="45" y="50" width="25" height="50" fill="#888"/><rect x="90" y="30" width="25" height="70" fill="#888"/><rect x="135" y="65" width="25" height="35" fill="#888"/>'
    '<text x="52" y="114" font-size="9" text-anchor="middle">Mon</text><text x="102" y="114" font-size="9" text-anchor="middle">Tue</text><text x="147" y="114" font-size="9" text-anchor="middle">Wed</text>'
    '<text x="24" y="14" font-size="8" text-anchor="end">Pupils</text></svg>'
)


class Run:
    """Builds a progress.json the way the progress layer saves it: messages plus one entry per turn."""

    def __init__(self, run_id: str, task_text: str) -> None:
        self.run_id = run_id
        self.messages: list = [{"role": "user", "content": task_text}]
        self.turns: list = []
        self.n = 0

    def turn(self, name: str, args: dict, result: dict, status: str = "running", tokens=(1800, 220)) -> None:
        self.n += 1
        saw = len(self.messages)
        call_id = f"call_{self.n}"
        self.messages.append({"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(args)})
        out = len(self.messages)
        self.messages.append({"type": "function_call_output", "call_id": call_id, "output": json.dumps(result)})
        end = len(self.messages)
        self.turns.append(
            {
                "turn": self.n, "time": f"2026-11-02T09:{self.n:02d}:00+00:00", "saw": saw, "output": out, "end": end,
                "input_tokens": tokens[0] + 300 * self.n, "output_tokens": tokens[1], "status": status, "model": "demo-model",
            }
        )

    def save(self, folder: Path, status: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "progress.json").write_text(
            json.dumps(
                {
                    "run_id": self.run_id, "status": status, "turn": self.n, "verification": True, "model": "demo-model",
                    "started": "2026-11-02T09:00:00+00:00", "messages": self.messages, "turns": self.turns, "notes": {},
                },
                indent=2,
            )
        )


def checklist(settled: list[str], escalated: list[str] = ()) -> dict:
    items = {
        "number_sense": "Whole numbers: place value and reading numbers",
        "fractions": "Fractions: adding and subtracting",
        "data_graphs": "Data handling: bar graphs",
        "angles": "Geometry: angles",
    }
    return {
        k: {"question": v, "status": "proven" if k in settled else ("escalated" if k in escalated else "open")}
        for k, v in items.items()
    }


def _chained(events: list[dict]) -> list[dict]:
    """Give demo audit events a valid hash chain, like edu_kit/audit.py does."""
    prev = "genesis"
    out = []
    for n, event in enumerate(events, start=1):
        entry = {"seq": n, "at": f"2026-11-02T09:{n:02d}:00+00:00", "prev": prev, **event}
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        entry["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
        prev = entry["hash"]
        out.append(entry)
    return out


def build(root: Path) -> None:
    (root / "workspace/runs").mkdir(parents=True, exist_ok=True)
    (root / "workspace/case_records").mkdir(parents=True, exist_ok=True)
    (root / "curriculum").mkdir(exist_ok=True)
    (root / "packs/grade7-maths-term2").mkdir(parents=True, exist_ok=True)
    (root / "curriculum/grade7_mathematics.sample.json").write_text(json.dumps(PACK, indent=2))
    (root / "packs/grade7-maths-term2/objective.md").write_text(OBJECTIVE)
    (root / ".env").write_text("MODEL_API_MODEL=demo-model\nTEACHING_PACK_DIR=./packs/grade7-maths-term2\nVERIFICATION=on\n")
    helper = root / "helper"
    helper.write_text(HELPER % {"TOOLS": json.dumps(TOOLS)})
    helper.chmod(helper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (root / "teaching_agent").mkdir(exist_ok=True)
    (root / "teaching_agent/loop.py").write_text("# demo placeholder: the real loop goes here\n")

    runs = root / "workspace/runs"
    records = root / "workspace/case_records"
    task = OBJECTIVE
    cite = lambda oid, quote: {"outcome_id": oid, "quote": quote}
    num1 = PACK["strands"][0]["sub_strands"][0]["outcomes"]

    # Run 1: waiting for the teacher
    r1 = Run("run-demo-1-needs-input", task)
    r1.turn("list_curriculum", {}, {"strands": [{"id": "NUM"}, {"id": "DAT"}]})
    r1.turn("read_curriculum", {"outcome_id": "NUM.1.a"}, {"outcomes": num1})
    r1.turn("set_checklist", {"items": [{"id": k} for k in checklist([])]}, {"checklist": checklist([])})
    r1.turn("ask_teacher", {"item": "number_sense", "question": "Which weeks of Term 2 are exam weeks?"},
            {"escalated": True, "request": "R1", "item": "number_sense", "need": "Which weeks of Term 2 are exam weeks?", "status": "needs_input"},
            status="needs_input")
    r1.save(runs / "run-demo-1-needs-input", "needs_input")
    (records / "run-demo-1-needs-input.json").write_text(json.dumps({
        "checklist": checklist([]),
        "checklist_checks": [{"draft": list(checklist([])), "passed": True, "score": 1.0, "feedback": "", "attempt": 1, "accepted": True}],
        "facts": [],
        "requests": [{"id": "R1", "item": "number_sense", "status": "open", "rule": "teacher_input", "need": "Which weeks of Term 2 are exam weeks?"}],
    }, indent=2))

    # Run 2: waiting for teacher review, with an unverified row, a mismatched quote and a figure
    r2 = Run("run-demo-2-awaiting-review", task)
    r2.turn("list_curriculum", {}, {"strands": [{"id": "NUM"}, {"id": "DAT"}]})
    r2.turn("read_curriculum", {"outcome_id": "NUM.1.a"}, {"outcomes": num1})
    r2.turn("set_checklist", {"items": [{"id": k} for k in checklist([])]}, {"checklist": checklist([])})
    r2.turn("cite_outcome", {"item": "number_sense", "outcome_id": "NUM.1.a", "quote": "read and write whole numbers up to 1,000,000,000", "claim": "Weeks 1-2 cover reading large numbers"},
            {"recorded": {"id": "F1", "item": "number_sense"}})
    r2.turn("cite_outcome", {"item": "fractions", "outcome_id": "NUM.2.a", "quote": "add and subtract fractions with different denominators", "claim": "Weeks 3-4 cover fractions"},
            {"recorded": {"id": "F2", "item": "fractions"}})
    r2.turn("cite_outcome", {"item": "data_graphs", "outcome_id": "DAT.1.a", "quote": "draw bar graphs on a logarithmic scale", "claim": "Week 5 covers graphs"},
            {"error": "The quoted words are not in outcome DAT.1.a. Quote it exactly."})
    r2.turn("escalate", {"item": "angles", "reason_code": "missing_outcome_text", "need": "No angles outcome is transcribed in the pack yet."},
            {"escalated": True, "request": "R1", "item": "angles", "reason_code": "missing_outcome_text", "need": "No angles outcome is transcribed in the pack yet.", "status": "escalated"})
    r2.turn("submit_document", {"conclusion": "Weeks 1 to 5 of 10 drafted; the angles week is left open.", "kind": "scheme"},
            {"filed": True, "document": "awaiting_signoff", "status": "awaiting_signoff"}, status="awaiting_signoff")
    r2.save(runs / "run-demo-2-awaiting-review", "awaiting_signoff")
    fig = runs / "run-demo-2-awaiting-review/figures"
    fig.mkdir(exist_ok=True)
    (fig / "fig-1.svg").write_text(FIGURE_SVG)
    (runs / "run-demo-2-awaiting-review/audit.jsonl").write_text("\n".join(
        json.dumps(e)
        for e in _chained([
            {"actor": "agent", "event": "run_started", "detail": {"verification": True}},
            {"actor": "agent", "event": "tool_call", "detail": {"tool": "cite_outcome", "item": "number_sense"}},
            {"actor": "agent", "event": "tool_call", "detail": {"tool": "escalate", "item": "angles"}},
            {"actor": "agent", "event": "run_stopped", "detail": {"status": "awaiting_signoff"}},
        ])
    ) + "\n")
    (records / "run-demo-2-awaiting-review.json").write_text(json.dumps({
        "checklist": checklist(["number_sense", "fractions"], ["angles"]),
        "checklist_checks": [{"draft": list(checklist([])), "passed": True, "score": 1.0, "feedback": "", "attempt": 1, "accepted": True}],
        "facts": [
            {"id": "F1", "item": "number_sense", "outcome_id": "NUM.1.a", "quote": "read and write whole numbers up to 1,000,000,000"},
            {"id": "F2", "item": "fractions", "outcome_id": "NUM.2.a", "quote": "add and subtract fractions with different denominators"},
        ],
        "rejected_facts": [{"item": "data_graphs", "outcome_id": "DAT.1.a"}],
        "requests": [{"id": "R1", "item": "angles", "status": "answered", "rule": "missing_outcome_text", "need": "No angles outcome is transcribed in the pack yet.", "response": "Leave angles as a gap; the pack update is coming."}],
        "memo": {
            "kind": "scheme", "status": "awaiting_signoff",
            "conclusion": "Weeks 1 to 5 of 10 drafted; the angles week is left open.",
            "gaps": ["Angles: no outcome in the pack yet."],
            "findings": [
                {"item": "number_sense", "status": "verified", "summary": "Weeks 1 to 2: reading and writing large whole numbers; place value games.", "citations": [cite("NUM.1.a", "read and write whole numbers up to 1,000,000,000")]},
                {"item": "fractions", "status": "verified", "summary": "Weeks 3 to 4: adding and subtracting fractions using fraction strips.", "citations": [cite("NUM.2.a", "add and subtract fractions with different denominators")]},
                {"item": "data_graphs", "status": "verified", "summary": "Week 5: drawing and reading bar graphs from class data.", "figure_id": "fig-1", "figure_alt": "Bar graph of pupils present on Monday, Tuesday and Wednesday", "citations": [cite("DAT.1.a", "draw bar graphs on a logarithmic scale")]},
                {"item": "angles", "status": "unverified", "summary": "Week 6: angles (placeholder, no outcome found).", "citations": []},
            ],
        },
    }, indent=2))

    # Run 3: approved
    r3 = Run("run-demo-3-approved", task)
    r3.turn("list_curriculum", {}, {"strands": [{"id": "NUM"}]})
    r3.turn("cite_outcome", {"item": "number_sense", "outcome_id": "NUM.1.b", "quote": "place value and total value of digits", "claim": "Place value is covered"},
            {"recorded": {"id": "F1", "item": "number_sense"}})
    r3.turn("submit_document", {"conclusion": "Whole numbers mini-scheme.", "kind": "scheme"},
            {"filed": True, "document": "awaiting_signoff", "status": "awaiting_signoff"}, status="awaiting_signoff")
    r3.turn("update_plan", {"plan": ["Read pack", "Cite", "File"]}, {"plan": ["Read pack", "Cite", "File"]}, status="done")
    r3.save(runs / "run-demo-3-approved", "done")
    (runs / "run-demo-3-approved/verification.json").write_text(json.dumps([
        {"what": "checklist", "passed": True, "score": 1.0, "feedback": ""},
        {"what": "memo", "passed": True, "problems": []},
    ], indent=2))
    (records / "run-demo-3-approved.json").write_text(json.dumps({
        "checklist": {"number_sense": {"question": "Whole numbers", "status": "proven"}},
        "facts": [{"id": "F1", "item": "number_sense", "outcome_id": "NUM.1.b", "quote": "place value and total value of digits"}],
        "requests": [],
        "memo": {"kind": "scheme", "status": "approved", "review": {"notes": "Looks right."},
                 "conclusion": "Whole numbers mini-scheme.",
                 "findings": [{"item": "number_sense", "status": "verified", "summary": "Place value activities.", "citations": [cite("NUM.1.b", "place value and total value of digits")]}]},
    }, indent=2))


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_repo").resolve()
    build(target)
    print(f"Demo repository created at {target}\nTry it:  python3 ui/ui.py --root {target}")


if __name__ == "__main__":
    main()
