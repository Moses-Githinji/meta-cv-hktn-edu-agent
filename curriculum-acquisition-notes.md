# Curriculum acquisition notes (provisional, revisit as the app grows)

Date: 2026-11-01. Phase 1 decision, recorded here per project owner.

## Decision: KICD email deferred

Sending the permission request now is deferred: a reply is uncertain and
waiting would stall the build. The draft is retained at
`docs/kicd-permission-request.md` and can be sent later if needed.

## Direction: web scraping tool for curriculum materials

Build a scraper that collects the required Grade 7 Mathematics curriculum
materials from the web, including:

- `kicd.ac.ke` (official designs portal and Kenya Education Cloud links);
- third-party sites where others have shared the same designs (finding aids).

Requirements for when this is built:

- Respect robots.txt and site terms; rate-limit; identify the crawler.
- Record source URL + retrieval date with every artifact.
- Dedupe identical files (sha256); land raw files outside git.
- KICD remains the authority: on any conflict between copies, the official
  design wording wins, and every outcome keeps its KICD source_ref.

## Image ingestion: use Muse Spark multimodal

Some artifacts will be images or scanned pages. The current best fit is
Muse Spark (`muse-spark-1.3`) through the Files API transcription path the
kit already has: `edu_kit/document_text.py` transcribes PDF, JPG, JPEG, and
PNG page by page, and `analyze_document` is the tool that triggers it. No
new model is needed for the MVP. `sam-3.1` is for segmentation, not text
extraction, so it is not the ingestion choice. Revisit only if transcription
quality gaps appear on real artifacts.

## Standing cautions

- Third-party copies do not settle the rights question. Keep exact-text use
  attributed to KICD, keep the permission draft on file, and re-seek
  permission before any redistribution beyond this prototype.
- Nothing scraped enters `curriculum/grade7-mathematics-term1.json` except
  through the `curriculum/TRANSCRIBE.md` workflow (verbatim copy, human
  review, loader check).

## Next steps (when revisited)

1. Spike the scraper against the KICD designs portal; confirm what is
   reachable without authentication.
2. Decide the raw landing zone and manifest format.
3. Wire a transcription queue: raw artifact -> Spark transcription ->
   human verbatim check -> pack entry -> `loader.py --check`.
