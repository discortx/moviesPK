"""GitHub Issues alerts (plan §18.1, P1-12).

* One open issue per (cinema, type), titled ``[alert] <cinemaId>: <type>`` with labels
  ``alert`` and ``alert:<type>``.
* Deduplication: every post ends with a hidden marker
  ``<!-- moviespk-alert state=<state> at=<ISO time> -->``. An open issue gets a new comment
  only when the state changed or the last post is 24 h old.
* Recovery: the next ``ok`` run closes the cinema's run-alert issues with a comment; the
  canary closes its own alert types when their condition clears.
* Alerts with ``repeat_after=None`` (robots, terms: the owner must review) never get a
  repeat comment for the same state, however old the last post.
* Digests (``[digest] ...``, label ``digest``): one issue per title, closed after 7 days.
* The body holds the cinema, type, summary, run link and last success time — never
  headers, cookies or secrets (summaries pass through ``health.clean_message``).
* Posting failures are logged and never fail the job. :class:`PrintAlerter` is the
  ``--dry-run`` stand-in.

Uses ``GITHUB_TOKEN`` (needs ``issues: write`` in the workflow) and ``GITHUB_REPOSITORY``.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TextIO

import httpx
from structlog.typing import FilteringBoundLogger

from ..core.logging import get_logger
from .health import clean_message

API = "https://api.github.com"
REPEAT_AFTER = timedelta(hours=24)
RUN_ALERT_TYPES = ("failed", "blocked", "drift")
_MARKER = re.compile(r"<!-- moviespk-alert state=(?P<state>\S+) at=(?P<at>\S+) -->")


@dataclass(frozen=True)
class Alert:
    cinema_id: str
    type: str  # failed | blocked | drift | ...
    summary: str
    state: str  # what "the same problem" means, e.g. "failed:SchemaDriftError"
    run_url: str | None = None
    last_success: datetime | None = None
    #: Re-post the same state after this long; ``None`` = never (needs a human review).
    repeat_after: timedelta | None = REPEAT_AFTER

    @property
    def title(self) -> str:
        return f"[alert] {self.cinema_id}: {self.type}"


def run_url() -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo, run = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return f"{server}/{repo}/actions/runs/{run}" if repo and run else None


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def render(alert: Alert, now: datetime) -> str:
    last = _iso(alert.last_success) if alert.last_success else "never"
    lines = [
        f"**Cinema:** `{alert.cinema_id}`",
        f"**Type:** `{alert.type}`",
        f"**Summary:** {clean_message(alert.summary)}",
        f"**Run:** {alert.run_url or '(local run)'}",
        f"**Last success:** {last}",
        "",
        f"<!-- moviespk-alert state={alert.state} at={_iso(now)} -->",
    ]
    return "\n".join(lines)


def last_marker(texts: list[str]) -> tuple[str, datetime] | None:
    found = None
    for text in texts:
        for match in _MARKER.finditer(text or ""):
            at = datetime.fromisoformat(match.group("at").replace("Z", "+00:00"))
            if found is None or at >= found[1]:
                found = (match.group("state"), at)
    return found


class Alerter(Protocol):
    def raise_alert(self, alert: Alert, now: datetime) -> None: ...

    def resolve(
        self, cinema_id: str, now: datetime, types: tuple[str, ...] = RUN_ALERT_TYPES
    ) -> None: ...

    def post_digest(self, title: str, body: str) -> None: ...

    def close_digests(self, created_before: datetime) -> None: ...


class PrintAlerter:
    """``--dry-run``: show what would be posted."""

    def __init__(self, out: TextIO | None = None) -> None:
        self.out = out or sys.stdout

    def raise_alert(self, alert: Alert, now: datetime) -> None:
        self.out.write(f"[dry-run alert] {alert.title}: {clean_message(alert.summary)}\n")

    def resolve(
        self, cinema_id: str, now: datetime, types: tuple[str, ...] = RUN_ALERT_TYPES
    ) -> None:
        return None

    def post_digest(self, title: str, body: str) -> None:
        self.out.write(f"[dry-run digest] {title}\n{body}\n")

    def close_digests(self, created_before: datetime) -> None:
        return None


class GitHubAlerter:
    def __init__(
        self,
        token: str,
        repository: str,
        *,
        transport: httpx.BaseTransport | None = None,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        self.repository = repository
        self._client = httpx.Client(
            base_url=f"{API}/repos/{repository}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "moviespk-scraper-alerts",
            },
            timeout=15.0,
            transport=transport,
        )
        self._log = logger or get_logger()
        self._lock = threading.Lock()  # cinemas run in threads; keep posts ordered
        self._open: dict[str, dict[str, Any]] | None = None

    @classmethod
    def from_env(cls) -> GitHubAlerter | None:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
        return cls(token, repository) if token and repository else None

    def close(self) -> None:
        self._client.close()

    # --- GitHub calls -----------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def _list_open(self, label: str) -> dict[str, dict[str, Any]]:
        issues: dict[str, dict[str, Any]] = {}
        for page in range(1, 11):
            batch = self._request(
                "GET",
                "/issues",
                params={"state": "open", "labels": label, "per_page": 100, "page": page},
            )
            for issue in batch:
                if "pull_request" not in issue:
                    issues[issue["title"]] = issue
            if len(batch) < 100:
                break
        return issues

    def _open_issues(self) -> dict[str, dict[str, Any]]:
        """Open ``alert`` issues by title, fetched once per run."""
        if self._open is None:
            self._open = self._list_open("alert")
        return self._open

    def _close(self, issue: dict[str, Any], comment: str) -> None:
        self._request("POST", f"/issues/{issue['number']}/comments", json={"body": comment})
        self._request(
            "PATCH",
            f"/issues/{issue['number']}",
            json={"state": "closed", "state_reason": "completed"},
        )

    def _recent_posts(
        self, issue: dict[str, Any], now: datetime, window: timedelta | None = REPEAT_AFTER
    ) -> list[str]:
        params: dict[str, Any] = {"per_page": 100}
        if window is not None:
            params["since"] = _iso(now - window * 2)
        comments = self._request("GET", f"/issues/{issue['number']}/comments", params=params)
        return [issue.get("body") or ""] + [c.get("body") or "" for c in comments]

    # --- alert API --------------------------------------------------------------------

    def raise_alert(self, alert: Alert, now: datetime) -> None:
        try:
            with self._lock:
                self._raise(alert, now)
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            self._log.warning("alert.post_failed", title=alert.title, error=type(exc).__name__)

    def _raise(self, alert: Alert, now: datetime) -> None:
        issues = self._open_issues()
        issue = issues.get(alert.title)
        body = render(alert, now)
        if issue is None:
            created = self._request(
                "POST",
                "/issues",
                json={
                    "title": alert.title,
                    "body": body,
                    "labels": ["alert", f"alert:{alert.type}"],
                },
            )
            issues[alert.title] = created
            self._log.info("alert.created", title=alert.title, issue=created.get("number"))
            return
        last = last_marker(self._recent_posts(issue, now, alert.repeat_after))
        if (
            last is not None
            and last[0] == alert.state
            and (alert.repeat_after is None or now - last[1] < alert.repeat_after)
        ):
            self._log.info("alert.unchanged", title=alert.title, issue=issue["number"])
            return
        self._request("POST", f"/issues/{issue['number']}/comments", json={"body": body})
        self._log.info("alert.commented", title=alert.title, issue=issue["number"])

    def resolve(
        self, cinema_id: str, now: datetime, types: tuple[str, ...] = RUN_ALERT_TYPES
    ) -> None:
        """Close the open ``[alert] <cinema_id>: <type>`` issues for ``types``."""
        try:
            with self._lock:
                issues = self._open_issues()
                for alert_type in types:
                    title = f"[alert] {cinema_id}: {alert_type}"
                    issue = issues.pop(title, None)
                    if issue is None:
                        continue
                    self._close(
                        issue,
                        f"Recovered: `{cinema_id}` `{alert_type}` cleared at {_iso(now)}. Closing.",
                    )
                    self._log.info("alert.closed", title=title, issue=issue["number"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            self._log.warning("alert.resolve_failed", cinemaId=cinema_id, error=type(exc).__name__)

    # --- digests ----------------------------------------------------------------------

    def post_digest(self, title: str, body: str) -> None:
        """Create the digest issue unless one with this title is already open."""
        try:
            with self._lock:
                if title in self._list_open("digest"):
                    self._log.info("digest.exists", title=title)
                    return
                created = self._request(
                    "POST", "/issues", json={"title": title, "body": body, "labels": ["digest"]}
                )
                self._log.info("digest.created", title=title, issue=created.get("number"))
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            self._log.warning("digest.post_failed", title=title, error=type(exc).__name__)

    def close_digests(self, created_before: datetime) -> None:
        """Close open digest issues created before ``created_before`` (7-day lifetime)."""
        try:
            with self._lock:
                for title, issue in self._list_open("digest").items():
                    created = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
                    if created < created_before:
                        self._close(issue, "Closed automatically after 7 days.")
                        self._log.info("digest.closed", title=title, issue=issue["number"])
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            self._log.warning("digest.close_failed", error=type(exc).__name__)
