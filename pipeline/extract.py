"""Extract and normalise: raw artifacts in, outcome candidate records out.

Every record carries provenance (source URL, retrieval time, artifact SHA,
extractor name + version), so gates can judge where wording came from and a
reviewer can trace any line back to its bytes.

Supported inputs (by content type):

- text/plain: blank-line-separated blocks of "key: value" lines. Required
  keys: id, text. Optional: strand, sub_strand, source_ref.
- text/html: elements with a data-outcome-id attribute; their text content
  is the outcome. Optional data-source-ref, data-strand, data-sub-strand.
- application/pdf: refused here — scanned/Authored PDFs go through the
  Files-API transcription queue first (see curriculum-acquisition-notes.md),
  and only its text output enters this pipeline.

Normalisation collapses whitespace only; case and wording are kept exactly
as fetched, because outcome text must stay verbatim.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

EXTRACTOR_VERSION = "1"

_WS = re.compile(r"\s+")


class ExtractionError(ValueError):
    """The artifact cannot be extracted. Safe to show and to log as an alert."""


def normalise(text: str) -> str:
    """Collapse whitespace; keep case and wording exactly."""
    return _WS.sub(" ", text or "").strip()


def provenance_for(
    url: str, retrieved_at: str, sha256: str, extractor: str
) -> dict:
    return {
        "source_url": url,
        "retrieved_at": retrieved_at,
        "sha256": sha256,
        "extractor": extractor,
        "extractor_version": EXTRACTOR_VERSION,
    }


def extract(
    body: bytes,
    content_type: str,
    url: str,
    retrieved_at: str,
    sha256: str,
) -> list:
    """Extract candidate records from one artifact. Unknown types are refused."""
    kind = (content_type or "").split(";")[0].strip().lower()
    if not kind:
        kind = "text/html" if body.lstrip().startswith(b"<") else "text/plain"
    if kind == "application/pdf":
        raise ExtractionError(
            "PDF artifacts need transcription before extraction: run the "
            "Files-API transcription queue, then extract its text output"
        )
    if kind in ("text/html", "application/xhtml+xml"):
        return extract_html(body, provenance_for(url, retrieved_at, sha256, "html"))
    if kind in ("text/plain", "text/markdown"):
        return extract_text(body, provenance_for(url, retrieved_at, sha256, "text"))
    raise ExtractionError(
        f"unsupported content type {content_type!r}; supported: text/html, text/plain"
    )


def extract_text(body: bytes, provenance: dict) -> list:
    """Parse text/plain blocks ("id: ...", "text: ...", one block per outcome)."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExtractionError(f"artifact is not UTF-8 text: {error}") from None
    records = []
    for n, block in enumerate(
        [b for b in text.split("\n\n") if b.strip()], start=1
    ):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            fields[key.strip().lower()] = value.strip()
        outcome_id = fields.get("id", "")
        outcome_text = normalise(fields.get("text", ""))
        if not outcome_id:
            raise ExtractionError(f"text block {n} has no id")
        if not outcome_text:
            raise ExtractionError(f"text block {n} ({outcome_id}) has no text")
        records.append(
            {
                "outcome_id": outcome_id,
                "outcome_text": outcome_text,
                "source_ref": fields.get("source_ref", ""),
                "strand": fields.get("strand", ""),
                "sub_strand": fields.get("sub_strand", ""),
                "status": "candidate",
                "provenance": dict(provenance),
            }
        )
    if not records:
        raise ExtractionError("no outcome blocks found in text artifact")
    return records


class _OutcomeHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[dict] = []
        self._current: dict | None = None
        self._depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        seen = dict(attrs)
        outcome_id = seen.get("data-outcome-id", "").strip()
        if outcome_id and self._current is None:
            self._current = {
                "outcome_id": outcome_id,
                "source_ref": seen.get("data-source-ref", "").strip(),
                "strand": seen.get("data-strand", "").strip(),
                "sub_strand": seen.get("data-sub-strand", "").strip(),
            }
            self._depth = 1
            self._chunks = []
        elif self._current is not None:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        self._depth -= 1
        if self._depth <= 0:
            text = normalise("".join(self._chunks))
            if text:
                self.records.append(dict(self._current, outcome_text=text))
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._chunks.append(data)


def extract_html(body: bytes, provenance: dict) -> list:
    """Parse text/html elements carrying data-outcome-id attributes."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExtractionError(f"artifact is not UTF-8 HTML: {error}") from None
    parser = _OutcomeHTML()
    parser.feed(text)
    if not parser.records:
        raise ExtractionError("no data-outcome-id elements found in HTML artifact")
    return [
        {
            "outcome_id": record["outcome_id"],
            "outcome_text": record["outcome_text"],
            "source_ref": record["source_ref"],
            "strand": record["strand"],
            "sub_strand": record["sub_strand"],
            "status": "candidate",
            "provenance": dict(provenance),
        }
        for record in parser.records
    ]
