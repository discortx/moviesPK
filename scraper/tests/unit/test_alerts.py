"""P1-12: GitHub Issues alerts against a stateful fake GitHub (plan §18.1)."""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from moviespk_scraper.services.alerts import (
    Alert,
    GitHubAlerter,
    PrintAlerter,
    last_marker,
    render,
)

REPO = "discortx/moviesPK"
BASE = f"https://api.github.com/repos/{REPO}"
T0 = datetime(2026, 11, 26, 2, 0, tzinfo=UTC)


class FakeGitHub:
    """Issues and comments kept across alerter instances (= across runs)."""

    def __init__(self) -> None:
        self.issues: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.created = 0
        self.fail = False
        self.clock = T0  # created_at of new issues

    def install(self, router: respx.MockRouter) -> None:
        router.get(f"{BASE}/issues").mock(side_effect=self.list_issues)
        router.post(f"{BASE}/issues").mock(side_effect=self.create_issue)
        router.get(url__regex=rf"{BASE}/issues/\d+/comments").mock(side_effect=self.list_comments)
        router.post(url__regex=rf"{BASE}/issues/\d+/comments").mock(side_effect=self.add_comment)
        router.patch(url__regex=rf"{BASE}/issues/\d+$").mock(side_effect=self.edit_issue)

    def _number(self, request: httpx.Request) -> int:
        return int(request.url.path.split("/issues/")[1].split("/")[0])

    def list_issues(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(500)
        label = request.url.params["labels"]
        open_ = [i for i in self.issues.values() if i["state"] == "open" and label in i["labels"]]
        return httpx.Response(200, json=open_)

    def create_issue(self, request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        number = len(self.issues) + 1
        created_at = self.clock.isoformat().replace("+00:00", "Z")
        self.issues[number] = {"number": number, "state": "open", "created_at": created_at, **data}
        self.comments[number] = []
        self.created += 1
        return httpx.Response(201, json=self.issues[number])

    def list_comments(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.comments[self._number(request)])

    def add_comment(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)["body"]
        self.comments[self._number(request)].append({"body": body})
        return httpx.Response(201, json={"body": body})

    def edit_issue(self, request: httpx.Request) -> httpx.Response:
        issue = self.issues[self._number(request)]
        issue.update(json.loads(request.content))
        return httpx.Response(200, json=issue)


@pytest.fixture
def github() -> Iterator[FakeGitHub]:
    fake = FakeGitHub()
    with respx.mock(assert_all_called=False) as router:
        fake.install(router)
        yield fake


def alert(state: str = "failed:SchemaDriftError", summary: str = "missing key 'screens'") -> Alert:
    return Alert(
        cinema_id="cinepax-packages-mall",
        type="drift",
        summary=summary,
        state=state,
        run_url="https://github.com/discortx/moviesPK/actions/runs/123",
        last_success=T0 - timedelta(hours=12),
    )


def run(fake: FakeGitHub, a: Alert, now: datetime) -> None:
    """One job run = a fresh alerter (it re-reads the open issues)."""
    alerter = GitHubAlerter("token", REPO)
    alerter.raise_alert(a, now)
    alerter.close()


# --- acceptance ----------------------------------------------------------------------


def test_forced_failure_creates_exactly_one_issue(github: FakeGitHub) -> None:
    run(github, alert(), T0)
    assert github.created == 1
    issue = github.issues[1]
    assert issue["title"] == "[alert] cinepax-packages-mall: drift"
    assert issue["labels"] == ["alert", "alert:drift"]
    assert (
        "actions/runs/123" in issue["body"]
        and "Last success:** 2026-11-25T14:00:00Z" in issue["body"]
    )


def test_repeat_within_24h_adds_no_comment(github: FakeGitHub) -> None:
    run(github, alert(), T0)
    run(github, alert(), T0 + timedelta(hours=12))  # next scheduled run
    run(github, alert(), T0 + timedelta(hours=23, minutes=59))
    assert github.created == 1 and github.comments[1] == []


def test_recovery_closes_the_issue(github: FakeGitHub) -> None:
    run(github, alert(), T0)
    alerter = GitHubAlerter("token", REPO)
    alerter.resolve("cinepax-packages-mall", T0 + timedelta(hours=12))
    alerter.close()
    assert github.issues[1]["state"] == "closed"
    assert "Recovered" in github.comments[1][0]["body"]


# --- deduplication rules --------------------------------------------------------------


def test_comment_after_24h(github: FakeGitHub) -> None:
    run(github, alert(), T0)
    run(github, alert(), T0 + timedelta(hours=24))
    assert len(github.comments[1]) == 1
    run(github, alert(), T0 + timedelta(hours=30))  # the comment at +24 h is the latest post
    assert len(github.comments[1]) == 1


def test_comment_when_state_changes(github: FakeGitHub) -> None:
    run(github, alert(), T0)
    run(github, alert(state="failed:ParseError", summary="bad time"), T0 + timedelta(hours=1))
    assert len(github.comments[1]) == 1 and "bad time" in github.comments[1][0]["body"]


def test_new_issue_after_recovery(github: FakeGitHub) -> None:
    run(github, alert(), T0)
    alerter = GitHubAlerter("token", REPO)
    alerter.resolve("cinepax-packages-mall", T0 + timedelta(hours=1))
    alerter.close()
    run(github, alert(), T0 + timedelta(hours=2))
    assert github.created == 2


def test_resolve_without_open_issue_does_nothing(github: FakeGitHub) -> None:
    alerter = GitHubAlerter("token", REPO)
    alerter.resolve("cinepax-ocean-mall", T0)
    alerter.close()
    assert github.issues == {}


def test_posting_failures_never_raise(github: FakeGitHub) -> None:
    github.fail = True
    run(github, alert(), T0)  # GitHub answers 500: logged, no exception
    alerter = GitHubAlerter("token", REPO)
    alerter.resolve("cinepax-packages-mall", T0)
    alerter.close()


def test_review_alert_is_never_repeated_for_the_same_state(github: FakeGitHub) -> None:
    """robots/terms alerts (repeat_after=None) fire once; days later still no comment."""
    review = replace(alert(state="terms:abc"), type="terms-changed", repeat_after=None)
    for days in (0, 1, 2, 9):
        run(github, review, T0 + timedelta(days=days))
    assert github.created == 1 and github.comments[1] == []
    run(github, replace(review, state="terms:def"), T0 + timedelta(days=10))
    assert len(github.comments[1]) == 1  # a different change is posted


def test_resolve_closes_only_the_given_types(github: FakeGitHub) -> None:
    run(github, replace(alert(), type="stale", state="stale"), T0)
    run(github, alert(), T0)
    alerter = GitHubAlerter("token", REPO)
    alerter.resolve("cinepax-packages-mall", T0, ("stale",))
    alerter.close()
    states = {i["title"]: i["state"] for i in github.issues.values()}
    assert states == {
        "[alert] cinepax-packages-mall: stale": "closed",
        "[alert] cinepax-packages-mall: drift": "open",
    }


# --- digests ---------------------------------------------------------------------------


def test_digest_is_posted_once_per_title(github: FakeGitHub) -> None:
    for _ in range(2):
        alerter = GitHubAlerter("token", REPO)
        alerter.post_digest("[digest] unmatched titles 2026-11-26", "- **Belkis**")
        alerter.close()
    assert github.created == 1
    assert github.issues[1]["labels"] == ["digest"]


def test_digests_close_after_7_days(github: FakeGitHub) -> None:
    alerter = GitHubAlerter("token", REPO)
    alerter.post_digest("[digest] unmatched titles 2026-11-26", "old")
    github.clock = T0 + timedelta(days=6)
    alerter.post_digest("[digest] unmatched titles 2026-12-02", "new")
    alerter.close_digests(T0 + timedelta(days=7, hours=1) - timedelta(days=7))
    alerter.close()
    assert [i["state"] for i in github.issues.values()] == ["closed", "open"]
    assert "after 7 days" in github.comments[1][0]["body"]


# --- body ------------------------------------------------------------------------------


def test_body_strips_query_strings_and_secrets() -> None:
    body = render(
        alert(summary="GET https://web.cinepax.com/api/movies?cinemaId=14&token=abc failed"), T0
    )
    assert "token=abc" not in body and "cinemaId=14" not in body
    assert "/api/movies" in body


def test_marker_round_trip() -> None:
    body = render(alert(), T0)
    assert last_marker([body]) == ("failed:SchemaDriftError", T0)
    assert last_marker(["no marker"]) is None


def test_print_alerter_for_dry_runs() -> None:
    out = io.StringIO()
    PrintAlerter(out).raise_alert(alert(), T0)
    assert out.getvalue().startswith("[dry-run alert] [alert] cinepax-packages-mall: drift")


def test_from_env_needs_token_and_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    assert GitHubAlerter.from_env() is None
