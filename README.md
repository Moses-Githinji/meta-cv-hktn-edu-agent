# Teaching Agent (CBC, Kenya)

A teaching agent for the Kenyan Competency-Based Curriculum — all levels
(Pre-Primary, Primary, Junior School, Senior School) and all learning
areas — forked from the
[legal-agent workshop](https://github.com/Moses-Githinji/legal-agent-workshop.git).
It plans term coverage from hand-built curriculum packs, quotes learning
outcomes exactly as printed in the official KICD designs, and files
documents (schemes of work, lesson plans, exams) for teacher sign-off.

Project scope is CBC-wide, one term per run. `docs/01-scope-and-permissions.md`
locks the Phase 1 slice: Grade 7, Term 1. Outcome text is copied exactly
from the official designs. The six Grade 7 Term 1 packs shipped here are
the current coverage, not the limit: new packs plug into the same schema,
pipeline, and console.

## Quick start

```bash
cp .env.example .env      # add MODEL_API_KEY; TEACHING_PACK_DIR names the pack
./helper setup            # creates .venv (OpenAI Python SDK), checks the key
```

The agent talks to the Meta Model API with the official OpenAI Python SDK
(`base_url=https://api.meta.ai/v1`). `./helper` runs everything with
`.venv/bin/python`.

To reproduce the project end to end on your own machine, follow
[REPRODUCE.md](REPRODUCE.md).

## Commands

```bash
./helper setup                         # set up env and seed the pack inbox
./helper test [--verification]         # offline tests; never call the live API
./helper run --turns 30                # run the agent
./helper run --resume RUN_ID --turns 15
./helper review RUN_ID --list          # one row per item, with curriculum text
./helper review RUN_ID --item ITEM --approve | --reject --notes "..." | --edit --notes "..."
./helper review RUN_ID --approve | --reject --notes "..." | --hod-approve
./helper verify RUN_ID --memo | --checklist | --independent
./helper branch RUN_ID
./helper pipeline fetch|extract|gates|diff|publish|rollback|staleness|refresh|schedule|propose-dates|alerts
./helper export RUN --what scheme|exam|marking-scheme|lesson-plan --format docx|pdf [--out FILE]
./helper send RUN --what WHAT --format docx|pdf --to ADDR [--subject S] [--message M] [--dry-run]
./helper eval [--task ID] [--live] [--shadow JUDGE]
./helper dashboard [--json] [--html FILE] [--alerts]
./helper retention [--days N] [--apply]
./helper ui [--port N]                   # browser console: start, watch, review runs
./helper reset [--clear-runs]
```

## Repository map

- `teaching_agent/` — the agent: the agentic loop (`loop.py`) and
  `system_instructions.md` (sent as its system prompt every turn).
- `edu_kit/` — pre-built plumbing (do not edit): tools, run progress, record
  system, document text, API client, settings.
- `verification/` — the verification layer: teaching checks
  (`verify_teaching_checklist.py`, `verify_scheme.py`, fail-closed
  `verify_claims.py`); legal originals kept beside them and in
  `docs/legal-reference/`.
- `pipeline/` — the curriculum data pipeline (fetch, extract, gates,
  publish, refresh; see `PIPELINE.md`). Local data in `var/` (gitignored).
- `lessons/`, `exams/`, `diagrams/`, `export/` — follow-up documents:
  lesson plans, exams, figures, Word/PDF export (see `DOCUMENTS.md`).
- `evals/`, `routing/` — golden tasks and model routing (see `OPERATE.md`).
- `curriculum/` — schema, loader, and the current curriculum packs.
- `teacher_context/` — term calendar and timetable for one real term.
- `packs/grade7-*/` — the six Grade 7 Term 1 subject packs shipped so far
  (`objective.md` + `documents/`); switch with the console's Task picker.
  Further CBC levels and subjects follow the same layout.
- `ui/` — the browser console (stdlib only; see `ui/README.md`).
- `docs/` — scope, KICD permission draft, ground-rules prompt, legal reference.

## Fork notes (Phase 1C)

Renamed: `agent_kit/` → `edu_kit/`, `legal_agent/` → `teaching_agent/`,
`CASE_DIR` → `TEACHING_PACK_DIR`. Removed: `cases/`, `ground_truth/`,
`world/`, `solutions/`, `ui/` (legal content; not copied — the current
`ui/` is a new teaching console, not the legal one).
Legal originals kept for provenance in `docs/legal-reference/`.

Teaching tools live alongside the kit tools in `edu_kit/tools/`:
`list_curriculum`, `read_curriculum`, `cite_outcome`, `ask_teacher`,
`submit_document` (plus teaching-worded `set_checklist` and `update_plan`).

Planned later-phase renames (kept stable now to avoid breaking the kit):
`case_record.py` → `teaching_record.py`, `scripts/reset_case.py` →
`scripts/reset_pack.py`, and retirement of the legal tools once teaching
verification exists.
