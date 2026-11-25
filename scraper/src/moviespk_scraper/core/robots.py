"""robots.txt parsing, per-path checks and evidence hashing (plan §10.2, P0-07).

This module does no network I/O. The HTTP client (P1-01) fetches robots.txt once per host
per run and builds a :class:`RobotsPolicy` with :meth:`RobotsPolicy.from_response`.

Rule matching implements RFC 9309 directly instead of using ``urllib.robotparser``,
whose behaviour differs between Python versions (3.12 applies the *first* matching rule;
RFC 9309 requires the *most specific* one). Compliance (OD3) must not depend on the
interpreter version.

* Groups: the groups whose ``User-agent`` equals our product token (case-insensitive) are
  merged; if there are none, the ``*`` groups are used; if there are none either, all is
  allowed.
* Rules: the longest matching ``Allow``/``Disallow`` pattern wins; on a tie ``Allow``
  wins. ``*`` matches any sequence and a trailing ``$`` anchors the end. An empty
  ``Disallow`` matches nothing. ``/robots.txt`` itself is always allowed.

RFC 9309 status handling:
* 2xx → parse the body, unless it is an HTML page (a soft 404, e.g. a redirect to an
  error page), which counts as a missing robots.txt → allow everything;
* 4xx → allow everything;
* 5xx or a network failure → disallow everything for this run (fail safe, run ``blocked``).
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit


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


@dataclass(frozen=True)
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[_Rule] = field(default_factory=list)
    crawl_delay: float | None = None


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


def _parse(body: str) -> list[_Group]:
    groups: list[_Group] = []
    current: _Group | None = None
    in_agent_lines = False
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not in_agent_lines:
                current = _Group()
                groups.append(current)
            current.agents.append(value.lower())
            in_agent_lines = True
            continue
        in_agent_lines = False
        if current is None:
            continue  # rules before any User-agent line are ignored
        if key in ("allow", "disallow"):
            if value:  # an empty Disallow (or Allow) matches nothing
                current.rules.append(_Rule(key == "allow", value, _compile(value)))
        elif key == "crawl-delay":
            with contextlib.suppress(ValueError):
                current.crawl_delay = float(value)
    return groups


def _looks_like_html(body: str) -> bool:
    """A robots.txt never starts with ``<``; an HTML page (error page, soft 404) does."""
    return body.lstrip("﻿ \t\r\n").startswith("<")


@dataclass
class RobotsPolicy:
    """Parsed robots.txt for one host, evaluated for one user agent."""

    user_agent: str
    status: int | None
    #: ``"parsed"``, ``"allow_all"`` (4xx) or ``"disallow_all"`` (5xx / network failure).
    mode: str
    body: str = ""
    _rules: list[_Rule] = field(default_factory=list, repr=False)
    _crawl_delay: float | None = field(default=None, repr=False)

    @classmethod
    def from_response(cls, user_agent: str, status: int | None, body: str = "") -> RobotsPolicy:
        """Build from an HTTP status (``None`` = network failure) and body."""
        if status is None or status >= 500:
            return cls(user_agent, status, "disallow_all")
        if 400 <= status < 500:
            return cls(user_agent, status, "allow_all")
        if 200 <= status < 300:
            if _looks_like_html(body):
                # Some sites redirect /robots.txt to an HTML error page served as 200.
                # That is a missing robots.txt, not an empty one: same as 4xx.
                return cls(user_agent, status, "allow_all")
            token = product_token(user_agent).lower()
            groups = _parse(body)
            selected = [g for g in groups if token in g.agents] or [
                g for g in groups if "*" in g.agents
            ]
            rules = [rule for g in selected for rule in g.rules]
            delay = next((g.crawl_delay for g in selected if g.crawl_delay is not None), None)
            return cls(user_agent, status, "parsed", body, rules, delay)
        # 3xx should have been followed by the client; treat anything else as unreachable.
        return cls(user_agent, status, "disallow_all")

    @property
    def blocked(self) -> bool:
        """True when robots.txt was unreachable (the run must report ``blocked``)."""
        return self.mode == "disallow_all"

    def can_fetch(self, url: str) -> bool:
        if self.mode == "allow_all":
            return True
        if self.mode == "disallow_all":
            return False
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if path == "/robots.txt":
            return True
        best: _Rule | None = None
        for rule in self._rules:
            if not rule.regex.match(path):
                continue
            if (
                best is None
                or len(rule.pattern) > len(best.pattern)
                or (len(rule.pattern) == len(best.pattern) and rule.allow)
            ):
                best = rule
        return best is None or best.allow

    def check(self, url: str) -> None:
        """Raise :class:`RobotsDisallowedError` if ``url`` may not be fetched."""
        if not self.can_fetch(url):
            raise RobotsDisallowedError(url, self.user_agent)

    def crawl_delay_ms(self) -> int | None:
        """``Crawl-delay`` for our group in milliseconds, if any."""
        return None if self._crawl_delay is None else int(self._crawl_delay * 1000)

    def effective_delay_ms(self, min_delay_ms: int) -> int:
        """``Crawl-delay`` is honoured when larger than ``min_delay_ms``."""
        delay = self.crawl_delay_ms()
        return max(min_delay_ms, delay) if delay is not None else min_delay_ms

    def body_sha256(self) -> str | None:
        return normalized_text_sha256(self.body) if self.mode == "parsed" else None
