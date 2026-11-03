"""The source allowlist: the only hosts the fetcher may touch.

Kinds: "authority" (citable for outcome wording: KICD and the Ministry
ecosystem), "finding_aid" (mirrors that help locate official copies but
never settle wording), and "transport" (carries official bytes without
settling wording: the authority is the embedding page, recorded as the
artifact's source_page). Transcribed text must come from an authority; the
publish gates enforce that. Seeds are starting points for a refresh, drawn
from the URLs already on file in docs/ and curriculum/TRANSCRIBE.md.
"""

from __future__ import annotations

from urllib.parse import urlparse

SOURCES = [
    {
        "host": "kicd.ac.ke",
        "kind": "authority",
        "notes": "KICD designs portal; the only citable source for outcome text.",
        "seeds": [
            "https://kicd.ac.ke/cbc-materials/curriculum-designs/grade-seven-designs/",
        ],
    },
    {
        "host": "kec.ac.ke",
        "kind": "authority",
        "notes": "Kenya Education Cloud.",
        "seeds": ["https://kec.ac.ke/"],
    },
    {
        "host": "oer.kec.ac.ke",
        "kind": "authority",
        "notes": "Kenya Education Cloud OER portal.",
        "seeds": ["https://oer.kec.ac.ke/"],
    },
    {
        "host": "education.go.ke",
        "kind": "authority",
        "notes": "Ministry of Education (term circulars).",
        "seeds": ["https://www.education.go.ke/"],
    },
    {
        "host": "drive.google.com",
        "kind": "transport",
        "notes": "KICD's file host: official embeds download from here, "
        "but the authority stays the embedding KICD page (source_page).",
        "seeds": [],
    },
    {
        "host": "freeexams.co.ke",
        "kind": "finding_aid",
        "notes": "Mirror; finding aid only, never citable.",
        "seeds": ["https://freeexams.co.ke/"],
    },
    {
        "host": "cbcelimu.com",
        "kind": "finding_aid",
        "notes": "Mirror; finding aid only, never citable.",
        "seeds": ["https://cbcelimu.com/"],
    },
]

_BY_HOST = {s["host"]: s for s in SOURCES}


class SourceError(ValueError):
    """A URL the allowlist refuses."""


def check(url: str) -> dict:
    """The allowlist entry for a URL, or raise SourceError.

    Only http(s) URLs on listed hosts (exact or subdomain) are allowed.
    """
    try:
        parsed = urlparse(url)
    except ValueError as error:
        raise SourceError(f"bad URL {url!r}: {error}") from None
    if parsed.scheme not in ("http", "https"):
        raise SourceError(f"URL scheme must be http(s): {url!r}")
    host = (parsed.hostname or "").lower()
    labels = host.split(".")
    for i in range(len(labels)):
        entry = _BY_HOST.get(".".join(labels[i:]))
        if entry is not None:
            return entry
    raise SourceError(
        f"host {host!r} is not allowlisted; "
        f"allowed: {', '.join(sorted(_BY_HOST))}"
    )


def is_authority(url: str) -> bool:
    """Whether outcome wording may be cited from this URL (authorities only)."""
    return check(url)["kind"] == "authority"


def seeds(kind: str | None = None) -> list:
    """Seed URLs for a refresh, optionally filtered by kind."""
    return [
        url
        for source in SOURCES
        if kind is None or source["kind"] == kind
        for url in source["seeds"]
    ]
