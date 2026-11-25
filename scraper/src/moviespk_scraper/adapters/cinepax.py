"""Cinepax adapter: public JSON API (adapter group A; docs/cinema-investigation/cinepax.md).

One request per branch per run: ``GET /api/movies?cinemaId=<branch>`` returns the branch's
films, each with ``screens`` → ``sessions``. Both ``list_movies`` and ``list_showtimes``
read the same payload, which is fetched once and kept on the run context.

Late-night shows: Cinepax files a show after midnight under the previous ``businessDate``
with ``lateNight: true``; ``calendarDate`` is the real date. The start time is always
``calendarDate`` + the clock time of ``showtime`` (plan §10.3 step 2), and a
``showtime`` whose date disagrees with ``calendarDate`` is treated as drift.

Not used: posters and backdrops (cinema artwork is never mirrored, plan D1), cast,
the branch list (``/api/cinemas``).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from ..core.clock import pkt_date
from ..core.config import CinemaConfig
from ..core.errors import SchemaDriftError
from .base import RawMovie, RawSeats, RawShowtime, RunContext, ShowRef, build_booking_url

MOVIES_PATH = "/api/movies?cinemaId={branch}"
_CACHE_KEY = "cinepax.movies"
_RUNTIME = re.compile(r"^\s*(\d{1,3})\s*min", re.I)


def _require(obj: Any, key: str, kind: type | tuple[type, ...], where: str) -> Any:
    if not isinstance(obj, dict) or key not in obj:
        raise SchemaDriftError(f"cinepax: missing key {key!r} in {where}")
    value = obj[key]
    if not isinstance(value, kind):
        raise SchemaDriftError(f"cinepax: {where}.{key} is {type(value).__name__}, expected {kind}")
    return value


def _optional_str(obj: dict[str, Any], key: str) -> str | None:
    value = obj.get(key)
    return value.strip() or None if isinstance(value, str) else None


def _runtime(value: str | None) -> int | None:
    match = _RUNTIME.match(value or "")
    return int(match.group(1)) if match else None


def _release_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class CinepaxAdapter:
    adapter_id = "cinepax"
    fetch_mode = "json"

    # --- fetching ----------------------------------------------------------------------

    def _payload(self, ctx: RunContext, cinema: CinemaConfig) -> list[dict[str, Any]]:
        cached = ctx.extra.get(_CACHE_KEY)
        if cached is not None:
            return cached  # type: ignore[return-value]
        if not cinema.branch:
            raise SchemaDriftError(f"cinepax: cinema {cinema.id} has no branch id")
        url = cinema.base_url.rstrip("/") + MOVIES_PATH.format(branch=cinema.branch)
        resp = ctx.fetch(cinema, url)
        try:
            payload = self._check(resp, cinema)
        except SchemaDriftError:
            ctx.save_debug(cinema, "api-movies", resp)
            raise
        ctx.extra[_CACHE_KEY] = payload
        return payload

    @staticmethod
    def _check(resp: httpx.Response, cinema: CinemaConfig) -> list[dict[str, Any]]:
        if resp.status_code != 200:
            raise SchemaDriftError(f"cinepax: /api/movies answered {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SchemaDriftError("cinepax: /api/movies is not JSON") from exc
        if not isinstance(data, list):
            raise SchemaDriftError("cinepax: /api/movies is not a list")
        for i, film in enumerate(data):
            where = f"film[{i}]"
            _require(film, "id", str, where)
            _require(film, "title", str, where)
            screens = _require(film, "screens", dict, where)
            branch = film.get("cinemaId")
            if branch is not None and branch != cinema.branch:
                raise SchemaDriftError(f"cinepax: {where} belongs to branch {branch!r}")
            for name, screen in screens.items():
                sessions = _require(screen, "sessions", list, f"{where}.screens[{name!r}]")
                for j, session in enumerate(sessions):
                    swhere = f"{where}.screens[{name!r}].sessions[{j}]"
                    for key in ("sessionId", "showtime", "calendarDate"):
                        _require(session, key, str, swhere)
        return data

    # --- adapter contract --------------------------------------------------------------

    def list_movies(self, ctx: RunContext, cinema: CinemaConfig) -> list[RawMovie]:
        movies = []
        for film in self._payload(ctx, cinema):
            genre = _optional_str(film, "genre")
            movies.append(
                RawMovie(
                    title=film["title"],
                    local_key=film["id"],
                    runtime_min=_runtime(_optional_str(film, "duration")),
                    genres=(genre,) if genre else (),
                    synopsis=_optional_str(film, "description"),
                    release_date=_release_date(_optional_str(film, "releaseDate")),
                    rating=_optional_str(film, "rating"),
                )
            )
        return movies

    def list_showtimes(
        self, ctx: RunContext, cinema: CinemaConfig, days: int = 7
    ) -> list[RawShowtime]:
        first_day = pkt_date(ctx.now)
        last_day = first_day + timedelta(days=days)
        shows = []
        for film in self._payload(ctx, cinema):
            for screen_name, screen in film["screens"].items():
                screen_type = _optional_str(screen, "type") if isinstance(screen, dict) else None
                for session in screen["sessions"]:
                    starts_at = self._starts_at(session)
                    if not first_day <= starts_at.date() <= last_day:
                        continue
                    seats = session.get("seatsAvailable")
                    shows.append(
                        RawShowtime(
                            movie_title=film["title"],
                            movie_local_key=film["id"],
                            starts_at=starts_at,
                            hall=_optional_str(session, "screenName") or screen_name,
                            format_text=screen_type,
                            external_id=session["sessionId"],
                            booking_url=build_booking_url(
                                cinema.booking_url_template,
                                branch=cinema.branch,
                                sessionId=session["sessionId"],
                                filmId=film["id"],
                                movieTitle=film["title"],
                                cinemaName=_optional_str(film, "cinemaName"),
                            ),
                            seats_available=seats if isinstance(seats, int) else None,
                        )
                    )
        shows.sort(key=lambda s: (s.starts_at, s.hall or "", s.movie_title))
        return shows

    @staticmethod
    def _starts_at(session: dict[str, Any]) -> datetime:
        """Naive PKT start: ``calendarDate`` + the clock time of ``showtime``."""
        try:
            showtime = datetime.fromisoformat(session["showtime"])
            calendar_date = date.fromisoformat(session["calendarDate"])
        except ValueError as exc:
            raise SchemaDriftError(f"cinepax: unparseable session time: {exc}") from exc
        if showtime.tzinfo is not None:
            raise SchemaDriftError("cinepax: showtime now carries a time zone")
        if showtime.date() != calendar_date:
            raise SchemaDriftError(
                f"cinepax: showtime {session['showtime']} disagrees with "
                f"calendarDate {session['calendarDate']}"
            )
        return datetime.combine(calendar_date, showtime.time())

    def fetch_seat_status(
        self, ctx: RunContext, cinema: CinemaConfig, show: ShowRef
    ) -> RawSeats | None:
        """Seat counts come with the listing (``seatsAvailable``), so there is no separate
        seat request; the ``seats`` job (P2-02) re-reads the listing instead."""
        return None
