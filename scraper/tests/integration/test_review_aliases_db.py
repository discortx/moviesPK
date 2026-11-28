"""P2-04 integration: what scripts/review_aliases.py lists from the database."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from moviespk_scraper.db.client import DB

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "review_aliases.py"
NOW = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)


def load_tool():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("review_aliases", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_aliases"] = module
    spec.loader.exec_module(module)
    return module


def movie(movie_id: str, title: str, **extra: object) -> dict:
    return {
        "_id": movie_id,
        "localKey": movie_id,
        "slug": movie_id,
        "title": title,
        "matchStatus": "unmatched",
    } | extra


def show(movie_id: str, cinema: str, hours: float, status: str = "active") -> dict:
    return {
        "_id": f"{movie_id}-{cinema}-{hours}",
        "movieId": movie_id,
        "cinemaId": cinema,
        "startsAt": NOW + timedelta(hours=hours),
        "status": status,
    }


def test_lists_pending_suggestions_and_unmatched_titles_with_upcoming_shows(db: DB) -> None:
    db.movies.insert_many(
        [
            movie("m1", "Avengers: Endgame Encore (Re-release)"),
            movie("m2", "Belkis", year=2026),
            movie("m3", "Gone"),  # only past shows
            movie("m4", "Sanjog", matchStatus="matched"),
            movie("m5", "Hexed"),  # a manual alias exists
        ]
    )
    db.showtimes.insert_many(
        [
            show("m1", "universal-emporium-mall-lahore", 2),
            show("m1", "universal-emporium-mall-lahore", 5),
            show("m1", "cinestar-township-lahore", 3),
            show("m1", "cinestar-township-lahore", 4, status="cancelled"),
            show("m2", "cinepax-packages-mall", 1),
            show("m3", "cinepax-packages-mall", -2),
            show("m4", "cinepax-packages-mall", 1),
            show("m5", "cinepax-packages-mall", 1),
        ]
    )
    db.movie_aliases.insert_many(
        [
            {"_id": "hope", "movieKey": "1058424", "source": "pending"},
            {"_id": "sanjog", "movieKey": "1795122", "source": "auto"},
        ]
    )
    tool = load_tool()
    items = {i.key: i for i in tool.review_items(db, {"hexed"}, NOW)}
    assert sorted(items) == ["avengers endgame encore re release", "belkis", "hope"]
    avengers = items["avengers endgame encore re release"]
    assert avengers.shows == 3 and avengers.status == "unmatched"
    assert avengers.cinemas == ["cinestar-township-lahore", "universal-emporium-mall-lahore"]
    assert items["belkis"].year == 2026
    assert items["hope"].status == "pending" and items["hope"].suggested_tmdb_id == 1058424
