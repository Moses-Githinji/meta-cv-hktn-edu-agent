#!/usr/bin/env python3
"""Education Agent Console: a browser UI to start, watch, and review the teaching agent.

Standard library only. From the repository root:

    ./helper ui
    open http://127.0.0.1:8765

Use --root PATH only to point it at a different checkout, --port N to change
the port. It binds to your own computer only and has no login, so do not
expose it to a network.

The console never imports the agent. It READS:
  workspace/runs/<run>/progress.json             written by the progress layer every turn
  workspace/case_records/<run>.json              the run's record (checklist, facts,
                                                  requests, memo, reviews, figures)
  workspace/runs/<run>/audit.jsonl               the run's hash-chained event log
  workspace/runs/<run>/figures/<id>.svg|png      figures made for a run
  curriculum/*.json                               to show the source text beside each citation
  packs/<pack>/objective.md                       the assignments you can pick from
and ACTS only through the project's own commands:
  ./helper run | review | verify | describe | reset | export | send

See ui/README.md for the full data contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

CONSOLE = Path(__file__).resolve().parent
DEFAULT_ROOT = CONSOLE.parent  # ui/ sits at the root of the repository
MAX_TURNS = 200
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
EXPORT_WHAT = ("scheme", "exam", "marking-scheme", "lesson-plan")
EXPORT_FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# The tool and field names changed when the legal agent became a teaching agent. The console
# accepts both, so it keeps working while you rename things step by step.
CITE_TOOLS = {"cite_outcome", "record_fact"}
SUBMIT_TOOLS = {"submit_document", "submit_memo"}
ASK_TOOLS = {"ask_teacher", "request_evidence"}
READ_TOOLS = {"read_curriculum", "list_curriculum"}


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def read_progress(run_dir: Path) -> dict:
    return read_json(run_dir / "progress.json") or {}


def citations_of(record: dict) -> list:
    return record.get("citations") or record.get("facts") or []


def document_of(record: dict):
    return record.get("document") or record.get("memo")


def _parse(value: Any) -> dict:
    try:
        out = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return {"result": value}
    return out if isinstance(out, dict) else {"result": out}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(c.get("text", "")) for c in content if isinstance(c, dict)
        ).strip()
    return json.dumps(content)


def _saw(items: list) -> dict:
    """What the model saw on one turn, in a few lines."""
    counts: dict[str, int] = {}
    for item in items:
        kind = {
            "function_call_output": "tool results",
            "function_call": "earlier tool calls",
            "reasoning": "reasoning notes",
        }.get(item.get("type", ""))
        kind = kind or (
            "user messages" if item.get("role") == "user" else "model messages"
        )
        counts[kind] = counts.get(kind, 0) + 1
    last = items[-1] if items else {}
    return {
        "items": len(items),
        "counts": counts,
        "newest_observation": str(last.get("output", ""))[:900]
        if last.get("type") == "function_call_output"
        else "",
        "newest_message": _text(last.get("content"))[:600]
        if last.get("role") == "user"
        else "",
    }


def _epoch(stamp: str | None) -> float:
    try:
        return datetime.fromisoformat(stamp or "").timestamp()
    except ValueError:
        return 0.0


def _walk_outcomes(node: Any, ctx: dict):
    """Yield every {id, text} outcome in a curriculum pack, with its strand and sub-strand.

    Outcomes carry their wording in "text" or "outcome_text"; anything else on the
    outcome (source_ref, status, week_range) is passed through for the review card.
    """
    if isinstance(node, dict):
        c = dict(ctx)
        if "id" in node and "name" in node and "outcomes" in node:
            c["sub_strand"] = f'{node["id"]} {node["name"]}'
        elif "id" in node and "name" in node and "sub_strands" in node:
            c["strand"] = f'{node["id"]} {node["name"]}'
        text = node.get("text") or node.get("outcome_text")
        if (
            "id" in node
            and isinstance(text, str)
            and "outcomes" not in node
            and "sub_strands" not in node
        ):
            extra = {
                k: node[k]
                for k in ("source_ref", "status", "week_range")
                if k in node
            }
            yield {"id": str(node["id"]), "text": text, **extra, **c}
        for value in node.values():
            yield from _walk_outcomes(value, c)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_outcomes(value, ctx)


def build_events(  # noqa: C901
    progress: dict, record: dict | None, job: dict | None
) -> list:
    """The run as a list of events for the timeline, rebuilt from the saved conversation
    and the run's record."""
    events: list = []
    if not progress:
        return events
    messages = progress.get("messages") or []
    record = record or {}
    requests = {r.get("id"): r for r in record.get("requests") or []}
    escalations = {e.get("id"): e for e in record.get("escalations") or []}
    checks = list(record.get("checklist_checks") or [])

    def add(event_type: str, actor: str, stamp: Any, /, **payload: Any) -> None:
        events.append(
            {
                "event_type": event_type,
                "actor": actor,
                "timestamp": stamp,
                "payload": payload,
            }
        )

    def what_happened(n: int, stamp: Any, name: str, args: dict, result: dict) -> None:
        """Checks and escalations the run's record shows for this tool call."""
        if name == "set_checklist":
            draft = [
                str(i.get("id")) for i in args.get("items") or [] if isinstance(i, dict)
            ]
            check = next((c for c in checks if c.get("draft") == draft), None)
            if check is not None:
                checks.remove(check)
                add(
                    "verification",
                    "agent",
                    stamp,
                    turn=n,
                    check="checklist",
                    passed=bool(check.get("passed")),
                    score=check.get("score"),
                    feedback=check.get("feedback", ""),
                    accepted=bool(check.get("accepted")),
                    attempt=check.get("attempt"),
                )
        if name in SUBMIT_TOOLS and result.get("problems"):
            which = result.get("check", "document")
            if which == "claims":
                add("verification", "agent", stamp, turn=n, check="document", passed=True)
            add(
                "verification",
                "agent",
                stamp,
                turn=n,
                check=which,
                passed=False,
                problems=result["problems"],
            )
        if result.get("filed"):
            status = result.get("status")
            if status in ("awaiting_signoff", "awaiting_verification"):
                add("verification", "agent", stamp, turn=n, check="document", passed=True)
                add("verification", "agent", stamp, turn=n, check="claims", passed=True)
                add(
                    "escalation",
                    "agent",
                    stamp,
                    turn=n,
                    rule="teacher_signoff"
                    if status == "awaiting_signoff"
                    else "independent_check",
                    need="Teacher review of the filed document."
                    if status == "awaiting_signoff"
                    else "Independent check before teacher review.",
                )
        if result.get("escalated") or result.get("escalation"):
            ident = result.get("request") or result.get("escalation")
            found = requests.get(ident) or escalations.get(ident) or {}
            add(
                "escalation",
                "agent",
                stamp,
                turn=n,
                rule=found.get("rule") or found.get("reason_code") or result.get("reason_code", ""),
                item=result.get("item") or found.get("item"),
                need=result.get("need")
                or found.get("need")
                or found.get("what_is_needed"),
            )

    add(
        "run_started",
        "agent",
        progress.get("started"),
        verification=bool(progress.get("verification")),
    )
    status, last_time = "running", progress.get("started")
    for entry in progress.get("turns") or []:
        stamp = entry.get("time")
        if status != "running":
            add("run_started", "agent", stamp, resumed=True)
        n = entry.get("turn")
        if n is not None:
            saw, out, end = (
                entry.get("saw", 0),
                entry.get("output", 0),
                entry.get("end", 0),
            )
            add("model_request", "agent", stamp, turn=n, saw=_saw(messages[:saw]))
            add(
                "model_response",
                "model",
                stamp,
                turn=n,
                input_tokens=entry.get("input_tokens", 0),
                output_tokens=entry.get("output_tokens", 0),
                model=entry.get("model"),
            )
            call = next(
                (m for m in messages[saw:out] if m.get("type") == "function_call"),
                None,
            )
            if call is not None:
                name, args = call.get("name", ""), _parse(call.get("arguments") or "{}")
                add("tool_call", "agent", stamp, turn=n, tool_name=name, arguments=args)
                output = next(
                    (
                        m
                        for m in messages[out:end]
                        if m.get("type") == "function_call_output"
                        and m.get("call_id") == call.get("call_id")
                    ),
                    None,
                )
                if output is not None:
                    result = _parse(output.get("output"))
                    add(
                        "tool_result",
                        "tool",
                        stamp,
                        turn=n,
                        tool_name=name,
                        result=result,
                    )
                    what_happened(n, stamp, name, args, result)
            add("state_snapshot", "agent", stamp, turn=n, status=entry.get("status"))
        status, last_time = entry.get("status", "running"), stamp
        if status != "running":
            add("run_finished", "agent", stamp, status=status)
    if job and (status == "running" or job.get("started", 0) > _epoch(last_time)):
        stamp = datetime.now(timezone.utc).isoformat()
        if status != "running":
            add("run_started", "agent", stamp, resumed=True)
        add(
            "model_request",
            "agent",
            stamp,
            turn=int(progress.get("turn") or 0) + 1,
            pending=True,
        )
    return events


