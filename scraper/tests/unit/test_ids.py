import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

from moviespk_scraper.pipeline.ids import canonical_hall, movie_key, showtime_id, utc_iso_seconds

PKT = timezone(timedelta(hours=5))
START = datetime(2026, 12, 1, 18, 30, tzinfo=UTC)


@pytest.mark.parametrize("hall", [None, "", "   ", "\t\n", "　"])
def test_missing_hall_variants_give_one_id(hall: str | None) -> None:
    assert showtime_id("cinepax-packages", "123", START, hall, "2D") == showtime_id(
        "cinepax-packages", "123", START, None, "2D"
    )


def test_empty_hall_keeps_its_slot() -> None:
    expected = hashlib.sha1(
        b"cinepax-packages|123|2026-12-01T18:30:00Z||2D", usedforsecurity=False
    ).hexdigest()
    assert showtime_id("cinepax-packages", "123", START, None, "2D") == expected


def test_five_components_with_hall() -> None:
    expected = hashlib.sha1(
        b"c|tt-local-2026|2026-12-01T18:30:00Z|Hall 1|IMAX", usedforsecurity=False
    ).hexdigest()
    hall = "  Hall" + chr(0xA0) + " 1 "  # NFKC turns NBSP into a space, then collapse
    assert showtime_id("c", "tt-local-2026", START, hall, "IMAX") == expected


def test_timezone_is_normalized_to_utc_seconds() -> None:
    pkt = datetime(2026, 12, 1, 23, 30, 0, 999_999, tzinfo=PKT)
    assert utc_iso_seconds(pkt) == "2026-12-01T18:30:00Z"
    assert showtime_id("c", "1", pkt, None, "2D") == showtime_id("c", "1", START, None, "2D")


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_iso_seconds(datetime(2026, 12, 1, 18, 30))


def test_id_shape() -> None:
    sid = showtime_id("c", "1", START, "A", "3D")
    assert len(sid) == 40 and sid == sid.lower()


def test_movie_key_prefers_tmdb() -> None:
    assert movie_key(550, "fight-club-1999") == "550"
    assert movie_key(None, "fight-club-1999") == "fight-club-1999"
    with pytest.raises(ValueError):
        movie_key(None, None)
    with pytest.raises(ValueError):
        movie_key(True, None)  # type: ignore[arg-type]


def test_canonical_hall() -> None:
    assert canonical_hall("  Screen   2 ") == "Screen 2"
    assert canonical_hall(None) == ""
