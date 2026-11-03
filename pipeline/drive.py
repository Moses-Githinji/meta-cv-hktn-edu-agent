"""Google Drive downloads for files an authority page embeds.

KICD publishes its curriculum designs as Google Drive embeds on official
pages, so discovery returns file IDs rather than PDF links. This module
downloads one file ID through the public export endpoint, still under the
source allowlist (drive.google.com is a "transport" host: it carries bytes
but never settles wording), robots.txt, and the per-domain rate limit.

Large files get a one-step confirmation round-trip (Drive's "download
anyway" token, with cookies kept across the two requests). Anything else
that comes back as a page — sign-in walls, takedowns — fails closed with
instructions to download the file by hand. The transport is injectable so
tests run offline, exactly like pipeline.fetch.
"""

from __future__ import annotations

import http.cookiejar
import re
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import urlparse

from .fetch import (
    USER_AGENT,
    DEFAULT_TIMEOUT,
    FetchError,
    RateLimiter,
    Response,
    robots_allows,
)
from .sources import SourceError, check

DEFAULT_MAX_BYTES = 50 * 1024 * 1024

_ID_RE = re.compile(r"[A-Za-z0-9_-]{10,}")
_CONFIRM_RE = re.compile(r"""confirm(?:=|%3D|\\?"\s*:\s*\\?")([A-Za-z0-9_-]+)""")

_JAR = http.cookiejar.CookieJar()


class DriveError(FetchError):
    """A Drive download refused or failed. Safe to show and to log."""


def export_url(file_id: str) -> str:
    """The public download URL for a Drive file ID."""
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def file_url(file_id: str) -> str:
    """The human preview URL for a Drive file ID (for manual fallback)."""
    return f"https://drive.google.com/file/d/{file_id}/view"


def confirm_token(page_text: str) -> str | None:
    """Drive's "download anyway" token, when the page offers one."""
    match = _CONFIRM_RE.search(page_text)
    return match.group(1) if match else None


def cookie_transport(url: str, headers: dict, timeout: int) -> Response:
    """The live transport: one GET that keeps cookies for the confirm step."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(_JAR),
        urllib.request.HTTPRedirectHandler(),
    )
    opener.addheaders = [("User-Agent", headers.get("User-Agent", USER_AGENT))]
    try:
        with opener.open(url, timeout=timeout) as reply:
            return Response(
                status=getattr(reply, "status", 200),
                headers=dict(reply.headers.items()),
                body=reply.read(),
            )
    except urllib.error.HTTPError as error:
        return Response(
            status=error.code, headers=dict(error.headers.items()), body=b""
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DriveError(f"GET {url} failed: {error}") from None


def _is_page(content_type: str, body: bytes) -> bool:
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind in ("text/html", "application/xhtml+xml"):
        return True
    return not kind and body.lstrip().startswith(b"<")


def _one_get(
    url: str,
    transport: Callable[[str, dict, int], Response],
    timeout: int,
    max_bytes: int,
    rate_limiter: RateLimiter | None,
) -> tuple[bytes, str]:
    if rate_limiter is not None:
        rate_limiter.wait(url)
    reply = transport(url, {"User-Agent": USER_AGENT}, timeout)
    if reply.status != 200:
        raise DriveError(f"GET {url} returned HTTP {reply.status}")
    if len(reply.body) > max_bytes:
        raise DriveError(f"GET {url} exceeds the {max_bytes}-byte cap")
    content_type = str(reply.headers.get("Content-Type", "")).split(";")[0].strip()
    return reply.body, content_type


def download(
    file_id: str,
    transport: Callable[[str, dict, int], Response] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    rate_limiter: RateLimiter | None = None,
    robots_cache: dict | None = None,
    robots_exception: bool = False,
) -> tuple[bytes, str]:
    """Download one Drive file ID: (body, content_type).

    Fails closed (DriveError) on bad IDs, robots refusals, and anything
    that stays a web page after the confirmation round-trip. `robots_exception`
    skips only the robots check, only for the /uc download endpoint, and
    only when the operator explicitly passes it (the CLI flag records the
    choice on the stored artifact for audit).
    """
    if not file_id or not _ID_RE.fullmatch(file_id):
        raise DriveError(f"not a Google Drive file ID: {file_id!r}")
    url = export_url(file_id)
    if urlparse(url).path != "/uc":
        raise DriveError(f"refusing non-download endpoint {url!r}")
    try:
        check(url)
    except SourceError as error:
        raise DriveError(str(error)) from None
    transport = transport or cookie_transport
    if not robots_exception and not robots_allows(url, transport, timeout, robots_cache):
        raise DriveError(f"robots.txt disallows fetching {url}")
    body, content_type = _one_get(url, transport, timeout, max_bytes, rate_limiter)
    if not _is_page(content_type, body):
        return body, content_type
    page = body.decode("utf-8", errors="replace")
    token = confirm_token(page)
    if token is None:
        if "permission to download this file" in page:
            raise DriveError(
                f"Google Drive refuses: the owner disabled downloading for "
                f"{file_url(file_id)} (view-only share). Only the owner or an "
                f"editor can download it; contact KICD or transcribe from the "
                f"viewable preview."
            )
        raise DriveError(
            f"Google Drive answered with a page, not the file (no download "
            f"confirmation offered). Download it manually from {file_url(file_id)}"
        )
    body, content_type = _one_get(
        f"{url}&confirm={token}", transport, timeout, max_bytes, rate_limiter
    )
    if _is_page(content_type, body):
        raise DriveError(
            f"Google Drive still answers with a page after confirmation. "
            f"Download it manually from {file_url(file_id)}"
        )
    return body, content_type


__all__ = ["DriveError", "confirm_token", "download", "export_url", "file_url"]
