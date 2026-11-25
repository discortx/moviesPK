"""P1-05: the capture tool's cleaning rules, and every committed fixture replays offline."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.offline import MANIFEST, FixtureTransport
from moviespk_scraper.core.redact import clean_body

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "scraper" / "tests" / "fixtures"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "capture_fixture", ROOT / "scripts" / "capture_fixture.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cap = _load()


def test_json_secrets_are_redacted_but_ids_survive() -> None:
    data = {
        "sessionId": "110453",
        "cinemaId": "0000000014",
        "accessToken": "abc",
        "csrf": "x",
        "apiKey": "k",
        "nested": [{"authorization": "Bearer y", "title": "Belkis"}],
        "auth": "z",
        "tokenCount": 3,  # not a string: left alone
    }
    body, ext = clean_body("application/json", json.dumps(data).encode())
    out = json.loads(body)
    assert ext == ".json"
    assert out["sessionId"] == "110453" and out["cinemaId"] == "0000000014"
    assert out["accessToken"] == out["csrf"] == out["apiKey"] == out["auth"] == "REDACTED"
    assert out["nested"][0] == {"authorization": "REDACTED", "title": "Belkis"}
    assert out["tokenCount"] == 3


def test_hidden_form_tokens_are_redacted() -> None:
    html = (
        '<form><input type="hidden" name="__RequestVerificationToken" value="secret123">'
        '<input type="hidden" name="__VIEWSTATE" value="dGVzdA==">'
        '<input name="cinemaId" value="8888"></form>'
    )
    body, ext = clean_body("text/html; charset=utf-8", html.encode())
    text = body.decode()
    assert ext == ".html"
    assert "secret123" not in text and "dGVzdA==" not in text
    assert 'value="8888"' in text


def test_urls_with_secret_query_parameters_are_refused() -> None:
    cap.check_url_has_no_secrets("https://c.example/api/movies?cinemaId=14")
    with pytest.raises(SystemExit):
        cap.check_url_has_no_secrets("https://c.example/api/x?access_token=abc")


def test_written_fixture_has_no_cookies_and_replays(tmp_path: Path) -> None:
    resp = httpx.Response(
        200,
        headers={"content-type": "application/json", "set-cookie": "sid=1", "etag": '"v1"'},
        json=[{"id": 1}],
    )
    out = tmp_path / "c" / "2026-11-25"
    entries = cap.write_fixture(
        out, "c", [("https://c.example/api/x?b=1", resp)], datetime(2026, 11, 25, tzinfo=UTC)
    )
    assert entries[0]["headers"] == {"content-type": "application/json", "etag": '"v1"'}
    with ScraperHttpClient("MoviesPKBot/1.0 (+test)", transport=FixtureTransport(out)) as http:
        assert http.get("https://c.example/api/x?b=1", min_delay_ms=1500).json() == [{"id": 1}]


# --- every committed fixture ------------------------------------------------------------

MANIFESTS = sorted(FIXTURES.glob(f"*/*/{MANIFEST}"))


@pytest.mark.parametrize(
    "manifest", MANIFESTS, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}"
)
def test_committed_fixture_is_complete_and_clean(manifest: Path) -> None:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["cinema_id"] == manifest.parent.parent.name
    transport = FixtureTransport(manifest.parent)  # every body file exists
    assert transport.responses
    for entry in data["responses"]:
        assert "set-cookie" not in {k.lower() for k in entry["headers"]}
        body = (manifest.parent / entry["body"]).read_text(encoding="utf-8", errors="replace")
        assert "Set-Cookie" not in body


def test_first_cinema_fixture_meets_p1_05() -> None:
    """At least 2 movies and several showtimes (plan P1-05 acceptance)."""
    movies_file = next((FIXTURES / "cinepax-packages-mall").glob("*/002-api-movies-*.json"))
    movies = json.loads(movies_file.read_text(encoding="utf-8"))
    sessions = [s for m in movies for scr in m["screens"].values() for s in scr["sessions"]]
    assert len(movies) >= 2 and len(sessions) >= 5
