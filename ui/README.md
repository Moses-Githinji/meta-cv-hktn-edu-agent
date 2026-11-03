# Education Agent Console

A local web page to start, watch and review the teaching agent.

Standard library only (Python 3.9+). Nothing to install.

## Run it

```text
./helper ui
```

Then open http://127.0.0.1:8765. Use `--root PATH` to point it at a different checkout and `--port N` to change the port. It binds to your own computer only and has no login, so do not expose it to a network.

## Try it on a demo repository

```text
python3 ui/make_demo.py demo_repo
python3 ui/ui.py --root demo_repo
```

This builds three sample runs (waiting for the teacher, waiting for review, approved), a stand-in `./helper`, and a **sample** curriculum pack. The sample wording is placeholder text, not official KICD wording.

## What you see

- **Task picker and pack badge:** the teaching pack the agent works on, and a short hash of the curriculum files it reads.
- **Timeline:** every turn as Plan, Act, Observe. Click a turn to see what the model saw and decided.
- **Teacher input card:** when the agent asks a question or escalates, type the answer and resume.
- **Teacher review card:** the finished document finding by finding. Every citation shows the official outcome text from the pack beside it, with a tick if the quoted words appear in it and a cross if they do not. Unverified rows are highlighted and need a tick from you before **Approve** unlocks. The ticks are written into the review notes.
- **Figures:** a finding with a `figure_id` shows the picture from the run's `figures/` folder.
- **Documents:** open each export kind in a viewer — read the PDF or download either format (scheme, exam, lesson plan; marking-scheme and email stay terminal-only). Everything is built fresh from the record, never from stale files.
- **Verify this run:** buttons for the document check, the checklist check and the independent check.
- **Side panels:** checklist, escalations (reason code, who it is routed to), plan, agent state, and an audit log viewer if the run has one.

## What it reads (the data contract)

The console never imports your agent. It reads files and calls `./helper`, so any agent that saves the same files will show up.

| File | What it holds |
|---|---|
| `.env` | `TEACHING_PACK_DIR` (or the old `TASK_DIR`/`CASE_DIR`), `MODEL_API_MODEL`, `VERIFICATION`, `MODEL_API_KEY` (only whether it is set is shown) |
| `workspace/runs/<run>/progress.json` | Saved every turn: `status`, `turn`, `messages`, `turns[]` (each with `saw`, `output`, `end`, token counts, `status`), `notes` |
| `workspace/case_records/<run>.json` | `checklist`, `facts`, `requests`, `memo`, `rejected_facts`, `checklist_checks` |
| `workspace/runs/<run>/verification.json` | List of results the `./helper verify` command saved |
| `workspace/runs/<run>/figures/<id>.svg` or `.png` | Figures for findings that name a `figure_id` |
| `workspace/runs/<run>/audit.jsonl` | Optional hash-chained event log, one JSON object per line |
| `curriculum/*.json` (except `schema.json`) | Outcomes with `{"id": ..., "outcome_text": ...}` at any nesting; strand names and levels are picked up from parent entries |
| `packs/<pack>/objective.md` | The assignment text; its first `# ` heading is the task title. The agent reads `curriculum/<pack>.json` for the chosen pack (unless `CURRICULUM_PACK` overrides it) |

Statuses it understands: `running`, `needs_input`, `awaiting_verification`, `awaiting_signoff`, `awaiting_hod`, `escalated`, `paused`, `answered`, `done`.

A document (filed under `memo`) is `{kind, status, conclusion, gaps, findings[]}`. Each finding is `{item, status, summary, citations[], figure_id?}`, and each citation is `{outcome_id, quote}`. Findings with status `unverified`, `escalated` or `not_proven`, or with an open escalation on the same `item`, count as unverified.

### Commands it calls

| Command | Used for |
|---|---|
| `./helper run --turns N [--resume RUN]` | Start and resume runs |
| `./helper review RUN --approve \| --reject \| --answer REQUEST [--notes TEXT]` | Teacher decisions (plus `--item`, `--edit`, `--hod-approve`/`--hod-reject` for the item and HoD flows) |
| `./helper review RUN --list --json` | One row per checklist item, with curriculum text (the same reader the command line uses) |
| `./helper verify RUN --memo \| --checklist \| --independent --json` | Checks (print a JSON object last) |
| `./helper export RUN --what WHAT --format FMT --out FILE` | Document viewer and downloads (built fresh each time) |
| `./helper describe` | JSON with `objective` and `tools[]` (`name`, `description`, `parameters`) |
| `./helper reset [--clear-runs]` | The Reset button |

Email (`./helper send`) and marking-scheme exports stay terminal-only: the
backend is unchanged, but the console no longer exposes them.

If a command does not exist yet, the console shows the command's error message. Nothing else breaks.

### Old and new names

While the legal fork is renamed step by step, the console accepts both: `cite_outcome` or `record_fact`, `submit_document` or `submit_memo`, `ask_teacher` or `request_evidence`, `citations` or `facts`, `document` or `memo`, `rows` or `findings`, and `task_records/` or `case_records/`.

## Limits

- Item-level approve/edit and head-of-department review run in the terminal for now (`./helper review RUN --item …`, `--hod-approve`/`--hod-reject`); the console shows their results but has no buttons for them yet.
- Approval acknowledgements are saved inside the review notes. A dedicated `--acknowledge` option on `./helper review` would store them as data.
- The page's stylesheet and helper functions come from the workshop console. Verified 3 Nov 2026: neither `meta-models/legal-agent-workshop` nor the intermediate fork ships a licence file. These derived parts are kept with attribution (see the repo README); confirm reuse terms with the hackathon organizers before redistributing beyond this entry.
