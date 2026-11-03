# Curriculum data pipeline

Fetches curriculum artifacts from allowlisted sources, extracts outcome
candidates, gates them, and publishes pack updates. Stdlib only (`pipeline/`);
local data lives in `var/` (gitignored). Nothing publishes without the gates
and a named human reviewer, per `curriculum/TRANSCRIBE.md`.

## Flow

```
sources (allowlist) -> fetch -> raw_store -> extract -> gates/diff -> publish
schedule/refresh runs the loop; alerts records every failure.
```

| Step | Module | What it does |
|---|---|---|
| Allowlist | `pipeline/sources.py` | Only listed hosts; authorities citable, mirrors finding aids only |
| Fetch | `pipeline/fetch.py` | Allowlist + robots.txt + per-domain rate limit + crawler UA; fails closed |
| Discover | `pipeline/discover.py` | Lists PDFs linked from a fetched page, plus Drive file IDs embedded in it (incl. WordPress page JSON via `--slug`); never fetches the documents itself |
| Drive download | `pipeline/drive.py` | Downloads one Drive file an authority page embeds; robots + rate limit + one confirmation round-trip; fails closed with a manual fallback |
| Raw store | `pipeline/raw_store.py` | Content-addressed blobs, SHA-256 dedupe, manifest with URLs + dates |
| Extract | `pipeline/extract.py` | HTML/text to candidate records, provenance on every record; PDFs refused until transcribed |
| Gates | `pipeline/gates.py` | Schema, unmapped, authority, immutable text, no removals, stubs, suspicious content |
| Diff | `pipeline/diff.py` | Added/removed/transcribed/changed per outcome id |
| Publish | `pipeline/publish.py` | Human `reviewed_by` required; backup, atomic write, receipt; rollback |
| Staleness | `pipeline/staleness.py` | Pack and source freshness vs a max age |
| Schedule | `pipeline/schedule.py` | Interval + due; refresh fetches, extracts, gates, reports (never publishes) |
| Term dates | `pipeline/term_dates.py` | Proposes dates from calendar artifacts; a human applies them |
| Alerts | `pipeline/alerts.py` | Append-only failure log |

## Commands

```bash
./helper pipeline fetch URL
./helper pipeline discover URL   # fetch a page (stored), list its allowlisted PDF links + Drive embeds
./helper pipeline discover --slug grade-seven-designs  # same, via the KICD page's JSON
./helper pipeline drive-download FILE_ID --from PAGE_URL  # download one embed (PAGE must be an authority)
./helper pipeline drive-download FILE_ID --from PAGE_URL --drive-robots-exception  # authorized bypass, recorded
./helper pipeline extract SHA
./helper pipeline gates | diff
./helper pipeline publish --reviewed-by NAME
./helper pipeline rollback [VERSION]
./helper pipeline staleness
./helper pipeline refresh          # scheduled run (cron: ./helper pipeline refresh)
./helper pipeline schedule [--interval-days N]
./helper pipeline propose-dates
./helper pipeline alerts
```

Live note (2026-11-02): the designs index page renders its document links with
JavaScript tabs, so `discover` on the plain page URL returns no PDF links.
But the same page's WordPress JSON (`discover --slug grade-seven-designs`)
lists all 16 subject embeds as Google Drive file IDs. Downloading the bytes
is blocked by Drive's robots.txt (`Disallow: /` covers the `/uc` download
endpoint), so `drive-download` fails closed there unless the operator passes
`--drive-robots-exception`: an explicit, per-download bypass that skips only
the robots check (allowlist, throttle, and authority-page rules still apply)
and is recorded on the artifact as `robots_exception: true` for audit. File
preview pages (`/file/...`, explicitly Allowed) fetch without any exception.
Decisive follow-up: KICD shared the design files view-only ("the owner
hasn't given you permission to download this file"), so even with the
exception the bytes are unavailable to anyone but KICD's owners/editors —
manual downloading fails the same way. The remaining routes are contacting
KICD, finding downloadable copies (e.g. Kenya Education Cloud), or a human
transcribing from the viewable previews.

Source survey (2026-11-02, all fetches via the pipeline): KEC's OER portal
holds interactive courses only (Grades 1/2/6, no Grade 7, no PDFs);
`resources.kec.ac.ke` was unreachable; the LMS Grade 7 category needs a
login and holds lessons, not designs; KICD's own media library has
downloadable PDFs but only pre-2020 volumes and tenders — no Grade 7
designs. No downloadable Grade 7 curriculum designs found anywhere
reachable; KICD contact or transcribe-from-preview remain.

## Rules the gates enforce

- Outcome wording comes from authorities (KICD, Ministry ecosystem) only.
- Transcribed wording is immutable; pending slots fill once.
- Outcomes are never removed; new ids need a human-added pending entry first.
- Suspicious content (scripts, instruction overrides) is quarantined, never published.