def run_state(progress: dict, events: list) -> dict:
    """What the side panels show: status, turn, the latest plan, the curriculum read."""
    plan: list = []
    read_ids: list = []
    args: dict = {}
    for e in events:
        p = e["payload"]
        if e["event_type"] == "tool_call":
            args = p.get("arguments") or {}
        elif e["event_type"] == "tool_result":
            result = p.get("result") or {}
            name = p.get("tool_name")
            if name == "update_plan" and isinstance(result.get("plan"), list):
                plan = result["plan"]
            if name in READ_TOOLS and "error" not in result:
                wanted = [
                    args.get(k)
                    for k in ("id", "sub_strand_id", "outcome_id", "subject")
                    if args.get(k)
                ] + list(args.get("ids") or [])
                read_ids += [str(i) for i in wanted if str(i) not in read_ids]
    return {
        **(progress.get("notes") or {}),
        "run_id": progress.get("run_id"),
        "verification": bool(progress.get("verification")),
        "model": progress.get("model"),
        "turn": progress.get("turn"),
        "status": progress.get("status"),
        "plan": plan,
        "read_ids": read_ids,
    }


def metrics(events: list, record: dict | None) -> dict:
    rec = record or {}
    m: dict[str, Any] = {
        "agent_turns": 0,
        "tool_calls": 0,
        "tokens": 0,
        "rejected": len(rec.get("rejected_citations") or rec.get("rejected_facts") or []),
        "escalations": 0,
    }
    for e in events:
        k, p = e.get("event_type"), e.get("payload") or {}
        if k == "model_request" and not p.get("pending"):
            m["agent_turns"] += 1
        elif k == "model_response":
            m["tokens"] += int(p.get("input_tokens") or 0) + int(
                p.get("output_tokens") or 0
            )
        elif k == "tool_call":
            m["tool_calls"] += 1
        elif k == "verification" and p.get("passed") is False:
            m["rejected"] += 1
        elif k == "escalation":
            m["escalations"] += 1
    return m


