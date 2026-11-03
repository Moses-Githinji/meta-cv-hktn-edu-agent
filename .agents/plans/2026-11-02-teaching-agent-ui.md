## Goal

A simple read-only browser UI for the teaching agent so you can watch what the models are processing and outputting: live run transcripts (turns, tool calls, results), case-record state (checklist, facts, requests, memo, reviews), the audit trail, and rendered figures — all from data the system already writes.

## Success Criteria

- One command starts it; opening the printed localhost URL shows the run list.
- During a live `./helper run`, new turns (model text, tool calls, tool results, token usage) appear in the run view without restart.
- A run view also shows record state, audit events, and figure images (SVG/PNG).
- The UI cannot change anything: every endpoint is a GET over existing readers; no keys or `.env` content is ever served.
- `./helper test` stays green; new endpoint tests run offline on fixture workspaces.

## Approach

Tiny local server plus one polling page, stdlib-only, reusing existing readers — no new dependencies, matching how this repo already builds everything (loader, pipeline, export are all stdlib).

- **Server**: new `ui/server.py` on Python's standard HTTP server, bound to `127.0.0.1` only, GET routes only. JSON endpoints read `workspace/` through the same functions the CLI uses: run list + `progress.json` transcript/usage, `CaseRecord` state, `audit.read`, `scripts/review.item_rows` for per-item rows, figure bytes from the run's `figures/` dir, and `scripts/describe.py`'s JSON for the header/config panel.
- **Page**: one static `ui/index.html` (vanilla JS, 2s polling, no build step), styled plainly per the repo's UI constraints (system fonts, tables, no decoration-as-identity).
- **Wiring**: `./helper ui [--port 8613]` serving both; documented in `OPERATE.md` + README line.

**Key decisions**

1. *Local server over static-file regeneration.* You want to see what is being processed *during* a run; a regenerating HTML file is always stale mid-run, while polling a server is live. Your WSL setup already forwards ports to the browser (that's what prompted you before), so `http://127.0.0.1:8613` will just open.
2. *Read-only viewer, no review actions in v1.* The request is to *see* processing and output; `./helper review` already handles approvals well. This keeps v1 small and eliminates any risk of the UI corrupting a run. Browser review actions become an explicit follow-up.
3. *Stdlib + vanilla JS, no framework.* A React/Vite/Flask stack would be the only npm/pip dependency in the repo for a viewer; the standard server plus one page does the whole job and stays testable offline.
4. *Reuse readers, don't reshape data.* Endpoints return thin projections of `progress.json` messages (which already hold the full model transcript: text, function calls, outputs), the case record, and the audit log — so the UI can never disagree with the CLI.

## Steps

1. **Server skeleton + run endpoints.** `ui/server.py`: route table, JSON error envelope, `GET /api/runs` (id, status, turn, model, updated), `GET /api/runs/<id>` (status, turns with per-turn model text / tool call / result / usage). Unknown run → 404 JSON. Unit tests against a fixture workspace (no sockets needed: test handler dispatch functions directly).
2. **Record, audit, figure endpoints.** `GET /api/runs/<id>/record` (checklist, facts, requests with reason codes, memo, item reviews), `GET /api/runs/<id>/audit` (tolerate a torn trailing line from a concurrent append — skip, don't 500), `GET /api/runs/<id>/figures` (metadata) + `GET /api/runs/<id>/figures/<name>` (bytes, SVG/PNG content types, names restricted to `fig-*` to prevent path escape). Tests incl. the torn-line and path-escape cases.
3. **The page.** `ui/index.html`: run list view + run detail view (transcript, record, audit, figures), 2s poll with visibility-pause, run selector via URL hash (`#run=<id>`) so views are linkable. Manual check in the browser; automated check that the file references only local endpoints (no external URLs).
4. **Wiring + docs.** `./helper ui [--port]` case + usage line, `OPERATE.md` section, README command line. Manual check of the full loop below.

## Validation Plan

- `./helper test` (full suite, both `VERIFICATION` modes) — must stay green.
- New `tests/test_ui.py`: endpoint projections on a fixture workspace (run list shape, transcript pairing of call→result, record passthrough, audit torn-line tolerance, figure path-escape refusal, 404s). Offline, no ports bound.
- Black-box: start `./helper ui --port 8613`, `curl` each endpoint for 200 + JSON shape; start `./helper run --turns 5` in another terminal and confirm new turns appear in the page without restart.
- Read-only proof: `grep` the server for mutating calls (must be GET-only; no imports of `answer_request`/`review_*`/`file_*` paths) plus a `POST /api/...` returns 405 check.
- Highest-risk validation: the live-runs-during-run check — concurrent file reads while the loop writes. Mitigated by atomic `progress.json` writes (already tmp+replace) and torn-line-tolerant audit reading; the manual check above is the evidence.

## Risks / Open Questions

- **Risks**: (a) port already in use → `--port` override + clear "address in use" message; (b) very long transcripts → cap the transcript payload to the latest 200 messages with a `?full=1` escape hatch; (c) a browser on another machine can't reach it — by design (localhost-only, no auth needed for v1).
- **Non-goals**: browser review/approve actions, auth/multi-user, editing runs, anything beyond `127.0.0.1`.
- **Open questions**: None.
