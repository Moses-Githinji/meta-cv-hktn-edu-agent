# Transcribing outcomes (exact-text workflow)

Outcome text is copied exactly from the official KICD design. No paraphrase,
no invention. Stubs stay `pending_transcription` until a human transcribes them.

## Steps

1. Confirm the KICD permission reply is filed (see
   `docs/01-scope-and-permissions.md`).
2. Open the official design for the subject (Junior School Curriculum
   Design, Grade 7) from
   https://kicd.ac.ke/cbc-materials/curriculum-designs/grade-seven-designs/
3. For each `TODO_TRANSCRIBE` stub in the subject's file
   (`curriculum/grade7-mathematics-term1.json`,
   `curriculum/grade7-cre-term1.json`, `curriculum/grade7-english-term1.json`,
   `curriculum/grade7-kiswahili-term1.json`,
   `curriculum/grade7-agriculture-term1.json`,
   `curriculum/grade7-french-term1.json`):
   - copy the outcome statement verbatim into `outcome_text` (official
     spelling, including accents);
   - extend `source_ref` with the design's page number;
   - set `status` to `transcribed`.
   - optionally add the design's own lists, verbatim, one string per
     bullet: `suggested_learning_experiences`, `key_inquiry_questions`,
     `assessment`, `learning_resources`. Leave a field out when the
     design has nothing for it; never invent entries.
   - If one sub-strand has several outcomes, add one entry per outcome
     (`G7M-T1-1.1.2`, …) rather than merging them into one string.
   - Confirm the provisional strand names and week ranges against the
     design as you go; fix them in the same diff.
4. Run `python3 curriculum/loader.py --check`: it must print `valid` and the
   new coverage count.
5. Have the Curriculum Owner review the diff before commit.

## Rules

- Never mark a stub `transcribed` without copying the printed text.
- Never take outcome wording from schemes of work, notes sites, or lesson
  books: those are teachers' words, not KICD's.
- The loader refuses a `transcribed` entry whose text is still a stub.
