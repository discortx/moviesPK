# ruff: noqa: RUF001  (the tests feed deliberately unusual Unicode to the normalizer)
"""P1-07: normalizer table tests (plan §10.3 step 2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from structlog.testing import capture_logs

from moviespk_scraper.adapters.base import RawMovie, RawShowtime
from moviespk_scraper.core.clock import pkt_date
from moviespk_scraper.core.logging import get_logger
from moviespk_scraper.pipeline.ids import showtime_id
from moviespk_scraper.pipeline.normalize import (
    map_genres,
    normalize_movie,
    normalize_showtime,
    parse_title,
    title_key,
    to_utc,
)

# --- acceptance (plan P1-07) ------------------------------------------------------------


def test_dune_imax_urdu() -> None:
    parsed = parse_title("Dune (IMAX) [Urdu]")
    assert parsed.title == "Dune"
    assert parsed.formats == ("IMAX",)
    assert parsed.languages == ("ur",)
    show = normalize_showtime(
        RawShowtime(movie_title="Dune (IMAX) [Urdu]", starts_at=datetime(2026, 12, 1, 20, 0))
    )
    assert (show.movie_title, show.format, show.language) == ("Dune", "IMAX", "ur")


@pytest.mark.parametrize(
    ("local", "utc", "pkt_day"),
    [
        (
            datetime(2026, 12, 1, 23, 30),
            datetime(2026, 12, 1, 18, 30, tzinfo=UTC),
            date(2026, 12, 1),
        ),
        (
            datetime(2026, 12, 2, 0, 15),
            datetime(2026, 12, 1, 19, 15, tzinfo=UTC),
            date(2026, 12, 2),
        ),
    ],
)
def test_pkt_to_utc(local: datetime, utc: datetime, pkt_day: date) -> None:
    converted = to_utc(local)
    assert converted == utc
    assert converted.isoformat().replace("+00:00", "Z") == utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert pkt_date(converted) == pkt_day


def test_aware_times_are_converted_not_reinterpreted() -> None:
    assert to_utc(datetime(2026, 12, 1, 18, 30, 45, 999, tzinfo=UTC)) == datetime(
        2026, 12, 1, 18, 30, 45, tzinfo=UTC
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("جوانی پھر نہیں آنی ۳", "جوانی پھر نہیں آنی ۳"),  # Urdu kept
        ("ﺟﻮﺍﻧﯽ", "جوانی"),  # Arabic presentation forms → NFKC letters
        ("Ｍｉｓｓｉｏｎ　Ｉｍｐｏｓｓｉｂｌｅ", "Mission Impossible"),  # full-width → NFKC
        ("  Mission  Impossible  ", "Mission Impossible"),
    ],
)
def test_nfkc_and_urdu_titles(raw: str, expected: str) -> None:
    assert parse_title(raw).title == expected


@pytest.mark.parametrize(
    ("hall", "expected"),
    [(" Screen  2 ", "Screen 2"), (None, ""), ("", ""), ("   ", ""), (" \t", "")],
)
def test_hall(hall: str | None, expected: str) -> None:
    show = normalize_showtime(
        RawShowtime(movie_title="X", starts_at=datetime(2026, 12, 1, 20, 0), hall=hall)
    )
    assert show.hall == expected


def test_missing_and_blank_hall_give_one_showtime_id() -> None:
    ids = {
        showtime_id(
            "c",
            "1",
            normalize_showtime(
                RawShowtime(movie_title="X", starts_at=datetime(2026, 12, 1, 20, 0), hall=h)
            ).starts_at,
            normalize_showtime(
                RawShowtime(movie_title="X", starts_at=datetime(2026, 12, 1, 20, 0), hall=h)
            ).hall,
            "2D",
        )
        for h in (None, "", "   ")
    }
    assert len(ids) == 1


# --- titles seen on real sites ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "title", "formats", "languages", "cert"),
    [
        ("18+Belkis (Turkish Urdu Dubbed)", "Belkis", (), ("ur",), "18+"),
        ("18+Resident Evil (English)", "Resident Evil", (), ("en",), "18+"),
        ("Clayface (English)", "Clayface", (), ("en",), None),
        ("GODZILLA MINUS ZERO (ENGLISH SUBTITLE)", "GODZILLA MINUS ZERO", (), (), None),
        ("Shogun (Japanese English Subtitles)", "Shogun", (), ("other",), None),
        (
            "Godzilla Minus Zero (Japanes With Eng Subtitles)",
            "Godzilla Minus Zero",
            (),
            ("other",),
            None,
        ),
        ("Spider-Man: Brand New Day (2D Eng)", "Spider-Man: Brand New Day", ("2D",), ("en",), None),
        ("Avatar: Fire and Ash 3D", "Avatar: Fire and Ash", ("3D",), (), None),
        ("Avatar (3D) (Urdu Dubbed)", "Avatar", ("3D",), ("ur",), None),
        (
            "Mission: Impossible (The Final Reckoning)",
            "Mission: Impossible (The Final Reckoning)",
            (),
            (),
            None,
        ),
        ("Top Gun (IMAX 3D)", "Top Gun", ("IMAX",), (), None),
        ("(English)", "(English)", (), ("en",), None),  # never an empty title
    ],
)
def test_parse_title_cases(
    raw: str, title: str, formats: tuple[str, ...], languages: tuple[str, ...], cert: str | None
) -> None:
    parsed = parse_title(raw)
    assert (parsed.title, parsed.formats, parsed.languages, parsed.certification) == (
        title,
        formats,
        languages,
        cert,
    )


def test_title_key_drops_punctuation_keeps_scripts() -> None:
    assert title_key("Mission: Impossible – Dead Reckoning!") == "mission impossible dead reckoning"
    assert title_key("Jawani Phir Nahi Ani 3") == "jawani phir nahi ani 3"
    assert title_key("جوانی، پھر نہیں آنی") == "جوانی پھر نہیں آنی"


# --- formats and languages ----------------------------------------------------------------


def test_format_field_wins_over_title_marker() -> None:
    show = normalize_showtime(
        RawShowtime(
            movie_title="Dune (IMAX)", starts_at=datetime(2026, 12, 1, 20), format_text="3D"
        )
    )
    assert show.format == "3D"


def test_no_format_anywhere_defaults_to_2d() -> None:
    show = normalize_showtime(RawShowtime(movie_title="Dune", starts_at=datetime(2026, 12, 1, 20)))
    assert show.format == "2D" and "format defaulted to 2D" in show.notes


def test_unknown_format_text_is_other_and_logged() -> None:
    with capture_logs() as logs:
        show = normalize_showtime(
            RawShowtime(
                movie_title="X", starts_at=datetime(2026, 12, 1, 20), format_text="Dolby Atmos"
            ),
            get_logger(),
        )
    assert show.format == "OTHER"
    assert any(e["event"] == "normalize.unknown_format" for e in logs)


def test_unknown_language_is_other_and_logged() -> None:
    with capture_logs() as logs:
        show = normalize_showtime(
            RawShowtime(movie_title="X", starts_at=datetime(2026, 12, 1, 20)), get_logger()
        )
    assert show.language == "other" and "language unknown" in show.notes
    assert any(e["event"] == "normalize.unknown_language" for e in logs)


def test_language_field_wins_over_title() -> None:
    show = normalize_showtime(
        RawShowtime(
            movie_title="X (English)", starts_at=datetime(2026, 12, 1, 20), language_text="Urdu"
        )
    )
    assert show.language == "ur"


# --- genres and movies ----------------------------------------------------------------------


def test_genres_map_to_vocabulary_and_unknown_is_other() -> None:
    with capture_logs() as logs:
        genres = map_genres(("Action, Sci-Fi", "Entertainment", "Horror/Thriller"), get_logger())
    assert genres == ("action", "science-fiction", "other", "horror", "thriller")
    assert any(
        e["event"] == "normalize.unknown_genre" and e["value"] == "entertainment" for e in logs
    )


def test_normalize_movie() -> None:
    movie = normalize_movie(
        RawMovie(
            title="18+Belkis (Turkish Urdu Dubbed)",
            local_key=" F000003188 ",
            runtime_min=85,
            genres=("Entertainment",),
            synopsis="  Left homeless\nafter a dark tragedy.  ",
            release_date=date(2026, 11, 20),
            rating="A",
        )
    )
    assert movie.title == "Belkis" and movie.title_key == "belkis"
    assert movie.local_key == "F000003188"
    assert movie.languages == ("ur",)
    assert movie.genres == ("other",)
    assert movie.synopsis == "Left homeless after a dark tragedy."
    assert movie.year == 2026
    assert movie.certification == "A"  # the cinema's rating field wins over the title marker


def test_movie_certification_falls_back_to_title_marker() -> None:
    assert normalize_movie(RawMovie(title="18+Belkis")).certification == "18+"


def test_showtime_keeps_ids_and_seats() -> None:
    show = normalize_showtime(
        RawShowtime(
            movie_title="Clayface (English)",
            starts_at=datetime(2026, 11, 25, 23, 0),
            movie_local_key="F000003115",
            hall="PLATINUM",
            format_text="2D",
            external_id="88394",
            booking_url="https://web.cinepax.com/pages/booking.html?filmCode=F000003115&cinemaId=0000000002",
            seats_available=29,
        )
    )
    assert show.starts_at == datetime(2026, 11, 25, 18, 0, tzinfo=UTC)
    assert (show.external_id, show.seats_available, show.movie_local_key) == (
        "88394",
        29,
        "F000003115",
    )
    assert show.booking_url and show.booking_url.startswith("https://web.cinepax.com/")
