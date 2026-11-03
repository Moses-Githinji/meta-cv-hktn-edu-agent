# Escalation rules (teaching)

When a run stops for a person, what the person sees, and how the run resumes.
Every escalation names one checklist item and one reason code
(`edu_kit/escalation.py`). A run that stops for a person makes no model calls
until someone acts.

## Reason codes

| Code | Raised by | Meaning |
|---|---|---|
| `teacher_input` | `ask_teacher` | One question the teacher must answer (e.g. an outcome is pending transcription). |
| `missing_outcome_text` | `escalate` | A term outcome has no transcribed wording, so coverage cannot be confirmed. |
| `timetable_clash` | `escalate` | The planned coverage does not fit the week's timetable slots. |
| `calendar_clash` | `escalate` | The plan conflicts with the term calendar (half-term, closing, catch-up). |
| `document_refused` | `submit_document` | The document failed the inline checks 3 times; the agent needs guidance. |
| `exam_signoff` | `escalate` | An exam document needs head-of-department review before use. |

(`missing_evidence` and `memo_refused` are the retired legal equivalents.)

## When a run stops

| Trigger | Status | What unblocks it |
|---|---|---|
| The agent calls `ask_teacher` | `needs_input` | The teacher answers (`./helper review RUN --answer R1 --notes "..."`). |
| The agent calls `escalate` | `escalated` | The person named by the code answers the same way. |
| The document is refused 3 times | `escalated` (`document_refused`) | The reviewer replies with guidance, then resumes. |
| The document passes the scheme rules and the claims check | `awaiting_signoff` | The teacher approves, or rejects with notes. Exam documents then wait for the head of department (`--hod-approve` / `--hod-reject`). |

One request is open at a time. Escalating an already-covered item, or while a
request is open, is refused.

## Handoff

The review console (`./helper review RUN --list`) shows the reviewer each
item, its finding, and the curriculum text beside it, plus the blocked item,
the reason code, and the one specific need.

## Resume

`./helper run --resume RUN_ID` continues the same run from its saved progress:

- **After `needs_input` / `escalated`**: resumes only if the request was
  answered (or new documents appeared); otherwise it is refused with no model
  call. The agent gets the reply and continues.
- **After sign-off**: approve ends the run as `done` with no model call
  (exams need teacher + head-of-department approval); reject sends the notes
  back to the agent, which files a revised document.
- **After the turn limit** (`paused`): the agent is told it has more turns.
