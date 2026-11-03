# Expansion (Y)

How the system grows beyond Grade 7 Mathematics, in dependency order. Each
item is shippable alone; each ends with its acceptance check.

## New subject or level (shipped: the seam)

The loader (`curriculum/loader.py`) accepts only combos in `SUPPORTED`, and
the tools read the pack named by `CURRICULUM_PACK` (default
`grade7-mathematics-term1`). To add one, e.g. Science 7:

1. Add `("Science", 7, "CBC")` to `SUPPORTED` and the enums in
   `curriculum/schema.json`.
2. Add `curriculum/science-grade7-term1.json` via the TRANSCRIBE.md workflow
   (verbatim, human-reviewed, `loader.py --check` green).
3. Add golden tasks (copy `evals/tasks/scheme-happy-path.json`, new pack +
   outcome ids) and unskip them by landing `evals/packs/<pack>.json`.
4. Run `./helper eval` and the full suite.

Accept: loader green, evals pass, dashboard unchanged for old runs.

## Apparatus and ray diagrams (shipped)

`diagrams/` kinds `apparatus` (beaker, flask, test tube, burner) and `ray`
(rays with arrowheads, mirror/lens optics), with spec validation, SVG+PNG
rendering, and read-back — same contract as the first three kinds.

## Biology and geography libraries (next)

New glyph sets behind the same spec contract: propose the symbol list
(e.g. biology: cell, leaf, flower; geography: compass, contour, map pins),
add one kind per library or extend `apparatus`, add golden diagram tasks.
Do not add clip-art realism: labelled line glyphs, as now.

## Kiswahili (next)

Order: (1) export strings behind a language flag (`--lang sw`:
headings, captions, footers); (2) system-instructions variant reviewed by a
Kiswahili-speaking teacher; (3) Kiswahili outcome packs only from confirmed
KICD Kiswahili sources. Never machine-translate outcome text: outcomes stay
in the source language, everything around them translates.

## 8-4-4 (only if wanted)

8-4-4 is a different curriculum, not a new level: separate packs, separate
`SUPPORTED` combos (e.g. `("Mathematics", 8, "8-4-4")`), separate evals, and
a scope decision recorded in `docs/01-scope-and-permissions.md` first. Do
not mix 8-4-4 wording into CBC packs.
