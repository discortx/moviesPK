"""P2-06: scripts/keepalive.py against a fake GitHub API."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "keepalive.py"


@pytest.fixture(scope="module")
def keepalive() -> ModuleType:
    spec = importlib.util.spec_from_file_location("keepalive", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["keepalive"] = module
    spec.loader.exec_module(module)
    return module


class FakeGitHub:
    def __init__(self, disabled: set[str] | None = None, refuse: set[str] | None = None) -> None:
        self.state = {f: "disabled_inactivity" for f in (disabled or set())}
        self.refuse = refuse or set()
        self.enabled: list[str] = []
        self.issues: list[dict[str, Any]] = []
        self.comments: list[tuple[int, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/repos/discortx/moviesPK")
        if path.startswith("/actions/workflows/"):
            file = path.split("/")[3]
            if request.method == "PUT" and path.endswith("/enable"):
                if file in self.refuse:
                    return httpx.Response(403, json={"message": "Resource not accessible"})
                self.enabled.append(file)
                self.state[file] = "active"
                return httpx.Response(204)
            return httpx.Response(200, json={"path": file, "state": self.state.get(file, "active")})
        if path == "/issues" and request.method == "GET":
            assert request.url.params["labels"] == "maintenance"
            return httpx.Response(200, json=[i for i in self.issues if i["state"] == "open"])
        if path == "/issues" and request.method == "POST":
            data = json.loads(request.content)
            issue = {"number": len(self.issues) + 1, "state": "open", **data}
            self.issues.append(issue)
            return httpx.Response(201, json=issue)
        if path.endswith("/comments") and request.method == "POST":
            self.comments.append((int(path.split("/")[2]), json.loads(request.content)["body"]))
            return httpx.Response(201, json={})
        return httpx.Response(404)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "discortx/moviesPK")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "discortx")


def test_finds_every_scheduled_workflow(keepalive: ModuleType) -> None:
    assert keepalive.scheduled_workflows() == [
        "export.yml",
        "keepalive.yml",
        "scrape-canary.yml",
        "scrape-full.yml",
    ]


def test_ignores_workflows_without_a_schedule(keepalive: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "ci.yml").write_text("on:\n  pull_request:\njobs: {}\n", encoding="utf-8")
    (tmp_path / "cron.yml").write_text(
        "on:\n  schedule:\n    - cron: '1 1 * * *'\njobs: {}\n", encoding="utf-8"
    )
    (tmp_path / "push.yml").write_text("on: push\njobs: {}\n", encoding="utf-8")
    assert keepalive.scheduled_workflows(tmp_path) == ["cron.yml"]


def test_dispatch_enables_every_scheduled_workflow_and_opens_the_issue(
    keepalive: ModuleType, env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGitHub(disabled={"scrape-full.yml"})
    assert keepalive.main([], transport=httpx.MockTransport(fake.handler)) == 0
    assert sorted(fake.enabled) == keepalive.scheduled_workflows()
    assert fake.state["scrape-full.yml"] == "active"  # a disabled schedule came back
    [issue] = fake.issues
    assert issue["title"].startswith("[maintenance] 20") and issue["labels"] == ["maintenance"]
    assert issue["assignees"] == ["discortx"]
    assert "Human maintenance commit" in issue["body"] and "**Z1:**" in issue["body"]
    assert "`scrape-full.yml` | HTTP 204 | active" in issue["body"]
    assert "maintenance issue #1: created" in capsys.readouterr().out


def test_second_run_in_the_month_comments_instead(keepalive: ModuleType, env: None) -> None:
    fake = FakeGitHub()
    transport = httpx.MockTransport(fake.handler)
    assert keepalive.main([], transport=transport) == 0
    assert keepalive.main([], transport=transport) == 0
    assert len(fake.issues) == 1
    assert [n for n, _ in fake.comments] == [1]


def test_a_refused_enable_fails_the_run_but_still_reports(keepalive: ModuleType, env: None) -> None:
    fake = FakeGitHub(refuse={"export.yml"})
    assert keepalive.main([], transport=httpx.MockTransport(fake.handler)) == 1
    assert "`export.yml` | HTTP 403 | HTTP 403" in fake.issues[0]["body"]


def test_needs_token(keepalive: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert keepalive.main([]) == 2


def test_never_commits(keepalive: ModuleType) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "/git/" not in source and "/contents/" not in source and "git commit" not in source
