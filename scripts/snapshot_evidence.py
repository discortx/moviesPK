#!/usr/bin/env python3
"""Record robots.txt / terms evidence for a cinema (plan P0-07).

    python scripts/snapshot_evidence.py --cinema cinepax-packages-mall \\
        --base-url https://web.cinepax.com --terms-url https://web.cinepax.com/terms \\
        --paths /api/sessions /api/films

Fetches only robots.txt and the terms page (the terms page only if robots allows it),
never the endpoints themselves. Prints per-path Allowed/Disallowed and a YAML ``evidence``
snippet for ``scraper/config/cinemas.yml``. Stores no copies of third-party pages:
hashes (normalized text, SHA-256) and verdicts only.

``--base-url`` may be omitted when the cinema already exists in cinemas.yml.
The User-Agent comes from ``SCRAPER_USER_AGENT`` (or ``--user-agent``).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
import yaml
from selectolax.lexbor import LexborHTMLParser

from moviespk_scraper.core.robots import RobotsPolicy, normalized_text_sha256, robots_url

ROOT = Path(__file__).resolve().parents[1]
CINEMAS_YML = ROOT / "scraper" / "config" / "cinemas.yml"
MIN_DELAY_S = 1.5
SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def html_text(html: str) -> str:
    """Visible text of an HTML page (scripts and styles removed)."""
    tree = LexborHTMLParser(html)
    for node in tree.css("script, style, noscript, template"):
        node.decompose()
    root = tree.body or tree.root
    return root.text(separator="\n") if root is not None else ""


def build_evidence(
    policy: RobotsPolicy,
    base_url: str,
    paths: list[str],
    terms_url: str | None,
    terms_sha256: str | None,
    checked_at: str,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "checked_at": checked_at,
        "robots_sha256": policy.body_sha256(),
        "terms_url": terms_url,
        "terms_sha256": terms_sha256,
        "endpoints": [
            {"path": p, "allowed": policy.can_fetch(urljoin(base_url, p))} for p in paths
        ],
    }
    return {"evidence": evidence}


def _base_url_from_config(cinema_id: str) -> str | None:
    if not CINEMAS_YML.exists():
        return None
    data = yaml.safe_load(CINEMAS_YML.read_text(encoding="utf-8")) or []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("id") == cinema_id:
            base = item.get("base_url")
            return base if isinstance(base, str) else None
    return None


def fetch_robots(client: httpx.Client, base_url: str, user_agent: str) -> RobotsPolicy:
    try:
        resp = client.get(robots_url(base_url))
    except httpx.HTTPError:
        return RobotsPolicy.from_response(user_agent, None)
    return RobotsPolicy.from_response(user_agent, resp.status_code, resp.text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record robots/terms evidence for a cinema.")
    parser.add_argument("--cinema", required=True, help="cinema id (slug)")
    parser.add_argument("--paths", nargs="+", required=True, help="endpoint paths to check")
    parser.add_argument("--base-url", help="https://host (default: from cinemas.yml)")
    parser.add_argument("--terms-url", help="terms / conditions page URL")
    parser.add_argument("--user-agent", default=os.environ.get("SCRAPER_USER_AGENT"))
    args = parser.parse_args(argv)

    if not args.user_agent:
        print("error: set SCRAPER_USER_AGENT or pass --user-agent", file=sys.stderr)
        return 2
    if not SLUG.fullmatch(args.cinema):
        print(
            f"error: cinema id {args.cinema!r} must be a slug: lowercase letters, digits and "
            "single hyphens (e.g. cinepax-world-trade-center)",
            file=sys.stderr,
        )
        return 2
    base_url = args.base_url or _base_url_from_config(args.cinema)
    if not base_url or urlsplit(base_url).scheme not in ("http", "https"):
        print("error: --base-url is required (cinema not found in cinemas.yml)", file=sys.stderr)
        return 2
    # A relative --terms-url (e.g. /terms) is resolved against the base URL.
    if args.terms_url:
        args.terms_url = urljoin(base_url, args.terms_url)

    headers = {"User-Agent": args.user_agent}
    with httpx.Client(headers=headers, timeout=TIMEOUT, follow_redirects=True) as client:
        policy = fetch_robots(client, base_url, args.user_agent)
        terms_sha: str | None = None
        if args.terms_url:
            if policy.can_fetch(args.terms_url):
                time.sleep(MIN_DELAY_S)
                resp = client.get(args.terms_url)
                resp.raise_for_status()
                terms_sha = normalized_text_sha256(html_text(resp.text))
            else:
                print("warning: terms page is disallowed by robots.txt; not fetched")

    status = "unreachable" if policy.status is None else str(policy.status)
    print(f"# robots.txt {robots_url(base_url)}: HTTP {status} ({policy.mode})")
    for path in args.paths:
        verdict = "Allowed" if policy.can_fetch(urljoin(base_url, path)) else "Disallowed"
        print(f"#   {verdict:<10} {path}")
    if policy.blocked:
        print("# robots.txt unreachable: treat every path as Disallowed for now")
    checked_at = datetime.now(UTC).date().isoformat()
    snippet = build_evidence(policy, base_url, args.paths, args.terms_url, terms_sha, checked_at)
    print(f"# YAML snippet for cinema '{args.cinema}':")
    print(yaml.safe_dump(snippet, sort_keys=False, allow_unicode=True), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
