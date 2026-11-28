#!/usr/bin/env python3
"""Operations report for an unattended window (plan P2-09, gate G2).

    python scripts/ops_report.py --since 2026-11-28T16:30Z [--until ...] [--repo owner/name]

Reads the public GitHub API (``GITHUB_TOKEN`` optional, for a higher rate limit) and
prints Markdown for the runbook's observation log:

* per scheduled workflow: runs in the window by trigger and conclusion, and every run that
  was not ``success`` (each must be fixed or explained);
* ``scrape-full`` freshness: the longest gap between successful runs, against the targets
  (nominal 12 h, alert 18 h; plan §3.2), including the gap still open at the end;
* issues opened or closed in the window.

Writes nothing.
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

API = "https://api.github.com"
WORKFLOWS = ("scrape-full", "scrape-canary", "healthcheck", "export", "keepalive")
NOMINAL_GAP = timedelta(hours=12)
ALERT_GAP = timedelta(hours=18)


def parse_time(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class Run:
    workflow: str
    number: int
    event: str
    conclusion: str | None
    created: datetime
    url: str


def fetch_runs(client: httpx.Client, workflow: str, since: datetime, until: datetime) -> list[Run]:
    runs: list[Run] = []
    for page in range(1, 20):
        resp = client.get(
            f"/actions/workflows/{workflow}.yml/runs",
            params={"per_page": 100, "page": page, "created": f">={since:%Y-%m-%dT%H:%M:%SZ}"},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        batch = resp.json().get("workflow_runs", [])
        for r in batch:
            created = parse_time(r["created_at"])
            if since <= created < until:
                runs.append(
                    Run(
                        workflow,
                        r["run_number"],
                        r["event"],
                        r.get("conclusion"),
                        created,
                        r["html_url"],
                    )
                )
        if len(batch) < 100:
            break
    return sorted(runs, key=lambda r: r.created)


def fetch_issues(client: httpx.Client, since: datetime, until: datetime) -> list[dict[str, Any]]:
    resp = client.get(
        "/issues",
        params={"state": "all", "since": f"{since:%Y-%m-%dT%H:%M:%SZ}", "per_page": 100},
    )
    resp.raise_for_status()
    out = []
    for issue in resp.json():
        if "pull_request" in issue:
            continue
        opened = parse_time(issue["created_at"])
        closed = parse_time(issue["closed_at"]) if issue.get("closed_at") else None
        if since <= opened < until or (closed is not None and since <= closed < until):
            out.append(issue)
    return sorted(out, key=lambda i: i["number"])


def longest_gap(
    successes: list[datetime], since: datetime, until: datetime
) -> tuple[timedelta, datetime, datetime]:
    """The longest stretch without a successful run, counting from the window's start
    to the first success and from the last success to the end."""
    points = [since, *sorted(successes), until]
    best = (timedelta(0), since, since)
    for a, b in itertools.pairwise(points):
        if b - a > best[0]:
            best = (b - a, a, b)
    return best


def report(client: httpx.Client, since: datetime, until: datetime) -> str:
    lines = [f"### Window {iso(since)} → {iso(until)} UTC", ""]
    lines += ["| Workflow | Runs | Scheduled | Success | Not success |", "|---|---|---|---|---|"]
    problems: list[Run] = []
    full: list[Run] = []
    for wf in WORKFLOWS:
        runs = fetch_runs(client, wf, since, until)
        bad = [r for r in runs if r.conclusion not in ("success", None)]
        problems += bad
        if wf == "scrape-full":
            full = runs
        scheduled = sum(r.event == "schedule" for r in runs)
        ok = sum(r.conclusion == "success" for r in runs)
        lines.append(f"| `{wf}` | {len(runs)} | {scheduled} | {ok} | {len(bad)} |")

    gap, start, end = longest_gap(
        [r.created for r in full if r.conclusion == "success"], since, until
    )
    hours = gap.total_seconds() / 3600
    verdict = (
        "ok" if gap <= NOMINAL_GAP else ("over nominal 12 h" if gap <= ALERT_GAP else "OVER 18 h")
    )
    lines += [
        "",
        f"**scrape-full freshness:** longest gap without a successful run {hours:.1f} h "
        f"({iso(start)} → {iso(end)}): {verdict}.",
        "",
        "**Runs to fix or explain:**" if problems else "**Runs to fix or explain:** none.",
    ]
    for r in problems:
        lines.append(
            f"- `{r.workflow}` #{r.number} ({r.event}, {iso(r.created)}): {r.conclusion} — {r.url}"
        )
    issues = fetch_issues(client, since, until)
    lines += ["", "**Issues opened or closed in the window:**" if issues else "**Issues:** none."]
    for i in issues:
        lines.append(f"- #{i['number']} {i['title']} ({i['state']})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report on an unattended operations window.")
    parser.add_argument("--since", required=True, help="window start, ISO time (UTC)")
    parser.add_argument("--until", help="window end (default: now)")
    parser.add_argument("--repo", default="discortx/moviesPK")
    args = parser.parse_args(argv)
    since = parse_time(args.since)
    until = parse_time(args.until) if args.until else datetime.now(UTC)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "moviespk-ops-report"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(
        base_url=f"{API}/repos/{args.repo}", headers=headers, timeout=20.0, transport=transport
    ) as client:
        try:
            sys.stdout.write(report(client, since, until))
        except httpx.HTTPError as exc:
            print(f"error: GitHub API ({type(exc).__name__})", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
