#!/usr/bin/env python3
"""Capture an offline fixture for one cinema (plan P1-05).

    SCRAPER_USER_AGENT="MoviesPKBot/1.0 (+...)" \\
        python scripts/capture_fixture.py --cinema cinepax-packages-mall [--path /api/x ...]

* Fetches through the scraper's real HTTP client: robots.txt is enforced, requests are
  throttled, and a disallowed path is never fetched.
* Captures only the paths the adapter needs (``CAPTURE_PATHS`` below, or ``--path``) plus
  robots.txt, so ``--offline`` replays robots behaviour too.
* Strips cookies and tokens: only a few harmless headers are kept (never ``Set-Cookie``),
  token-like JSON keys and hidden HTML form tokens are replaced with ``REDACTED``, and
  token-like query parameters are refused.
* Writes ``scraper/tests/fixtures/<cinema-id>/<YYYY-MM-DD>/`` with ``manifest.json``
  (see ``moviespk_scraper/core/offline.py`` for the format) and one body file per URL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from moviespk_scraper.core.config import load_config
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.offline import MANIFEST
from moviespk_scraper.core.redact import KEPT_HEADERS, clean_body, url_has_secret_params

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "scraper" / "tests" / "fixtures"

#: Paths each adapter needs; ``{branch}`` is the cinema's branch id.
CAPTURE_PATHS: dict[str, list[str]] = {
    "cinepax": ["/api/cinemas", "/api/movies?cinemaId={branch}"],
    "vista": ["/browsing/Cinemas/Details/{branch}"],
}


def check_url_has_no_secrets(url: str) -> None:
    if url_has_secret_params(url):
        raise SystemExit("error: refusing to record a URL with a token-like query parameter")


class RecordingTransport(httpx.BaseTransport):
    """Pass requests to the network and remember every response."""

    def __init__(self) -> None:
        self.inner = httpx.HTTPTransport()
        self.recorded: list[tuple[str, httpx.Response]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        response.read()
        self.recorded.append((str(request.url), response))
        return response

    def close(self) -> None:
        self.inner.close()


def _slug(url: str, index: int, ext: str) -> str:
    parts = urlsplit(url)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", f"{parts.path}-{parts.query}").strip("-").lower()
    return f"{index:03d}-{stem[:60] or 'root'}{ext}"


def write_fixture(
    out: Path, cinema_id: str, recorded: list[tuple[str, httpx.Response]], now: datetime
) -> list[dict[str, Any]]:
    out.mkdir(parents=True, exist_ok=False)
    entries: list[dict[str, Any]] = []
    for index, (url, resp) in enumerate(recorded):
        content_type = resp.headers.get("content-type", "")
        body, ext = clean_body(content_type, resp.content)
        name = _slug(url, index, ext)
        (out / name).write_bytes(body)
        headers = {k: v for k, v in resp.headers.items() if k.lower() in KEPT_HEADERS}
        entries.append({"url": url, "status": resp.status_code, "headers": headers, "body": name})
    manifest = {
        "cinema_id": cinema_id,
        "captured_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "responses": entries,
    }
    (out / MANIFEST).write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture an offline fixture for one cinema.")
    parser.add_argument("--cinema", required=True)
    parser.add_argument("--path", action="append", help="path to capture (repeatable)")
    parser.add_argument("--out-root", type=Path, default=FIXTURES)
    parser.add_argument("--user-agent", default=os.environ.get("SCRAPER_USER_AGENT"))
    args = parser.parse_args(argv)
    if not args.user_agent:
        print("error: set SCRAPER_USER_AGENT or pass --user-agent", file=sys.stderr)
        return 2

    cinema = load_config().cinema(args.cinema)
    paths = args.path or CAPTURE_PATHS.get(cinema.adapter)
    if not paths:
        print(
            f"error: no capture paths for adapter {cinema.adapter!r}; use --path", file=sys.stderr
        )
        return 2
    urls = [urljoin(cinema.base_url, p.format(branch=cinema.branch or "")) for p in paths]
    for url in urls:
        check_url_has_no_secrets(url)

    now = datetime.now(UTC)
    out = args.out_root / cinema.id / now.date().isoformat()
    if out.exists():
        print(f"error: {out} already exists; delete it to re-capture", file=sys.stderr)
        return 2

    transport = RecordingTransport()
    with ScraperHttpClient(args.user_agent, transport=transport) as http:
        for url in urls:
            resp = http.get(
                url,
                min_delay_ms=cinema.min_delay_ms,
                robots_policy=cinema.robots_policy,
                permission_ref=cinema.permission_ref,
            )
            print(f"{resp.status_code}  {urlsplit(url).path}  {len(resp.content)} bytes")

    entries = write_fixture(out, cinema.id, transport.recorded, now)
    print(f"wrote {len(entries)} responses to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
