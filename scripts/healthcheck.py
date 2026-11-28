#!/usr/bin/env python3
"""Hourly health check (plan P2-08, §10.5, §18.1). Run by healthcheck.yml.

Two checks, each alerting through the scraper's GitHub-issue alerts:

* **site** — ``GET <site>/`` (200, HTML) and ``GET <api>/api/v1/health`` (200, database
  ``ok``), with ``Cache-Control: no-store``. Failing → ``[alert] site: down``.
* **images** — the first ``poster.key`` from ``/api/v1/movies?city=lahore&date=<today PKT>``
  as ``<image base>/img/<key>-w342.webp``; expects 200 ``image/webp``. Failing →
  ``[alert] images: down``. Cloudflare error 1027 is reported as "Workers Free daily limit
  reached, resets 00:00 UTC". No poster in today's list → skipped (not a failure).

"2 consecutive failures": a failing check is retried once after ``--retry-after`` seconds
(default 120) in the same run, and only a second failure alerts; a scheduled run keeps no
other state. A passing check closes its open issue.

Environment: ``SITE_URL``, ``API_URL``, ``IMAGE_BASE``; ``GITHUB_TOKEN`` and
``GITHUB_REPOSITORY`` for issues (without them the result is only printed).
Exit 1 when a check failed twice.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from moviespk_scraper.core.clock import pkt_date
from moviespk_scraper.services.alerts import Alert, Alerter, GitHubAlerter, PrintAlerter, run_url

DEFAULT_CITY = "lahore"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
USER_AGENT = "moviespk-healthcheck"
WORKERS_LIMIT = "Workers Free daily limit reached (error 1027), resets 00:00 UTC"


@dataclass(frozen=True)
class CheckResult:
    name: str  # "site" | "images"
    ok: bool
    detail: str
    skipped: bool = False


def _get(client: httpx.Client, url: str) -> httpx.Response:
    return client.get(url, headers={"Cache-Control": "no-store"})


def check_site(client: httpx.Client, site: str, api: str) -> CheckResult:
    try:
        home = _get(client, site.rstrip("/") + "/")
        if home.status_code != 200 or "text/html" not in home.headers.get("content-type", ""):
            return CheckResult("site", False, f"home page answered {home.status_code}")
        health = _get(client, api.rstrip("/") + "/api/v1/health")
        if health.status_code != 200:
            return CheckResult("site", False, f"/api/v1/health answered {health.status_code}")
        data = health.json().get("data", {})
        if data.get("status") != "ok" or data.get("db") != "ok":
            return CheckResult("site", False, f"/api/v1/health reports {data}")
    except (httpx.HTTPError, ValueError) as exc:
        return CheckResult("site", False, f"request failed ({type(exc).__name__})")
    return CheckResult("site", True, "home page 200; API health ok")


def first_poster_key(movies: Any) -> str | None:
    for movie in (movies or {}).get("data") or []:
        poster = movie.get("poster") if isinstance(movie, dict) else None
        if isinstance(poster, dict) and isinstance(poster.get("key"), str):
            return poster["key"]
    return None


def check_images(client: httpx.Client, api: str, image_base: str, today: str) -> CheckResult:
    try:
        listing = _get(client, f"{api.rstrip('/')}/api/v1/movies?city={DEFAULT_CITY}&date={today}")
        if listing.status_code != 200:
            # The site check covers the API; images cannot be judged this time.
            return CheckResult("images", True, f"movie list answered {listing.status_code}", True)
        key = first_poster_key(listing.json())
        if key is None:
            return CheckResult("images", True, "no poster in today's list; not checked", True)
        url = f"{image_base.rstrip('/')}/img/{key}-w342.webp"
        resp = client.get(url)
        if resp.status_code == 200 and resp.headers.get("content-type") == "image/webp":
            return CheckResult("images", True, f"poster 200 image/webp ({key}-w342)")
        if "1027" in resp.text[:2000]:
            return CheckResult("images", False, WORKERS_LIMIT)
        ctype = resp.headers.get("content-type", "-")
        return CheckResult("images", False, f"poster answered {resp.status_code} {ctype}")
    except (httpx.HTTPError, ValueError) as exc:
        return CheckResult("images", False, f"request failed ({type(exc).__name__})")


def run_checks(
    client: httpx.Client,
    site: str,
    api: str,
    image_base: str,
    *,
    alerter: Alerter | None,
    retry_after_s: float,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[CheckResult]:
    today = pkt_date(now()).isoformat()
    checks: dict[str, Callable[[], CheckResult]] = {
        "site": lambda: check_site(client, site, api),
        "images": lambda: check_images(client, api, image_base, today),
    }
    results = {name: check() for name, check in checks.items()}
    failing = [name for name, r in results.items() if not r.ok]
    if failing:
        print(f"failing: {', '.join(failing)}; checking again in {retry_after_s:.0f} s")
        sleep(retry_after_s)
        for name in failing:
            results[name] = checks[name]()

    for r in results.values():
        mark = "skip" if r.skipped else ("ok" if r.ok else "DOWN")
        print(f"[{mark}] {r.name}: {r.detail}")
        if alerter is None or r.skipped:
            continue
        if r.ok:
            alerter.resolve(r.name, now(), ("down",))
        else:
            alerter.raise_alert(
                Alert(
                    cinema_id=r.name,
                    type="down",
                    summary=f"{r.detail} (failed twice, {retry_after_s:.0f} s apart).",
                    state=f"down:{r.detail[:40].replace(' ', '_')}",
                    run_url=run_url(),
                ),
                now(),
            )
    return list(results.values())


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the site, the API and one poster.")
    parser.add_argument("--retry-after", type=float, default=120.0, help="seconds")
    parser.add_argument("--dry-run", action="store_true", help="print alerts, post nothing")
    args = parser.parse_args(argv)

    site = os.environ.get("SITE_URL", "").strip()
    api = os.environ.get("API_URL", "").strip()
    image_base = os.environ.get("IMAGE_BASE", "").strip()
    if not (site and api and image_base):
        print("error: set SITE_URL, API_URL and IMAGE_BASE", file=sys.stderr)
        return 2
    alerter: Alerter | None = PrintAlerter() if args.dry_run else GitHubAlerter.from_env()
    if alerter is None:
        print("note: issues not posted (GITHUB_TOKEN or GITHUB_REPOSITORY not set)")
    try:
        with httpx.Client(
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
            transport=transport,
        ) as client:
            results = run_checks(
                client, site, api, image_base, alerter=alerter, retry_after_s=args.retry_after
            )
    finally:
        if isinstance(alerter, GitHubAlerter):
            alerter.close()
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
