# Verification layer (teaching)

On for runs started with `VERIFICATION=on` in `.env`. Every check is one file
in `verification/` with one entry point,
`run_verification(ctx, work) -> {"passed": bool, ...}`. The teaching tools
call them at fixed points, so the agent cannot skip them. The legal originals
are preserved in `docs/legal-reference/LEGAL_VERIFICATION.md`.

| When | File | Check | On failure |
|---|---|---|---|
| `set_checklist` | `verification/verify_teaching_checklist.py` | Set comparison: every term outcome id is named in some item's question or evidence_needed (transcribed to cite, pending as gaps) | Refused with the missing outcomes. After 3 tries the checklist is accepted, and the score and feedback are kept for the reviewer. |
| `submit_document` | `verification/verify_scheme.py` | Scheme rules: the document shape (via `submit_document.check`), every item proven or escalated in the record, every recorded citation still the pack's exact text, no request still open | Refused with the problems |
| `submit_document` | `verification/verify_claims.py` | Each proven finding is supported by its quotes (one judge call per document, after the scheme rules pass). Fails closed: an unreadable judgement refuses the document | Refused with the claims |
| 3 refused documents | | | Escalated to a person (`document_refused`) |
| The document passes | | Pause for teacher sign-off (`awaiting_signoff`); exam documents then wait for the head of department | Rejected: the notes go back to the agent |

Roots without a teaching pack keep the legal checks (`verify_checklist.py`
ground-truth judge, `verify_memo.py`).

## Independent verification

`./helper verify RUN_ID --independent` runs a separate process that
recomputes everything from the saved artifacts: the scheme rules, the
checklist set comparison, the claims judgement with a different judge model
(`JUDGE_MODEL`, must differ from the agent model), and the audit-log hash
chain. It also hashes the filed document (SHA-256), so any later edit is
detectable.

## Audit log

Every tool call and loop event is appended to the run's hash-chained log
(`workspace/runs/<run-id>/audit.jsonl`); `edu_kit/audit.py` appends and
replays it.

## On work already done

`./helper verify RUN_ID --memo` and `./helper verify RUN_ID --checklist` run
the same checks on a finished run (the agent is not involved; the run is not
changed). `./helper branch RUN_ID` starts a new run with verification on from
the run's checklist step; resume it to continue.
