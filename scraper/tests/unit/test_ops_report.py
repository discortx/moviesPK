"""P2-09: scripts/ops_report.py against a fake GitHub API."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops_report.py"
T0 = datetime(2026, 11, 28, 16, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def ops() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ops_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ops_report"] = module
    spec.loader.exec_module(module)
    return module


def run(n: int, hours: float, event: str = "schedule", conclusion: str = "success") -> dict:
    when = (T0 + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"run_number": n, "event": event, "conclusion": conclusion, "created_at": when,
            "html_url": f"https://github.test/runs/{n}"}  # fmt: skip


def fake(runs: dict[str, list[dict]], issues: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/actions/workflows/" in path:
            name = path.split("/actions/workflows/")[1].split(".yml")[0]
            return httpx.Response(200, json={"workflow_runs": runs.get(name, [])})
        if path.endswith("/issues"):
            return httpx.Response(200, json=issues)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_longest_gap_counts_the_open_ends(ops: ModuleType) -> None:
    until = T0 + timedelta(hours=24)
    gap, start, end = ops.longest_gap([T0 + timedelta(hours=h) for h in (1, 3, 10)], T0, until)
    assert gap == timedelta(hours=14) and start == T0 + timedelta(hours=10) and end == until
    assert ops.longest_gap([], T0, until)[0] == timedelta(hours=24)


def test_report_lists_failures_freshness_and_issues(
    ops: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = {
        "scrape-full": [run(20, 1), run(21, 2), run(22, 5, conclusion="failure"), run(23, 20)],
        "scrape-canary": [run(5, 12)],
        "healthcheck": [run(3, 0.5, event="workflow_dispatch")],
    }
    issues = [
        {"number": 90, "title": "[alert] cinepax-ocean-mall: drift", "state": "closed",
         "created_at": "2026-11-29T01:00:00Z", "closed_at": "2026-11-29T03:00:00Z"},
        {"number": 1, "title": "old", "state": "open", "created_at": "2026-11-01T00:00:00Z",
         "closed_at": None},
        {"number": 91, "title": "a PR", "pull_request": {}, "state": "open",
         "created_at": "2026-11-29T01:00:00Z"},
    ]  # fmt: skip
    code = ops.main(
        ["--since", "2026-11-28T16:30Z", "--until", "2026-11-29T16:30Z"],
        transport=fake(runs, issues),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "| `scrape-full` | 4 | 4 | 3 | 1 |" in out
    assert "| `healthcheck` | 1 | 0 | 1 | 0 |" in out
    assert "longest gap without a successful run 18.0 h" in out and "over nominal 12 h" in out
    assert "`scrape-full` #22 (schedule, 2026-11-28 21:30): failure" in out
    assert "#90 [alert] cinepax-ocean-mall: drift (closed)" in out
    assert "old" not in out and "a PR" not in out
