"""robots.txt parsing, per-path checks and evidence hashing (plan §10.2, P0-07).

This module does no network I/O. The HTTP client (P1-01) fetches robots.txt once per host
per run and builds a :class:`RobotsPolicy` with :meth:`RobotsPolicy.from_response`.

RFC 9309 status handling:
* 2xx → parse the body;
* 4xx → allow everything;
* 5xx or a network failure → disallow everything for this run (fail safe, run ``blocked``).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser


class RobotsDisallowedError(Exception):
    """Raised before any request to a path that robots.txt disallows."""

    def __init__(self, url: str, user_agent: str) -> None:
        super().__init__(f"robots.txt disallows {urlsplit(url).path or '/'} for {user_agent}")
        self.url = url
        self.user_agent = user_agent


def robots_url(url: str) -> str:
    """The robots.txt URL for the scheme and host of ``url``."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"absolute URL required: {url!r}")
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def product_token(user_agent: str) -> str:
    """Product token used to match robots groups (``MoviesPKBot/1.0 (...)`` → ``MoviesPKBot``)."""
    token = user_agent.strip().split("/", 1)[0].split(" ", 1)[0]
    if not token:
        raise ValueError("user agent must not be empty")
    return token


_WS = re.compile(r"\s+")


def normalized_text_sha256(text: str) -> str:
    """SHA-256 of text after NFKC, line-ending unification, per-line trim, whitespace
    collapse and removal of blank lines. Stable across cosmetic whitespace changes."""
    norm = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = (_WS.sub(" ", line).strip() for line in norm.split("\n"))
    canonical = "\n".join(line for line in lines if line)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class RobotsPolicy:
    """Parsed robots.txt for one host, evaluated for one user agent."""

    user_agent: str
    status: int | None
    #: ``"parsed"``, ``"allow_all"`` (4xx) or ``"disallow_all"`` (5xx / network failure).
    mode: str
    body: str = ""
    _parser: RobotFileParser | None = field(default=None, repr=False)

    @classmethod
    def from_response(cls, user_agent: str, status: int | None, body: str = "") -> RobotsPolicy:
        """Build from an HTTP status (``None`` = network failure) and body."""
        if status is None or status >= 500:
            return cls(user_agent, status, "disallow_all")
        if 400 <= status < 500:
            return cls(user_agent, status, "allow_all")
        if 200 <= status < 300:
            parser = RobotFileParser()
            parser.parse(body.splitlines())
            return cls(user_agent, status, "parsed", body, parser)
        # 3xx should have been followed by the client; treat anything else as unreachable.
        return cls(user_agent, status, "disallow_all")

    @property
    def blocked(self) -> bool:
        """True when robots.txt was unreachable (the run must report ``blocked``)."""
        return self.mode == "disallow_all"

    def can_fetch(self, url: str) -> bool:
        if self.mode == "allow_all":
            return True
        if self.mode == "disallow_all" or self._parser is None:
            return False
        return self._parser.can_fetch(product_token(self.user_agent), url)

    def check(self, url: str) -> None:
        """Raise :class:`RobotsDisallowedError` if ``url`` may not be fetched."""
        if not self.can_fetch(url):
            raise RobotsDisallowedError(url, self.user_agent)

    def crawl_delay_ms(self) -> int | None:
        """``Crawl-delay`` for our group in milliseconds, if any."""
        if self._parser is None:
            return None
        delay = self._parser.crawl_delay(product_token(self.user_agent))
        return None if delay is None else int(float(delay) * 1000)

    def effective_delay_ms(self, min_delay_ms: int) -> int:
        """``Crawl-delay`` is honoured when larger than ``min_delay_ms``."""
        delay = self.crawl_delay_ms()
        return max(min_delay_ms, delay) if delay is not None else min_delay_ms

    def body_sha256(self) -> str | None:
        return normalized_text_sha256(self.body) if self.mode == "parsed" else None
