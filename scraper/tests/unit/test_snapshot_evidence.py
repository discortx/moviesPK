"""Tests for scripts/snapshot_evidence.py (plan P0-07)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import httpx
import pytest
import respx

from moviespk_scraper.core.robots import RobotsPolicy

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "snapshot_evidence.py"
UA = "MoviesPKBot/1.0 (+https://github.com/example/moviespk; contact@example.com)"
ROBOTS = "User-agent: *\nDisallow: /private/\n"
TERMS = (
    "<html><head><script>var x=1</script></head><body><h1>Terms</h1><p>Be nice.</p></body></html>"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("snapshot_evidence", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = _load()


def test_build_evidence_verdicts() -> None:
    policy = RobotsPolicy.from_response(UA, 200, ROBOTS)
    out = ev.build_evidence(
        policy, "https://c.example", ["/api/x", "/private/y"], None, None, "2026-11-24"
    )
    assert out["evidence"]["endpoints"] == [
        {"path": "/api/x", "allowed": True},
        {"path": "/private/y", "allowed": False},
    ]
    assert out["evidence"]["robots_sha256"] == policy.body_sha256()


def test_html_text_drops_scripts() -> None:
    text = ev.html_text(TERMS)
    assert "Be nice." in text and "var x" not in text


@respx.mock
def test_two_runs_on_unchanged_pages_give_same_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ev, "MIN_DELAY_S", 0)
    respx.get("https://c.example/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    terms = respx.get("https://c.example/terms").mock(return_value=httpx.Response(200, text=TERMS))
    args = [
        "--cinema",
        "c",
        "--base-url",
        "https://c.example",
        "--terms-url",
        "https://c.example/terms",
        "--paths",
        "/api/x",
        "/private/y",
        "--user-agent",
        UA,
    ]
    assert ev.main(args) == 0
    first = capsys.readouterr().out
    assert ev.main(args) == 0
    assert capsys.readouterr().out == first
    assert terms.call_count == 2
    assert "Disallowed /private/y" in first
    assert "terms_sha256: " in first and "terms_sha256: null" not in first


@respx.mock
def test_disallowed_terms_page_is_not_fetched(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.get("https://c.example/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    terms = respx.get("https://c.example/private/terms").mock(return_value=httpx.Response(200))
    args = [
        "--cinema",
        "c",
        "--base-url",
        "https://c.example",
        "--terms-url",
        "https://c.example/private/terms",
        "--paths",
        "/",
        "--user-agent",
        UA,
    ]
    assert ev.main(args) == 0
    assert terms.call_count == 0
    assert "not fetched" in capsys.readouterr().out


@respx.mock
def test_robots_5xx_reports_unreachable(capsys: pytest.CaptureFixture[str]) -> None:
    respx.get("https://c.example/robots.txt").mock(return_value=httpx.Response(503))
    args = ["--cinema", "c", "--base-url", "https://c.example", "--paths", "/a", "--user-agent", UA]
    assert ev.main(args) == 0
    out = capsys.readouterr().out
    assert "Disallowed /a" in out and "unreachable" in out


@respx.mock
def test_relative_terms_url_resolves_against_base(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ev, "MIN_DELAY_S", 0)
    respx.get("https://c.example/robots.txt").mock(return_value=httpx.Response(404))
    terms = respx.get("https://c.example/legal/terms").mock(
        return_value=httpx.Response(200, text=TERMS)
    )
    args = ["--cinema", "c", "--base-url", "https://c.example", "--terms-url", "/legal/terms"]
    assert ev.main([*args, "--paths", "/", "--user-agent", UA]) == 0
    assert terms.call_count == 1
    assert "terms_url: https://c.example/legal/terms" in capsys.readouterr().out


@pytest.mark.parametrize("cinema", ["cinepax_world_trade_center", "Cinepax", "a--b", "a-"])
def test_rejects_non_slug_cinema_id(cinema: str) -> None:
    args = ["--cinema", cinema, "--base-url", "https://c.example", "--paths", "/"]
    assert ev.main([*args, "--user-agent", UA]) == 2


def test_requires_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCRAPER_USER_AGENT", raising=False)
    assert ev.main(["--cinema", "c", "--base-url", "https://c.example", "--paths", "/"]) == 2
