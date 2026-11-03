# Documents (Phase 5)

The scheme of work itself plus the follow-up documents built on the
approved scheme: lesson plans, exams, diagrams, and Word/PDF export.
All stdlib, all offline-testable.

## Scheme table

Kind-`scheme` filings carry the week-by-week lesson table (`lessons` on
`submit_document`, enforced by its `check` on teaching roots):

- exactly one row per pack week and timetable period (12 weeks x 5
  periods = 60 rows), every slot exactly once, no duplicates;
- each row ties to a checklist item and fills every column: topic,
  subtopic, objectives, teaching methods, learning activities,
  references, remarks (1-2 sentences each);
- row citations are optional but must match recorded citations when
  present (same rule as findings).

`export/build.py` renders it as the landscape table (Wk, Pd, Topic,
Sub-topic, Objectives, Teaching Methods, Learning Activities,
References, Remarks) with the header repeated on every page, followed
by the coverage notes and gaps. Cited outcome ids are appended to the
objectives cell.

## Lesson plans (R)

`submit_lesson_plan` files one week's lessons (`lessons/validate.py`):

- every lesson ties to **approved** scheme rows (reviewer verdict
  `approved` or `edited`; rejected or unreviewed rows refuse);
- activity minutes must sum **exactly** to the day's timetable slot
  (`teacher_context/timetable.json`); days without a slot refuse;
- weeks are pack weeks; cited figures must exist.

Filed plans are `LPn` on the case record.

## Exams (S)

Kind-`exam` filings carry the exam payload, checked by `exams/validate.py`:

- **blueprint**: total marks + per-outcome sections (question counts and
  marks each match the questions);
- **marks arithmetic**: question totals equal the blueprint total and the
  marking-scheme total; every question has exactly one scheme entry with
  equal marks (`check_answers` runs the answer check standalone);
- **marking scheme**: one answer per question, non-empty, with marks;
- **originality** (`exams/originality.py`): questions sharing a 10+ word
  verbatim run with an outcome or a scheme finding are refused, as are
  duplicate questions.

## Diagrams v1 (T)

`diagrams/`: `spec.py` (strict specs: graph, geometry, circuit, apparatus,
ray), `layout.py` (specs to pixel-space drawings), `svg.py` + `png.py`
renderers, `readback.py` (independent SVG parse-back and spec comparison).

- `check_diagram` validates a spec; `make_diagram` renders it to SVG + PNG
  and files it as `fig-N` under the run's `figures/`.
- PNG labels render in capitals from an embedded 5x7 font (SVG keeps exact
  case); one stroke width, no anti-aliasing.

## Export (U)

`./helper export RUN --what scheme|exam|marking-scheme|lesson-plan
--format docx|pdf [--out FILE]` (`export/`):

- figures number sequentially in order of appearance;
- the marking scheme embeds each answer's figures beside its answer;
- every page carries a footer (Word: page field; PDF: page numbers).