class Jobs:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items: list = []

    def start(
        self, kind: str, argv: list, cwd: Path, runs: Path, run_id: str = ""
    ) -> dict:
        before = {p.name for p in runs.glob("run-*")} if runs.exists() else set()
        process = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        job = {
            "id": len(self.items) + 1,
            "kind": kind,
            "argv": " ".join(argv),
            "run_id": run_id,
            "started": time.time(),
            "returncode": None,
            "log": "",
        }
        with self.lock:
            self.items.append(job)
        threading.Thread(target=self._pump, args=(job, process), daemon=True).start()
        if not run_id:
            threading.Thread(
                target=self._discover, args=(job, runs, before), daemon=True
            ).start()
        return job

    def _pump(self, job: dict, process) -> None:
        for line in process.stdout:
            with self.lock:
                job["log"] = (job["log"] + line)[-20000:]
        job["returncode"] = process.wait()

    def _discover(self, job: dict, runs: Path, before: set) -> None:
        while not job["run_id"]:
            fresh = (
                sorted(p.name for p in runs.glob("run-*") if p.name not in before)
                if runs.exists()
                else []
            )
            if fresh:
                job["run_id"] = fresh[-1]
                return
            if job["returncode"] is not None:
                return
            time.sleep(0.2)

    def snapshot(self) -> list:
        with self.lock:
            return [dict(j, running=j["returncode"] is None) for j in self.items]

    def active_for(self, run_id: str):
        return next(
            (
                j
                for j in reversed(self.snapshot())
                if j["run_id"] == run_id and j["running"]
            ),
            None,
        )

    def any_running(self) -> bool:
        return any(j["running"] for j in self.snapshot())


