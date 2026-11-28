#!/usr/bin/env python3
"""Monthly keepalive (plan P2-06, architecture §10.5, §18.2). Run by keepalive.yml.

GitHub disables the scheduled workflows of a public repository after 60 days without
"repository activity", which GitHub does not define (docs/free-tier-verification.md
P5-5). So this does not rely on any definition:

1. ``PUT /repos/{repo}/actions/workflows/{file}/enable`` for every workflow in
   ``.github/workflows`` that has an ``on.schedule`` (idempotent; a disabled one comes back).
2. Opens the month's maintenance issue ``[maintenance] YYYY-MM`` (label ``maintenance``),
   assigned to the owner, with the §18.2 monthly checklist; when it is already open, adds
   a comment with this run's result instead.
3. The owner then makes the monthly **human** maintenance commit and closes the issue.
   This script never commits (bot commits are not documented as activity, and
   ``GITHUB_TOKEN`` pushes trigger no workflows).

Uses ``GITHUB_TOKEN`` (``actions: write``, ``issues: write``), ``GITHUB_REPOSITORY`` and
``GITHUB_REPOSITORY_OWNER``. Exit 1 when a workflow could not be enabled.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
API = "https://api.github.com"

CHECKLIST = """\
Monthly routine (plan §18.2). Tick each item, then close this issue.

- [ ] **Human maintenance commit** (Dependabot merges, a fixture refresh, or a line in the
      maintenance log of `docs/runbook.md`). Keeps the repository active (60-day rule).
- [ ] Dependabot PRs reviewed and merged or closed
- [ ] Fixtures refreshed for adapters that changed (`scripts/capture_fixture.py`)
- [ ] Keepalive ran: every scheduled workflow is `active` (table below)
- [ ] **Z1:** a payment method only on Cloudflare; only the R2 subscription; Workers plan
      Free; no zone; no other product; nothing billable on GitHub, Atlas, Vercel or TMDB
- [ ] **R2 usage record:** storage, Class A and Class B for the month appended to
      `docs/capacity.md` (actual vs §7.4.2); any charge on the invoice noted; buckets private
- [ ] Worker request graph for the month (peak day vs 100,000/day)
- [ ] Provider notices read (GitHub, Atlas, Vercel, Cloudflare, TMDB)
- [ ] Open `[alert]` and `[digest]` issues handled
"""


@dataclass(frozen=True)
class EnableResult:
    file: str
    status: int | None
    state: str | None  # the workflow's state after the call
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.state == "active"


def scheduled_workflows(directory: Path = WORKFLOWS) -> list[str]:
    """File names of the workflows with an ``on.schedule`` trigger."""
    found = []
    for path in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # PyYAML (YAML 1.1) reads the key ``on`` as the boolean True.
        triggers = data.get("on", data.get(True)) if isinstance(data, dict) else None
        if isinstance(triggers, dict) and triggers.get("schedule"):
            found.append(path.name)
    return found


def enable_all(client: httpx.Client, files: list[str]) -> list[EnableResult]:
    results = []
    for file in files:
        try:
            resp = client.put(f"/actions/workflows/{file}/enable")
            if resp.status_code != 204:
                results.append(
                    EnableResult(file, resp.status_code, None, f"HTTP {resp.status_code}")
                )
                continue
            state = client.get(f"/actions/workflows/{file}").json().get("state")
            results.append(EnableResult(file, resp.status_code, state))
        except (httpx.HTTPError, ValueError) as exc:
            results.append(EnableResult(file, None, None, type(exc).__name__))
    return results


def results_table(results: list[EnableResult]) -> str:
    lines = ["| Workflow | Enable call | State after |", "|---|---|---|"]
    for r in results:
        call = f"HTTP {r.status}" if r.status else (r.error or "-")
        lines.append(f"| `{r.file}` | {call} | {r.state or r.error or '-'} |")
    return "\n".join(lines)


def run_link() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo, run = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return f"{server}/{repo}/actions/runs/{run}" if repo and run else "(local run)"


def maintenance_issue(
    client: httpx.Client, month: str, owner: str | None, results: list[EnableResult]
) -> tuple[str, int]:
    """("created" | "commented", issue number)."""
    title = f"[maintenance] {month}"
    report = f"Keepalive run: {run_link()}\n\n{results_table(results)}\n"
    open_issues = client.get(
        "/issues", params={"state": "open", "labels": "maintenance", "per_page": 100}
    ).json()
    existing = next((i for i in open_issues if i.get("title") == title), None)
    if existing is not None:
        client.post(
            f"/issues/{existing['number']}/comments", json={"body": report}
        ).raise_for_status()
        return "commented", int(existing["number"])
    payload: dict[str, Any] = {
        "title": title,
        "body": f"{CHECKLIST}\n{report}",
        "labels": ["maintenance"],
    }
    if owner:
        payload["assignees"] = [owner]
    resp = client.post("/issues", json=payload)
    resp.raise_for_status()
    return "created", int(resp.json()["number"])


def make_client(
    token: str, repository: str, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    return httpx.Client(
        base_url=f"{API}/repos/{repository}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "moviespk-keepalive",
        },
        timeout=15.0,
        transport=transport,
    )


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-enable scheduled workflows; open the maintenance issue."
    )
    parser.add_argument("--dry-run", action="store_true", help="list the scheduled workflows only")
    args = parser.parse_args(argv)

    files = scheduled_workflows()
    print(f"scheduled workflows: {', '.join(files)}")
    if args.dry_run:
        return 0
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        print("error: set GITHUB_TOKEN and GITHUB_REPOSITORY", file=sys.stderr)
        return 2
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip() or repository.split("/")[0]
    month = datetime.now(UTC).strftime("%Y-%m")
    with make_client(token, repository, transport) as client:
        results = enable_all(client, files)
        print(results_table(results))
        try:
            action, number = maintenance_issue(client, month, owner, results)
            print(f"maintenance issue #{number}: {action}")
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            print(f"error: maintenance issue not posted ({type(exc).__name__})", file=sys.stderr)
            return 1
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
