# Pilot and release (Z)

## Pilot: a few teachers

- Scope: 2–3 teachers, one school, Grade 7 Mathematics Term 1 only. The
  agent drafts schemes, lesson plans, and exams; teachers review everything
  in `./helper review` before any classroom use.
- Entry bar: `./helper eval` green, `./helper test --verification` green,
  dashboard pass rate ≥ 80% on the pilot runs.
- Weekly loop: collect teacher edits (dashboard edit rate), turn repeats
  into golden tasks, review escalations for missing packs or wording.
- Exit bar: two consecutive weeks with no refused filings the teachers did
  not cause, and sign-off recorded per teacher. Then widen one subject or
  level at a time (see EXPANSION.md).

## Privacy and security review

Data the system holds, and where:

| Data | Location | Sensitivity |
|---|---|---|
| API keys | `.env` (never committed) | secret |
| Teacher notes, answers, reviews | `workspace/case_records/` | personal: a teacher's words |
| Run conversations, audit logs | `workspace/runs/` | operational, may quote notes |
| Curriculum packs | `curriculum/` | licensed: KICD permission pending (see docs/) |
| Raw fetches, receipts, alerts | `var/` (gitignored) | operational |

Review checklist (re-run before release):

- [ ] `.env` not in git; keys rotatable; no key in logs, reports, or exports
      (audit entries carry tool names and statuses, never credentials).
- [ ] Teacher words stay on the pilot machine; exports shared externally
      are teacher-approved documents only.
- [ ] Fetcher still allowlisted, robots-respecting, rate-limited; no new
      hosts without a scope note.
- [ ] Quarantined content reviewed, never published raw.
- [ ] Dependencies pinned (`requirements.txt`); `./helper setup` from clean.

## Retention policy

- Run artifacts (`workspace/runs/`, `workspace/case_records/`): 90 days,
  then `./helper retention --apply`. Teacher words go with the runs.
- Alert log (`var/pipeline/alerts.jsonl`), pack history, receipts: kept
  (operational memory, no teacher PII beyond run references).
- Curriculum packs and teacher context: kept (the product).
- Backups follow the same windows: a restored backup older than policy is
  purged on restore.

## Release

1. Freeze: evals + full suite green on the release commit.
2. Review: privacy/security checklist above, signed.
3. Deploy: per OPERATE.md (repo + `.env` + cron + `var/` backup).
4. Support: one contact, weekly dashboard review for the first month,
   rollback via git + `./helper pipeline rollback`.
