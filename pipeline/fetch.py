"""The fetcher: one polite, allowlisted GET per call.

Every fetch passes the source allowlist, robots.txt, and a per-domain rate
limit, and identifies the crawler. Failures raise FetchError (never partial
content). The transport is injectable so tests run offline:

    fetch_url(url, transport=FakeTransport(...))
    fetch_url(url)  # live: urllib over the network
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .sources import SourceError, check

USER_AGENT = (
    "meta-cv-hktn-edu-agent-curriculum-bot/0.1 "
    "(non-commercial prototype; respects robots.txt)"
)
CRAWLER_NAME = "meta-cv-hktn-edu-agent-curriculum-bot"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MIN_INTERVAL = 5.0


class FetchError(ValueError):
    """A fetch refused or failed. Safe to show and to log as an alert."""


@dataclass
class Response:
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""


def urllib_transport(
    url: str, headers: dict, timeout: int
) -> Response:
    """The live transport: one GET over urllib (stdlib)."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return Response(
                status=reply.status,
                headers=dict(reply.headers.items()),
                body=reply.read(),
            )
    except urllib.error.HTTPError as error:
        return Response(
            status=error.code, headers=dict(error.headers.items()), body=b""
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FetchError(f"GET {url} failed: {error}") from None


class RateLimiter:
    """At most one fetch per domain per min_interval seconds.

    State is file-backed (var_dir/rate.json) so separate refresh processes
    share it; best effort when the file is missing or corrupt.
    """

    def __init__(
        self,
        var_dir: Path | None = None,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.var_dir = Path(var_dir) if var_dir else None
        self.min_interval = min_interval
        self.now = now or time.time
        self.sleep = sleep or time.sleep
        self._last: dict[str, float] = {}
        if self.var_dir is not None:
            try:
                import json

                raw = json.loads((self.var_dir / "rate.json").read_text())
                self._last = {str(k): float(v) for k, v in raw.items()}
            except (OSError, ValueError):
                self._last = {}

    def wait(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        due = self._last.get(host, 0.0) + self.min_interval
        delay = due - self.now()
        if delay > 0:
            self.sleep(delay)
        self._last[host] = self.now()
        if self.var_dir is not None:
            try:
                import json

                self.var_dir.mkdir(parents=True, exist_ok=True)
                (self.var_dir / "rate.json").write_text(json.dumps(self._last))
            except OSError:
                pass


def robots_allows(
    url: str,
    transport: Callable[[str, dict, int], Response],
    timeout: int = DEFAULT_TIMEOUT,
    cache: dict | None = None,
) -> bool:
    """Whether robots.txt allows our crawler to fetch `url`.

    No robots file (404) means allowed. Any transport failure fails closed:
    without the rules, we do not fetch.
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if cache is not None and origin in cache:
        rules = cache[origin]
    else:
        try:
            reply = transport(
                f"{origin}/robots.txt", {"User-Agent": USER_AGENT}, timeout
            )
        except FetchError as error:
            raise FetchError(f"robots.txt for {origin} unreachable: {error}") from None
        if reply.status == 404:
            rules = ([], [])
        elif reply.status != 200:
            raise FetchError(
                f"robots.txt for {origin} returned HTTP {reply.status}: refusing"
            )
        else:
            rules = parse_robots(reply.body.decode("utf-8", "replace"))
        if cache is not None:
            cache[origin] = rules
    path = parsed.path or "/"
    allows, disallows = rules
    allow_hit = max(
        (len(prefix) for prefix in allows if path.startswith(prefix)), default=0
    )
    deny_hit = max(
        (len(prefix) for prefix in disallows if path.startswith(prefix)), default=0
    )
    return allow_hit >= deny_hit  # longest match wins; Allow wins ties


def parse_robots(text: str) -> tuple[list, list]:
    """(Allow, Disallow) prefixes applying to our crawler.

    The most specific group wins: our own User-agent block when it has any
    rules, else the "*" block. (Crawl-delay is ignored: our own throttle is
    stricter than any delay seen so far.)
    """
    generic: tuple[list, list] = ([], [])
    specific: tuple[list, list] = ([], [])
    in_scope: tuple[list, list] | None = None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            agent = value.lower()
            if agent == CRAWLER_NAME.lower():
                in_scope = specific
            elif agent == "*":
                in_scope = generic
            else:
                in_scope = None
        elif field == "allow" and in_scope is not None and value:
            in_scope[0].append(value)
        elif field == "disallow" and in_scope is not None and value:
            in_scope[1].append(value)
    if specific[0] or specific[1]:
        return specific
    return generic


def fetch_url(
    url: str,
    transport: Callable[[str, dict, int], Response] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    rate_limiter: RateLimiter | None = None,
    robots_cache: dict | None = None,
) -> tuple[bytes, str]:
    """Fetch one URL: (body, content_type). Refusals raise FetchError/SourceError."""
    try:
        check(url)
    except SourceError as error:
        raise FetchError(str(error)) from None
    transport = transport or urllib_transport
    if not robots_allows(url, transport, timeout, robots_cache):
        raise FetchError(f"robots.txt disallows fetching {url}")
    if rate_limiter is not None:
        rate_limiter.wait(url)
    reply = transport(url, {"User-Agent": USER_AGENT}, timeout)
    if reply.status != 200:
        raise FetchError(f"GET {url} returned HTTP {reply.status}")
    if len(reply.body) > max_bytes:
        raise FetchError(f"GET {url} exceeds the {max_bytes}-byte cap")
    content_type = str(reply.headers.get("Content-Type", "")).split(";")[0].strip()
    return reply.body, content_type
