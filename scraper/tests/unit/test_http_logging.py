"""Request logs carry the §10.2 fields and never the query string or host."""

from __future__ import annotations

import json
import random

import httpx
import respx
import structlog
from structlog.testing import capture_logs

from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.logging import configure_logging, get_logger, url_path

UA = "MoviesPKBot/1.0 (+https://github.com/example/moviespk)"


def test_url_path_drops_query_and_host() -> None:
    assert url_path("https://c.example/api/movies?cinemaId=14&lat=31.4") == "/api/movies"
    assert url_path("https://c.example") == "/"


def test_request_log_fields_without_query() -> None:
    with respx.mock() as router, capture_logs() as logs:
        router.get("https://c.example/robots.txt").mock(return_value=httpx.Response(404))
        router.get("https://c.example/api/movies").mock(return_value=httpx.Response(200))
        log = get_logger(job="full", cinemaId="cinepax-packages-mall", phase="fetch")
        with ScraperHttpClient(UA, logger=log, sleep=lambda _s: None, rng=random.Random(0)) as c:
            c.get("https://c.example/api/movies?cinemaId=0000000014")
    request = next(e for e in logs if e["event"] == "http.request")
    assert request["url_path"] == "/api/movies"
    assert request["status"] == 200
    assert isinstance(request["durationMs"], int)
    assert request["job"] == "full" and request["cinemaId"] == "cinepax-packages-mall"
    assert request["phase"] == "fetch"
    assert "cinemaId=0000000014" not in json.dumps(logs)
    assert "c.example" not in json.dumps(logs)


def test_configure_logging_emits_json(capsys: object) -> None:
    configure_logging("INFO")
    try:
        get_logger(job="canary").info("hello", url_path="/x")
        out = capsys.readouterr().out.strip()  # type: ignore[attr-defined]
        record = json.loads(out)
        assert record["event"] == "hello" and record["job"] == "canary"
        assert record["level"] == "info" and "timestamp" in record
    finally:
        structlog.reset_defaults()