class Console:
    def __init__(self, root: Path | None) -> None:
        self.jobs = Jobs()
        self.root: Path | None = None
        if root:
            self.set_root(str(root))

    # ---- repository ----
    def set_root(self, path: str) -> dict:
        root = Path(path).expanduser().resolve()
        if (root / "agent/helper").is_file():
            root = root / "agent"  # old nested layout: the agent lives under agent/
        if not (root / "helper").is_file():
            raise RuntimeError(f"not the education agent repository (no ./helper): {root}")
        if self.jobs.any_running():
            raise RuntimeError("wait for the running agent to stop first")
        self.root = root
        return self.info()

    @property
    def agent(self) -> Path:
        if not self.root:
            raise RuntimeError("choose the repository folder first")
        return self.root

    @property
    def runs(self) -> Path:
        return self.agent / "workspace/runs"

    def _env(self) -> dict:
        env = {}
        path = self.agent / ".env"
        if path.is_file():
            for line in path.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
        return env

    def _task_key(self) -> str:
        env = self._env()
        for key in ("TEACHING_PACK_DIR", "TASK_DIR", "CASE_DIR"):
            if key in env:
                return key
        return "TEACHING_PACK_DIR"

    def task_dir(self) -> Path:
        """The pack the agent works on (TEACHING_PACK_DIR in .env, relative to the repo)."""
        env = self._env()
        value = env.get("TEACHING_PACK_DIR") or env.get("TASK_DIR") or env.get("CASE_DIR") or ""
        path = Path(value).expanduser() if value else self.agent / "packs"
        return path if path.is_absolute() else (self.agent / path).resolve()

    def _display_path(self, path: Path) -> str:
        if self.root is None:
            return str(path)
        try:
            return str(path.resolve().relative_to(self.root))
        except ValueError:
            return str(path)

    def _task_folders(self) -> list:
        if not self.root:
            return []
        folders = []
        for name in ("packs", "tasks"):
            folder = self.root / name
            if folder.is_dir():
                folders.append(folder)
        return folders

    def tasks(self) -> list:
        """Every pack folder with an objective.md, with its title."""
        out = []
        for folder in self._task_folders():
            for task in sorted(p for p in folder.iterdir() if p.is_dir()):
                objective = task / "objective.md"
                if not objective.is_file():
                    continue
                title = next(
                    (
                        line[2:].strip()
                        for line in objective.read_text(errors="replace").splitlines()
                        if line.startswith("# ")
                    ),
                    task.name,
                )
                out.append(
                    {
                        "id": f"{folder.name}/{task.name}",
                        "path": self._display_path(task),
                        "title": title,
                    }
                )
        return out

    def select_task(self, task_id: str) -> dict:
        """Point TEACHING_PACK_DIR in .env at the chosen pack (its curriculum follows)."""
        if self.jobs.any_running():
            raise RuntimeError("wait for the running agent to stop before switching tasks")
        match = next((t for t in self.tasks() if t["id"] == task_id), None)
        if match is None:
            raise FileNotFoundError(task_id)
        path = self.agent / ".env"
        lines = path.read_text().splitlines() if path.is_file() else []
        key = self._task_key()
        setting = f"{key}=./{match['id']}"
        for i, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == key:
                lines[i] = setting
                break
        else:
            lines.append(setting)
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n")
        tmp.replace(path)
        return self.info()

    def pack_info(self) -> dict:
        """The curriculum pack the agent reads: how many files, and a short version hash."""
        folder = self.agent / "curriculum" if self.root else None
        files = sorted(folder.glob("*.json")) if folder and folder.is_dir() else []
        files = [f for f in files if f.name != "schema.json"]
        digest = hashlib.sha256()
        for f in files:
            digest.update(f.name.encode())
            digest.update(f.read_bytes())
        return {
            "files": [f.name for f in files],
            "version": digest.hexdigest()[:12] if files else None,
        }

    def info(self) -> dict:
        if not self.root:
            return {"root": None, "jobs": []}
        env = self._env()
        return {
            "root": str(self.root),
            "task": self._display_path(self.task_dir()),
            "tasks": self.tasks(),
            "pack": self.pack_info(),
            "verification": env.get("VERIFICATION", "off").strip().lower()
            in ("on", "1", "true", "yes"),
            "api_key_configured": bool(env.get("MODEL_API_KEY")),
            "smtp_configured": bool(env.get("SMTP_HOST", "").strip())
            and bool(env.get("SMTP_FROM", "").strip()),
            "model": env.get("MODEL_API_MODEL", ""),
            "agent_ready": self._agent_ready(),
            "jobs": self.jobs.snapshot()[-10:],
            "control": self.control(),
        }

    def _agent_ready(self) -> bool:
        loops = sorted(self.agent.glob("*_agent/loop.py"))
        return bool(loops) and all("is not implemented yet" not in p.read_text() for p in loops)

    # ---- reads ----
    def list_runs(self) -> list:
        if not self.root or not self.runs.exists():
            return []
        rows = []
        for run_dir in sorted(self.runs.glob("run-*"), reverse=True):
            progress = read_progress(run_dir)
            rows.append(
                {
                    "id": run_dir.name,
                    "status": "running"
                    if self.jobs.active_for(run_dir.name)
                    else progress.get("status", "unknown"),
                    "verification": bool(progress.get("verification")),
                    "turn": progress.get("turn"),
                    "started": progress.get("started"),
                }
            )
        return rows

    def _record(self, run_id: str) -> dict | None:
        for folder in ("task_records", "case_records"):
            found = read_json(self.agent / "workspace" / folder / f"{run_id}.json")
            if found is not None:
                return found
        return None

    def run_detail(self, run_id: str) -> dict:
        run_dir = self._run_dir(run_id)
        progress = read_progress(run_dir)
        record = self._record(run_id)
        job = self.jobs.active_for(run_id)
        paused = bool(job) and bool(self.control().get("waiting"))  # step mode, between turns
        events = build_events(progress, record, None if paused else job)
        instructions = run_dir / "instructions.md"
        return {
            "verification": read_json(run_dir / "verification.json") or [],
            "error": (progress.get("notes") or {}).get("error")
            if progress.get("status") == "paused"
            else None,
            "id": run_id,
            "status": "running" if job else progress.get("status", "unknown"),
            "state": run_state(progress, events),
            "record": record,
            "events": events,
            "metrics": metrics(events, record),
            "instructions": instructions.read_text()[:400] if instructions.is_file() else "",
            "audit_available": self._audit_path(run_id) is not None,
            "job": job,
        }

    def _audit_path(self, run_id: str) -> Path | None:
        for path in (
            self.agent / "workspace/audit" / f"{run_id}.jsonl",
            self.runs / run_id / "audit.jsonl",
        ):
            if path.is_file():
                return path
        return None

    def audit(self, run_id: str, limit: int = 500) -> dict:
        self._run_dir(run_id)
        path = self._audit_path(run_id)
        if path is None:
            return {"events": [], "total": 0}
        lines = path.read_text(errors="replace").splitlines()
        events = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except ValueError:
                events.append({"unreadable_line": line[:200]})
        return {"events": events, "total": len(lines)}

    def outcome(self, outcome_id: str) -> dict:
        """The official text of an outcome, read straight from the curriculum pack."""
        folder = self.agent / "curriculum" if self.root else None
        if not folder or not folder.is_dir():
            raise FileNotFoundError("no curriculum folder")
        for path in sorted(folder.glob("*.json")):
            if path.name == "schema.json":
                continue
            data = read_json(path)
            ctx: dict = {}
            if isinstance(data, dict):
                for k in ("level", "subject"):
                    if k in data:
                        ctx[k] = data[k]
                pack = data.get("pack")
                if isinstance(pack, dict):
                    if pack.get("learning_area"):
                        ctx.setdefault("subject", pack["learning_area"])
                    if pack.get("grade"):
                        ctx.setdefault(
                            "level",
                            f"Grade {pack['grade']} {pack.get('curriculum', '')}".strip(),
                        )
            for found in _walk_outcomes(data, ctx):
                if found["id"] == outcome_id:
                    return {**found, "file": path.name}
        raise FileNotFoundError(outcome_id)

    def figure(self, run_id: str, fig_id: str) -> tuple[bytes, str]:
        self._run_dir(run_id)
        if not SAFE_NAME.match(fig_id):
            raise FileNotFoundError(fig_id)
        for suffix, kind in ((".svg", "image/svg+xml"), (".png", "image/png")):
            path = self.runs / run_id / "figures" / f"{fig_id}{suffix}"
            if path.is_file():
                return path.read_bytes(), kind
        raise FileNotFoundError(fig_id)

    def export_file(self, run_id: str, what: str, fmt: str) -> tuple[bytes, str, str]:
        """Build one export fresh via ./helper export and return (data, kind, filename).

        Always rebuilt from the record, so the viewer and downloads can never show a
        stale file. Nothing is kept: the command writes to a temp file that is removed.
        """
        self._run_dir(run_id)
        if what not in EXPORT_WHAT:
            raise RuntimeError(f"what must be one of {', '.join(EXPORT_WHAT)}")
        if fmt not in EXPORT_FORMATS:
            raise RuntimeError("format must be pdf or docx")
        tmp = tempfile.NamedTemporaryFile(prefix="console-export-", delete=False)
        tmp.close()
        try:
            out = subprocess.run(
                ["./helper", "export", run_id, "--what", what, "--format", fmt,
                 "--out", tmp.name],
                cwd=self.agent,
                capture_output=True,
                text=True,
            )
            if out.returncode:
                raise RuntimeError((out.stderr or out.stdout).strip()[-800:])
            return Path(tmp.name).read_bytes(), EXPORT_FORMATS[fmt], f"{run_id}-{what}.{fmt}"
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def send_document(
        self, run_id: str, what: str, fmt: str, to: str, subject: str, message: str
    ) -> dict:
        """Email one export via ./helper send (addresses are validated there)."""
        self._run_dir(run_id)
        if what not in EXPORT_WHAT:
            raise RuntimeError(f"what must be one of {', '.join(EXPORT_WHAT)}")
        if fmt not in EXPORT_FORMATS:
            raise RuntimeError("format must be pdf or docx")
        if not to.strip():
            raise RuntimeError("type at least one recipient address")
        out = subprocess.run(
            ["./helper", "send", run_id, "--what", what, "--format", fmt,
             "--to", to, "--subject", subject, "--message", message, "--json"],
            cwd=self.agent,
            capture_output=True,
            text=True,
        )
        if out.returncode:
            raise RuntimeError((out.stderr or out.stdout).strip()[-800:])
        return _json_result(out.stdout)

    def describe(self) -> dict:
        """The assignment text, plus the tools from ./helper describe (if it works)."""
        objective = self.task_dir() / "objective.md"
        out: dict[str, Any] = {
            "objective": objective.read_text(errors="replace")
            if objective.is_file()
            else "No objective.md in the selected task folder.",
            "tools": [],
            "tools_error": None,
        }
        try:
            run = subprocess.run(
                ["./helper", "describe"], cwd=self.agent, capture_output=True, text=True
            )
            if run.returncode:
                raise RuntimeError((run.stderr or run.stdout).strip()[-300:] or "describe failed")
            described = json.loads(run.stdout)
            out["tools"] = described.get("tools", [])
            if described.get("objective"):
                out["objective"] = described["objective"]
        except (RuntimeError, ValueError, OSError) as error:
            out["tools_error"] = str(error)
        return out

    # ---- step mode (workspace/control.json, read by the progress layer after each saved turn) ----
    def control(self) -> dict:
        return read_json(self.agent / "workspace/control.json") or {
            "step": False,
            "credits": 0,
            "waiting": False,
        }

    def set_control(self, change: dict) -> dict:
        control = self.control()
        if "step" in change:
            control["step"] = bool(change["step"])
            if not control["step"]:
                control["waiting"] = False
        if change.get("next"):
            control["credits"] = int(control.get("credits", 0)) + 1
        path = self.agent / "workspace/control.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(control))
        tmp.replace(path)
        return control

    # ---- actions ----
    def start_run(self, turns: int, step: bool = False) -> dict:
        if not self.jobs.any_running():
            self._reset_control(step)
        return self._launch("run", turns, "")

    def resume_run(self, run_id: str, turns: int, step: bool | None = None) -> dict:
        self._run_dir(run_id)
        if not self.jobs.any_running():
            self._reset_control(bool(step))
        return self._launch("resume", turns, run_id)

    def _reset_control(self, step: bool) -> None:
        """A new run starts with no saved 'Next turn' clicks: the first turn always runs."""
        self.set_control({"step": step})
        control = dict(self.control(), credits=0, waiting=False)
        path = self.agent / "workspace/control.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(control))
        tmp.replace(path)

    def _launch(self, kind: str, turns: int, run_id: str) -> dict:
        if self.jobs.any_running():
            raise RuntimeError("an agent run is already in progress")
        turns = max(1, min(int(turns), MAX_TURNS))
        argv = ["./helper", "run", "--turns", str(turns)]
        if run_id:
            argv += ["--resume", run_id]
        return self.jobs.start(kind, argv, self.agent, self.runs, run_id)

    def _cmd(self, argv: list, cwd: Path) -> dict:
        out = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
        if out.returncode:
            raise RuntimeError((out.stderr or out.stdout).strip()[-800:])
        return {"message": (out.stdout + out.stderr).strip()[-800:]}

    def review(
        self,
        run_id: str,
        decision: str,
        notes: str,
        request_id: str = "",
        acknowledged: list | None = None,
        item: str = "",
    ) -> dict:
        """Teacher decisions through ./helper review (document, item, answer, HoD).

        Items the teacher chose to keep although they are unverified are written into the
        notes, so the decision and the acknowledgement stay together in the record.
        """
        self._run_dir(run_id)
        if decision == "answer":
            argv = ["./helper", "review", run_id, "--answer", request_id]
        elif decision in ("hod-approve", "hod-reject"):
            argv = ["./helper", "review", run_id, f"--{decision}"]
        elif decision in ("approve", "reject", "edit"):
            argv = ["./helper", "review", run_id]
            if item:
                if not SAFE_NAME.match(item):
                    raise RuntimeError(f"unknown item: {item}")
                argv += ["--item", item]
            if decision == "edit":
                if not item:
                    raise RuntimeError("editing replaces one row: choose its item first")
                argv += ["--edit"]
            else:
                argv += ["--approve" if decision == "approve" else "--reject"]
        else:
            raise RuntimeError("decision must be approve, reject, edit, answer or hod-*")
        acks = [str(a) for a in (acknowledged or []) if SAFE_NAME.match(str(a))]
        if acks:
            notes = (notes + "\n" if notes else "") + "Acknowledged as unverified: " + ", ".join(acks)
        if notes:
            argv += ["--notes", notes]
        return self._cmd(argv, self.agent)

    def review_rows(self, run_id: str) -> dict:
        """One row per checklist item, from ./helper review RUN --list --json.

        This is the same reader the command line uses, so the review card can never
        disagree with it. An empty list means there is no checklist to review yet.
        """
        self._run_dir(run_id)
        out = subprocess.run(
            ["./helper", "review", run_id, "--list", "--json"],
            cwd=self.agent,
            capture_output=True,
            text=True,
        )
        if out.returncode:
            return {"rows": [], "error": (out.stderr or out.stdout).strip()[-300:]}
        try:
            rows = json.loads(out.stdout)
        except ValueError:
            return {"rows": [], "error": "unexpected output from ./helper review --list"}
        return {"rows": rows if isinstance(rows, list) else []}

    def verify(self, run_id: str, what: str) -> dict:
        """./helper verify RUN --memo | --checklist | --independent: checks on finished work."""
        self._run_dir(run_id)
        if what not in ("document", "checklist", "independent"):
            raise RuntimeError("verify the document, the checklist, or run the independent check")
        flag = {"document": "memo"}.get(what, what)
        out = subprocess.run(
            ["./helper", "verify", run_id, f"--{flag}", "--json"],
            cwd=self.agent,
            capture_output=True,
            text=True,
        )
        if out.returncode:
            raise RuntimeError((out.stderr or out.stdout).strip()[-800:])
        return _json_result(out.stdout)

    def reset(self, clear_runs: bool) -> dict:
        if self.jobs.any_running():
            raise RuntimeError("stop the running agent before resetting")
        return self._cmd(
            ["./helper", "reset"] + (["--clear-runs"] if clear_runs else []), self.agent
        )

    def _run_dir(self, run_id: str) -> Path:
        if "/" in run_id or ".." in run_id or not run_id.startswith("run-"):
            raise FileNotFoundError(run_id)
        run_dir = self.runs / run_id
        if not run_dir.is_dir():
            raise FileNotFoundError(run_id)
        return run_dir


