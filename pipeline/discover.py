"""PDF-link discovery on an allowlisted page (stdlib only).

Given a fetched page, list the documents it points at: every <a href>
whose path ends in .pdf, resolved against the page URL, deduplicated —
plus any Google Drive file IDs embedded in the page (iframes, links, or
the same markup inside a WordPress page's JSON).
Discovery never fetches the documents itself and never leaves the
allowlist — use ./helper pipeline fetch on each PDF link, or
./helper pipeline drive-download on each Drive ID (each download
re-checks robots, rate limits, and provenance on its own).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value.strip())


def pdf_links(html: str, base_url: str) -> list[str]:
    """Absolute PDF URLs linked from the page, in order, without duplicates."""
    parser = _Links()
    parser.feed(html)
    found: list[str] = []
    for href in parser.hrefs:
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        if not parsed.path.lower().endswith(".pdf"):
            continue
        if absolute not in found:
            found.append(absolute)
    return found


# Google Drive embeds (iframes, links, or the same markup inside a JSON page):
# drive.google.com/file/d/<id>/... or .../open?id=<id> / .../uc?...&id=<id>.
# Real file IDs are long; the {10,} floor rejects short lookalikes.
_DRIVE_PATTERNS = (
    re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)"),
    re.compile(r"drive\.google\.com/[^\s\"'<>]*?[?&]id=([A-Za-z0-9_-]{10,})"),
)


def drive_files(text: str) -> list[str]:
    """Google Drive file IDs embedded in the text, in order, without duplicates."""
    text = text.replace("\\/", "/")  # WordPress JSON escapes forward slashes
    matches: list[tuple[int, str]] = []
    for pattern in _DRIVE_PATTERNS:
        for match in pattern.finditer(text):
            file_id = match.group(1)
            if len(file_id) >= 10:
                matches.append((match.start(), file_id))
    found: list[str] = []
    for _, file_id in sorted(matches):
        if file_id not in found:
            found.append(file_id)
    return found


def wp_page_url(site: str, slug: str) -> str:
    """WordPress REST lookup for a page slug (its JSON lists embedded files)."""
    return f"{site.rstrip('/')}/wp-json/wp/v2/pages?slug={slug}"
