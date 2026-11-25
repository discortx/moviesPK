"""P1-12: scrape_runs documents (plan §8.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from moviespk_scraper.services.health import (
    MAX_ERRORS,
    RunError,
    RunRecord,
    clean_message,
    run_document,
)

T0 = datetime(2026, 11, 26, 2, 0, tzinfo=UTC)


def record(**changes: object) -> RunRecord:
    base: dict[str, object] = {
        "job": "full",
        "cinema_id": "cinepax-packages-mall",
        "started_at": T0,
        "finished_at": T0 + timedelta(seconds=4),
        "status": "ok",
        "counts": {"movies": 8, "showtimes": 19, "upserted": 19},
    }
    return RunRecord(**{**base, **changes})  # type: ignore[arg-type]


def test_document_matches_the_contract_and_expires_in_30_days() -> None:
    doc = run_document(record(github_run_id="123"))
    assert doc["counts"] == {
        "movies": 8,
        "showtimes": 19,
        "upserted": 19,
        "invalid": 0,
        "cancelled": 0,
        "imagesUploaded": 0,
        "imagesFailed": 0,
    }
    assert doc["expireAt"] == T0 + timedelta(days=30, seconds=4)
    assert doc["githubRunId"] == "123" and doc["errors"] == []


def test_errors_are_capped_and_cleaned() -> None:
    errors = [RunError("ParseError", "x" * 500 + " https://e.com/a?token=s")] * 30
    doc = run_document(record(status="failed", errors=errors))
    assert len(doc["errors"]) == MAX_ERRORS
    assert len(doc["errors"][0]["message"]) <= 300


def test_invalid_document_is_rejected() -> None:
    with pytest.raises(ValidationError):
        run_document(record(status="exploded"))


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("GET https://web.cinepax.com/api/movies?cinemaId=14 → 503", "GET /api/movies → 503"),
        ("see https://x.example", "see /"),
        ("multi\n line\ttext", "multi line text"),
    ],
)
def test_clean_message(message: str, expected: str) -> None:
    assert clean_message(message) == expected
