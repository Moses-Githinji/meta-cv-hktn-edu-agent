# Reproduce this project

How to set up the Kenya teaching agent on your own computer, run it from
start to finish, and check that you got the same results. Every command
below was checked against this repository.

## What "same results" means

A language model does not give word-for-word identical answers on every
run. So reproduction has two layers:

| Layer | Exactly the same for everyone | Will differ |
|---|---|---|
| Offline tests + golden evals | Yes — scripted, no API, no network | Nothing |
| Curriculum data | Yes, if the pack hash matches (see step 6) | Nothing |
| Live run | The structure: turns, tool calls, statuses, checks | The wording. Check it against step 9, not word for word |

There is no recorded-run replay yet (see [Known gaps](#known-gaps)).
The offline suite is the exact-match test.

## 1. Prerequisites

- **OS:** macOS, Linux, or Windows with WSL. Plain Windows will not
  work: `./helper` needs a Unix shell.
- **Software:** `git`, and Python 3.9 or newer with `python3-venv`
  (`python3 --version` to check).
- **Model API key:** only needed for live runs and the judge-backed
  checks. Tests, evals, and the demo console need no key. Use your own
  key; never share it or commit it.
- **Power:** keep a laptop plugged in and awake during live runs. If the
  machine sleeps mid-run, the run is left behind (see [Troubleshooting](#troubleshooting)).

## 2. Get the code

```bash
git clone <REPO_URL>
cd kenya-teaching-agent   # or whatever the checkout folder is called
```

There are no release tags yet, so record the exact commit for your notes:

```bash
git rev-parse HEAD
```

## 3. Configure your settings

```bash
cp .env.example .env
```

Open `.env` in a text editor. The values that matter for reproduction:

```bash
MODEL_API_KEY=your_own_key_here   # live runs only; leave empty for offline-only use
MODEL_API_MODEL=muse-spark-1.3    # pinned: do not change if you want comparable results
TEACHING_PACK_DIR=./packs/grade7-mathematics-term1
VERIFICATION=off                   # on | off
JUDGE_MODEL=                       # review deployment for the independent check (see step 10)
```

Never commit `.env`. The agent talks to the Meta Model API
(`https://api.meta.ai/v1`) through the OpenAI Python SDK.

## 4. Set up the environment

```bash
./helper setup
```

This creates `.venv` inside the project, installs `requirements.txt`
into it, seeds the pack inbox, and checks your key against the live API.

- `./helper setup` needs a **working** key, because it validates it.
  Without one it stops and tells you to add the key and re-run.
- Do not copy a `.venv` from another computer or OS. Always let setup
  (or the manual commands below) build it on the machine itself.
- Never install into the system Python (`--break-system-packages`):
  the project environment is `.venv` at the repo root.

**Keyless path** (offline tests and evals only — no live runs, no
judge checks): build the environment by hand instead of running setup.

```bash
cp .env.example .env   # TEACHING_PACK_DIR must be set even without a key
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 5. Run the offline tests

```bash
./helper test                # checks off
./helper test --verification # checks on
```

They use a scripted fake model: no key, no network. Success looks like:

```text
Ran 210 tests in ~60s

OK
```

(The count grows as the suite grows; some tests skip per mode — skips
are expected, failures are not.)

## 6. Confirm the curriculum data

The agent reads `curriculum/*.json`. Confirm yours matches everyone
else's by hashing it:

```bash
sha256sum curriculum/grade7-mathematics-term1.json
```

Compare the hash with the other person's. The console also shows a
12-character version of these files as the pack badge (step 8).

> Current pack state: the outcome texts are still placeholders
> (`TODO_TRANSCRIBE`, status `pending_transcription` — see
> `curriculum/TRANSCRIBE.md`). This is on purpose at this stage, and it
> shapes what a live run does: the agent cannot cite untranscribed
> outcomes, asks the teacher about them, and files gaps. A full-coverage
> scheme is only reproducible once the pack is transcribed.

## 7. Run the golden evals

```bash
./helper eval
```

Offline replay of scripted capability tasks (filing, refusals,
escalation, diagrams). Success looks like:

```text
6 passed, 0 failed, 2 skipped
```

Skips name packs that have not landed yet (`pack ... not landed yet`) —
expected. Exit code is 1 if any task fails. (Evals create run folders
under `workspace/`, which is gitignored.)

## 8. Start the console

```bash
./helper ui
```

Then open http://127.0.0.1:8765 (localhost only, no login — never
expose it to a network). `--port N` changes the port, `--root PATH`
points at another checkout.

**No key?** Try the console on a demo repository instead — three sample
runs, a stand-in helper, and a sample pack, all offline:

```bash
python3 ui/make_demo.py demo_repo
python3 ui/ui.py --root demo_repo
```

## 9. Do a live run

Needs `MODEL_API_KEY`. In the console:

1. Check the task is the Grade 7 Mathematics Term 1 pack and the pack
   badge matches the files from step 6.
2. Tick **Step through turns** (leave turns at 30) and click **Start
   agent**. Step through a few turns: Plan, Act, Observe per turn.
   Expect the agent to list the curriculum, draft its checklist, then
   stall on the untranscribed outcomes.
3. Click **Run to end** when you have seen enough stepping.
4. When the status becomes `needs_input`, the agent is asking you
   something (currently: an outcome it cannot read). Type the answer
   and click **Send answer and resume**. The standing answer used so
   far: official wording is unavailable, do not invent outcome text,
   proceed with what the pack has and list every untranscribed outcome
   as a gap.
5. The run ends `answered` (checks off: document filed without checks)
   or `awaiting_signoff` (checks on: filed after passing).

The same run from the terminal:

```bash
./helper run --turns 30
./helper run --resume RUN_ID --turns 15   # after answering, or at the turn limit
```

A run prints one line per turn (`Turn 6: update_plan → … · facts 0 ·
running`) and a final `{run_id, status, turn}` object.

To keep a run going in the background while you do other work:

```bash
setsid -f ./helper run --turns 30 </dev/null >>/tmp/agent-run.log 2>&1
```

## 10. Run the checks

In the console's **Verify this run** card, or the terminal equivalents:

```bash
./helper verify RUN_ID --memo        # document rules + claims judge (uses the API)
./helper verify RUN_ID --checklist   # checklist check (no model calls, but needs the key set)
./helper verify RUN_ID --independent # separate process: recomputes, different judge, hash chain
```

Notes:

- All three need `MODEL_API_KEY` set; `--memo` and `--independent`
  spend tokens on the judge, `--checklist` does not.
- `--independent` needs `JUDGE_MODEL` pointing at a real review
  deployment, and the judge must differ from the generator. The audit
  hash-chain replay inside it is offline.
- Results append to `workspace/runs/RUN_ID/verification.json` and show
  as history in the console.

With the current pack, expect the checks to report gaps rather than
pass cleanly — that is the honest result until transcription lands.

## 11. Review as the teacher, then export

```bash
./helper review RUN_ID --list        # one row per item, with curriculum text
./helper review RUN_ID --item ITEM --approve   # per-row: --approve | --reject --notes … | --edit --notes …
./helper review RUN_ID --approve     # whole document (--reject needs --notes)
```

Exam documents additionally need the head of department after you:

```bash
./helper review RUN_ID --hod-approve   # or --hod-reject --notes …
```

In the console, the review card shows each citation beside its official
outcome text (tick: quoted words appear; cross: they do not).
Unverified rows must be ticked before **Approve** unlocks; approval of
an exam moves it to `awaiting_hod`, otherwise to `done`.

Export the finished document (offline, pure-Python writers):

```bash
./helper export RUN_ID --what scheme --format pdf --out /tmp/scheme.pdf
./helper export RUN_ID --what scheme --format docx --out /tmp/scheme.docx
```

(`--what` is `scheme` | `exam` | `marking-scheme` | `lesson-plan`.)

Share it by email (needs `SMTP_*` in `.env`; see `.env.example`):

```bash
./helper send RUN_ID --what scheme --format pdf --to teacher@school.edu --dry-run  # preview, no send
./helper send RUN_ID --what scheme --format pdf --to teacher@school.edu
```

## 12. Operate

Pointers; detail lives in `OPERATE.md` / `PIPELINE.md`:

```bash
./helper branch RUN_ID            # continue a run from its checklist, verification on
./helper pipeline staleness       # + fetch|extract|gates|diff|publish|rollback|refresh|schedule|propose-dates|alerts
./helper dashboard                # pass rates, escalations, edit rates, cost, scrape health
./helper retention                # dry run of the 90-day artifact policy (--apply deletes)
./helper reset [--clear-runs]     # reset the inbox to the pack's documents
```

Do not refresh the curriculum pack when reproducing someone's results:
a changed pack means different results.

## 13. Checklist: did you reproduce it?

- [ ] Same commit (`git rev-parse HEAD`) and same pack hash (step 6).
- [ ] `./helper test` and `./helper test --verification` fully pass.
- [ ] `./helper eval` passes with only pack-missing skips.
- [ ] Console loads; pack badge matches the hashed files.
- [ ] A live run moves through turns, pauses for input with a sensible
      question, and files a document after the answer.
- [ ] Every citation the agent makes points at an outcome in the pack
      (currently: citations are refused and gaps filed — correct for
      this pack state).
- [ ] Checks run; anything unverified is flagged, not silently passed.
- [ ] Teacher approval moves the run to `done` (or `awaiting_hod`).
- [ ] Exported PDF/DOCX opens with the filed content.

Different live-run wording is expected and is not a failure.

## Troubleshooting

| Problem | What to do |
|---|---|
| `MODEL_API_KEY is not set` | Add the key to `.env` at the repo root (no spaces or quotes) |
| Key rejected during setup | The key must have access to the pinned model (`muse-spark-1.3`) |
| Tests fail on a fresh clone | Rebuild the env: `rm -rf .venv` then `./helper setup` |
| Killed run cannot resume (`nothing to resume`) | Only `paused`, answered `needs_input`/`escalated`, and approved `awaiting_signoff` runs resume. A killed run keeps status `running`; continue from its checklist with `./helper branch RUN_ID` |
| Run stopped at the turn limit | `./helper run --resume RUN_ID --turns 15`, or **Resume this run** in the console |
| Port already in use | `./helper ui --port 8766` |
| Console shows "No repository found" | Start it from the repo root, or pass `--root PATH` |
| Live wording differs from someone else's | Expected — use the checklist above, not a word diff |

## Known gaps

What does not exist yet, so no guide can promise it:

- **Release tags / CI** — pin by commit hash until tags and a test job exist.
- **Locked dependencies** — `requirements.txt` is a loose range; record
  `pip freeze` output alongside your results if versions matter to you.
- **Recorded-run replay** — evals replay scripted tasks, not a live run
  byte for byte. There is no `./helper replay` or expected-hash file.
- **Pack version file** — use `sha256sum` (step 6) and the console badge.
- **Transcribed pack** — live runs file gaps by design until
  `curriculum/TRANSCRIBE.md` is worked through.
- **Judge deployment** — `--independent` needs a real `JUDGE_MODEL`.
