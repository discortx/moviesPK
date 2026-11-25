"""P1-08: validator and sanitizer (plan §10.3 step 3)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from moviespk_scraper.pipeline.normalize import NormalizedMovie, NormalizedShowtime
from moviespk_scraper.pipeline.validate import (
    SYNOPSIS_MAX,
    TITLE_MAX,
    cap,
    strip_html,
    validate,
)

NOW = datetime(2026, 11, 25, 18, 0, tzinfo=UTC)


def show(**changes: object) -> NormalizedShowtime:
    base = NormalizedShowtime(
        movie_title="Belkis",
        title_key="belkis",
        movie_local_key="F1",
        starts_at=NOW + timedelta(hours=3),
        hall="Screen 4",
        format="2D",
        language="ur",
        booking_url="https://web.cinepax.com/pages/booking.html?filmCode=F1",
        external_id="110453",
        seats_available=93,
        seats_total=None,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def movie(**changes: object) -> NormalizedMovie:
    base = NormalizedMovie(
        title="Belkis",
        title_key="belkis",
        local_key="F1",
        original_title=None,
        runtime_min=85,
        genres=("horror",),
        languages=("ur",),
        synopsis="Three sisters.",
        release_date=None,
        year=2026,
        certification="A",
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


# --- acceptance ------------------------------------------------------------------------


def test_invalid_rows_are_counted_by_reason() -> None:
    rows = [
        show(),
        show(starts_at=NOW - timedelta(hours=3)),  # too old
        show(starts_at=NOW + timedelta(days=15)),  # too far ahead
        show(movie_title="", title_key=""),
        show(booking_url="javascript:alert(1)"),
    ]
    result = validate([], rows, now=NOW)
    assert (result.total, result.invalid, len(result.showtimes)) == (5, 4, 1)
    assert result.reasons["starts_at: outside now-2h..now+14d"] == 2
    assert sum(result.reasons.values()) == 4


@pytest.mark.parametrize(("bad", "failed"), [(21, True), (20, False), (0, False)])
def test_invalid_rate_threshold(bad: int, failed: bool) -> None:
    rows = [show(starts_at=NOW - timedelta(days=1))] * bad + [show()] * (100 - bad)
    result = validate([], rows, now=NOW)
    assert result.invalid_rate == pytest.approx(bad / 100)
    assert result.failed is failed


def test_threshold_is_configurable() -> None:
    rows = [show(starts_at=NOW - timedelta(days=1))] + [show()] * 9  # 10% invalid
    assert not validate([], rows, now=NOW).failed
    assert validate([], rows, now=NOW, max_invalid_rate=0.05).failed


def test_html_in_synopsis_is_stripped() -> None:
    m = movie(synopsis="<p>Three <b>orphaned</b> sisters &amp; a witch.</p><script>x()</script>")
    result = validate([m], [], now=NOW)
    assert result.movies[0].synopsis == "Three orphaned sisters & a witch."


def test_lengths_are_capped() -> None:
    long_title = "Word " * 60  # 300 chars
    long_synopsis = "sentence " * 400  # 3,600 chars
    result = validate(
        [movie(title=long_title, synopsis=long_synopsis)], [show(movie_title=long_title)], now=NOW
    )
    m = result.movies[0]
    assert m.synopsis is not None
    assert len(m.title) <= TITLE_MAX and m.title.endswith("…")
    assert len(m.synopsis) <= SYNOPSIS_MAX and m.synopsis.endswith("…")
    assert len(result.showtimes) == 1 and len(result.showtimes[0].movie_title) <= TITLE_MAX


# --- more rules ------------------------------------------------------------------------


def test_window_edges_are_inclusive() -> None:
    rows = [show(starts_at=NOW - timedelta(hours=2)), show(starts_at=NOW + timedelta(days=14))]
    assert validate([], rows, now=NOW).invalid == 0


def test_runtime_out_of_range_is_dropped_not_rejected() -> None:
    result = validate(
        [movie(runtime_min=5), movie(runtime_min=301), movie(runtime_min=30)], [], now=NOW
    )
    assert [m.runtime_min for m in result.movies] == [None, None, 30]
    assert result.fixes["runtime out of range"] == 2


def test_ends_at_must_follow_starts_at() -> None:
    from moviespk_scraper.pipeline.validate import ShowtimeRow

    data = dataclasses.asdict(show())
    with pytest.raises(ValueError, match="endsAt"):
        ShowtimeRow.model_validate({**data, "ends_at": data["starts_at"]})
    ShowtimeRow.model_validate({**data, "ends_at": data["starts_at"] + timedelta(hours=2)})


def test_naive_start_is_invalid() -> None:
    result = validate([], [show(starts_at=datetime(2026, 11, 25, 23, 0))], now=NOW)
    assert result.invalid == 1


def test_negative_seats_are_dropped() -> None:
    result = validate([], [show(seats_available=-3)], now=NOW)
    assert result.invalid == 0 and result.showtimes[0].seats_available is None


def test_html_in_title_and_hall() -> None:
    result = validate([], [show(movie_title="<i>Belkis</i>", hall="<b>Screen&nbsp;4</b>")], now=NOW)
    assert result.showtimes[0].movie_title == "Belkis"
    assert result.showtimes[0].hall == "Screen 4"


def test_empty_input_is_not_a_failure() -> None:
    result = validate([], [], now=NOW)
    assert result.invalid_rate == 0 and not result.failed


def test_now_must_be_aware() -> None:
    with pytest.raises(ValueError):
        validate([], [], now=datetime(2026, 11, 25))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain text", "plain text"),
        ("a &lt; b", "a < b"),
        ("<p>one</p><p>two</p>", "one two"),
        ("<style>p{}</style>visible", "visible"),
        (None, ""),
    ],
)
def test_strip_html(text: str | None, expected: str) -> None:
    assert strip_html(text) == expected


def test_cap_keeps_short_text_and_cuts_at_words() -> None:
    assert cap("short", 10) == "short"
    assert cap("alpha beta gamma delta", 12) == "alpha beta…"
