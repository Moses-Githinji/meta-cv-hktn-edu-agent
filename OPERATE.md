# Operate

Running the system day to day: evals, routing, dashboard, retention,
deployment, support.

## Golden evals (V)

`evals/tasks/*.json` are replayable golden tasks (more subjects and levels as
packs land; tasks without a pack skip with a reason). Task format: fixture
pack, scripted tool/record steps with optional `expect_error` /
`expect_status`, and final expectations (status, cited outcomes, escalation,
exam total, figures + read-back specs).

```bash
./helper eval                 # offline replay of every task
./helper eval --task exam-filing
./helper eval --live          # free-run with the live API (MODEL_API_KEY)
./helper eval --shadow JUDGE  # compare a shadow judge per filed memo
```

Exit code is 1 when any task fails. Authoring rule: a new capability lands
with at least one golden task pinning it.

## Model routing (W)

`routing/`: `registry.py` (known models; prices live in
`var/routing/prices.json` as `{model: {in_per_1k, out_per_1k}}` — no invented
defaults), `table.py` (static role table, agent + judge), `performance.py`
(recorded outcomes → best qualified model), `shadow.py` (second-model
comparison that never breaks runs).

- Static table first: `MODEL_API_MODEL` / `JUDGE_MODEL` decide, as before.
- Hard rule, enforced by `resolve_pair()` and independent verification:
  the judge never equals the generator.
- Performance choice later: feed outcomes with `performance.record()`
  (evals can log them), read `stats()` to promote a winner by hand once it
  has 5+ samples. The router never auto-switches production.

## Dashboard (X)

```bash
./helper dashboard              # text: pass rates, escalations, edit rates, cost, scrape
./helper dashboard --json
./helper dashboard --html FILE  # standalone report (open directly, no server)
./helper dashboard --alerts     # record threshold alerts (pass rate, pile-ups, errors, staleness)
```

Costs need `var/routing/prices.json`; unpriced tokens are reported, never
priced by guesswork.

## Console (browser UI)

```bash
./helper ui                 # start the console, then open http://127.0.0.1:8765
./helper ui --port 8613     # a different port; --root PATH points at another checkout
```

Localhost only, no login: never expose it to a network. It reads the run
files and acts only through `./helper` (start/resume runs, answer/approve/
reject, checks, reset). Full data contract in `ui/README.md`; try it without
the agent via `python3 ui/make_demo.py demo_repo`.

## Retention

Policy: run artifacts (conversation, audit log, figures, exports) go after
90 days; curriculum packs, teacher context, and the alert log stay.

```bash
./helper retention              # dry run: what would go
./helper retention --apply      # delete (run dir + case record only)
```

## Deployment

One machine, no services: this repo + `.env` (MODEL_API_KEY, JUDGE_MODEL,
prices) + `.venv` from `./helper setup`. Schedule the two loops in cron:

```
0 3 * * 0 cd /path/to/repo && ./helper pipeline refresh >> var/pipeline/cron.log 2>&1
0 4 1 * * cd /path/to/repo && ./helper retention --apply >> var/pipeline/cron.log 2>&1
```

Back up `var/` (raw store, pack history, receipts, alert log) with the repo.
Rollback is `./helper pipeline rollback [VERSION]` for packs; releases roll
back with git (nothing above runs migrations).

## Support

- Something refused? Read the refusal: every tool, gate, and check says
  what to fix. `./helper dashboard --alerts` lists what needs a human.
- Agent stuck mid-run? `./helper run --resume RUN_ID` after answering the
  open request (`./helper review RUN --list` shows it).
- Suspicious pipeline content? It is already quarantined under
  `var/quarantine/`; review the file, never publish it directly.