def _json_result(stdout: str) -> dict:
    """The JSON object a ./helper command printed last (any progress lines before it are skipped)."""
    start = stdout.rfind("\n{")
    try:
        return json.loads(stdout[start + 1 :] if start >= 0 else stdout)
    except ValueError:
        raise RuntimeError(f"unexpected output: {stdout.strip()[-300:]}") from None


def make_handler(console: Console) -> type[BaseHTTPRequestHandler]:  # noqa: C901
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def _send(
            self, status: int, body: bytes, kind: str, filename: str = ""
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if filename:
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{filename}"'
                )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object, status: int = 200) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n)) if n else {}
            except ValueError:
                return {}

        def do_GET(self) -> None:
            url = urlparse(self.path)
            q = parse_qs(url.query)
            parts = [p for p in url.path.split("/") if p]
            try:
                if url.path in ("/", "/index.html"):
                    self._send(
                        200,
                        (CONSOLE / "index.html").read_bytes(),
                        "text/html; charset=utf-8",
                    )
                elif parts == ["api", "info"]:
                    self._json(console.info())
                elif parts == ["api", "runs"]:
                    self._json(console.list_runs())
                elif parts == ["api", "describe"]:
                    self._json(console.describe())
                elif parts == ["api", "outcome"]:
                    self._json(console.outcome(q.get("id", [""])[0]))
                elif parts == ["api", "figure"]:
                    body, kind = console.figure(q.get("run", [""])[0], q.get("id", [""])[0])
                    self._send(200, body, kind)
                elif parts == ["api", "export"]:
                    body, kind, name = console.export_file(
                        q.get("run", [""])[0], q.get("what", [""])[0], q.get("format", [""])[0]
                    )
                    self._send(200, body, kind, name if "download" in q else "")
                elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "audit":
                    self._json(console.audit(parts[2]))
                elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "review-rows":
                    self._json(console.review_rows(parts[2]))
                elif len(parts) == 3 and parts[:2] == ["api", "runs"]:
                    self._json(console.run_detail(parts[2]))
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except FileNotFoundError as error:
                self._json({"error": f"not found: {error}"}, HTTPStatus.NOT_FOUND)
            except RuntimeError as error:
                self._json({"error": str(error)}, HTTPStatus.CONFLICT)

        def do_POST(self) -> None:
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            b = self._body()
            try:
                if parts == ["api", "root"]:
                    self._json(console.set_root(b.get("path", "")))
                elif parts == ["api", "task"]:
                    self._json(console.select_task(str(b.get("task", ""))))
                elif parts == ["api", "runs"]:
                    self._json(console.start_run(b.get("turns", 30), bool(b.get("step"))))
                elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "resume":
                    self._json(console.resume_run(parts[2], b.get("turns", 15), b.get("step")))
                elif parts == ["api", "control"]:
                    self._json(console.set_control(b))
                elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "review":
                    self._json(
                        console.review(
                            parts[2],
                            b.get("decision", ""),
                            b.get("notes", ""),
                            b.get("request_id", ""),
                            b.get("acknowledged") or [],
                            b.get("item", ""),
                        )
                    )
                elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "verify":
                    self._json(console.verify(parts[2], str(b.get("what", ""))))
                elif len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "send":
                    self._json(
                        console.send_document(
                            parts[2],
                            str(b.get("what", "")),
                            str(b.get("format", "")),
                            str(b.get("to", "")),
                            str(b.get("subject", "")),
                            str(b.get("message", "")),
                        )
                    )
                elif parts == ["api", "reset"]:
                    self._json(console.reset(bool(b.get("clear_runs"))))
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except FileNotFoundError as error:
                self._json({"error": f"not found: {error}"}, HTTPStatus.NOT_FOUND)
            except RuntimeError as error:
                self._json({"error": str(error)}, HTTPStatus.CONFLICT)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Console for the Kenya teaching agent")
    parser.add_argument(
        "--root",
        "--workshop",
        dest="root",
        type=Path,
        default=None,
        help="a different repository folder (default: the one this ui/ folder is in)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    root = args.root
    if root is None and (
        (DEFAULT_ROOT / "helper").is_file() or (DEFAULT_ROOT / "agent/helper").is_file()
    ):
        root = DEFAULT_ROOT
    console = Console(root)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(console))
    print(
        f"Education Agent Console: http://{args.host}:{args.port}"
        + (f"  (repository: {console.root})" if console.root else "  (no repository yet)")
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
