"""Vista adapter: the public cinema details page of a Vista "browsing" site (adapter group B;
docs/cinema-investigation/vista.md). Used by Universal Cinemas and CineStar.

One request per branch per run: ``GET /browsing/Cinemas/Details/<branch>`` lists every film
at the branch with its sessions for the coming days::

    div.film-list > div.film-item[data-movie-id]
        img.rating-image[src=".../RatingIconGraphic/<rating>?..."]
        h3.film-title
        div.session
            h4.session-date                     "Saturday, 28 November 2026"
            a.session-time[href="...visSelectTickets.aspx?cinemacode=<branch>&txtSessionId=<id>"]
                img[alt]                        hall ("Screen-9", "Gold") or "3DX", "Urdu"
                time[datetime]                  "2026-11-29T00:00:00" (naive PKT)

Late-night shows: a show after midnight is listed under the previous evening's
``session-date`` heading, but ``time[datetime]`` already carries the real calendar date, so
it is used as is. A ``datetime`` more than one day after its heading, or before it, is drift.

Films without sessions (coming soon) are skipped. Not used: posters (never mirrored, plan
D1), the film details pages, seat maps.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser, LexborNode

from ..core.clock import pkt_date
from ..core.config import CinemaConfig
from ..core.errors import SchemaDriftError
from .base import RawMovie, RawSeats, RawShowtime, RunContext, ShowRef, build_booking_url

DETAILS_PATH = "/browsing/Cinemas/Details/{branch}"
_CACHE_KEY = "vista.films"
_RATING = re.compile(r"/RatingIconGraphic/([^/?#]+)", re.I)
#: Icon alts that are a projection format, not a hall. "3DX" is Universal's 3D branding.
_FORMAT_ALTS = {"2d": "2D", "3d": "3D", "3dx": "3D", "imax": "IMAX", "4dx": "4DX"}
#: Icon alts that are the show's language (Vista shows one only when it is not the default).
_LANGUAGE_ALTS = frozenset(
    {
        "urdu",
        "english",
        "punjabi",
        "hindi",
        "pashto",
        "japanese",
        "chinese",
        "korean",
        "turkish",
        "arabic",
        "tamil",
        "telugu",
    }
)


class _Session:
    __slots__ = ("format_text", "hall", "language_text", "session_id", "starts_at")

    def __init__(
        self,
        starts_at: datetime,
        session_id: str,
        hall: str | None,
        format_text: str | None,
        language_text: str | None,
    ) -> None:
        self.starts_at = starts_at
        self.session_id = session_id
        self.hall = hall
        self.format_text = format_text
        self.language_text = language_text


class _Film:
    __slots__ = ("key", "rating", "sessions", "title")

    def __init__(self, key: str, title: str, rating: str | None, sessions: list[_Session]):
        self.key = key
        self.title = title
        self.rating = rating
        self.sessions = sessions


def _text(node: LexborNode | None) -> str:
    return " ".join((node.text(strip=True) if node is not None else "").split())


def _heading_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%A, %d %B %Y").date()
    except ValueError as exc:
        raise SchemaDriftError(f"vista: unparseable session-date heading {text!r}") from exc


def _classify(alts: list[str]) -> tuple[str | None, str | None, str | None]:
    """(hall, format, language) from a session's icon alts. Anything that is not a known
    format or language is the hall name; the first one wins."""
    hall = fmt = lang = None
    for alt in alts:
        key = alt.lower()
        if key in _FORMAT_ALTS:
            fmt = fmt or _FORMAT_ALTS[key]
        elif key in _LANGUAGE_ALTS:
            lang = lang or alt
        else:
            hall = hall or alt
    return hall, fmt, lang


class VistaAdapter:
    adapter_id = "vista"
    fetch_mode = "html"

    # --- fetching ----------------------------------------------------------------------

    def _films(self, ctx: RunContext, cinema: CinemaConfig) -> list[_Film]:
        cached = ctx.extra.get(_CACHE_KEY)
        if cached is not None:
            return cached  # type: ignore[return-value]
        if not cinema.branch:
            raise SchemaDriftError(f"vista: cinema {cinema.id} has no branch id")
        url = cinema.base_url.rstrip("/") + DETAILS_PATH.format(branch=cinema.branch)
        resp = ctx.fetch(cinema, url)
        try:
            films = self._parse(resp, cinema)
        except SchemaDriftError:
            ctx.save_debug(cinema, "cinema-details", resp)
            raise
        ctx.extra[_CACHE_KEY] = films
        return films

    @staticmethod
    def _parse(resp: httpx.Response, cinema: CinemaConfig) -> list[_Film]:
        if resp.status_code != 200:
            raise SchemaDriftError(f"vista: cinema details answered {resp.status_code}")
        tree = LexborHTMLParser(resp.text)
        film_list = tree.css_first("div.film-list")
        if film_list is None:
            raise SchemaDriftError("vista: no div.film-list on the cinema details page")
        items = film_list.css("div.film-item")
        if not items:
            raise SchemaDriftError("vista: div.film-list has no div.film-item")
        films = []
        for i, item in enumerate(items):
            where = f"film-item[{i}]"
            links = item.css("a.session-time")
            if not links:
                continue  # coming soon: no sessions at this branch
            key = (item.attributes.get("data-movie-id") or "").strip()
            title = _text(item.css_first(".film-title"))
            if not key or not title:
                raise SchemaDriftError(f"vista: {where} has no data-movie-id or film-title")
            branch = item.attributes.get("data-cinema-id")
            if branch is not None and branch.strip() != cinema.branch:
                raise SchemaDriftError(f"vista: {where} belongs to cinema {branch!r}")
            rating_img = item.css_first("img.rating-image")
            rating_src = rating_img.attributes.get("src") if rating_img is not None else None
            rating_match = _RATING.search(rating_src or "")
            sessions = []
            for block in item.css("div.session"):
                heading = _heading_date(_text(block.css_first("h4.session-date")))
                for link in block.css("a.session-time"):
                    sessions.append(VistaAdapter._session(link, heading, cinema, where))
            if len(sessions) != len(links):
                raise SchemaDriftError(f"vista: {where} has session links outside div.session")
            rating = rating_match.group(1) if rating_match else None
            films.append(_Film(key, title, rating, sessions))
        return films

    @staticmethod
    def _session(link: LexborNode, heading: date, cinema: CinemaConfig, where: str) -> _Session:
        query = parse_qs(urlsplit(link.attributes.get("href") or "").query)
        session_id = (query.get("txtSessionId") or [""])[0]
        code = (query.get("cinemacode") or [""])[0]
        if not session_id:
            raise SchemaDriftError(f"vista: {where} session link has no txtSessionId")
        if code and code != cinema.branch:
            raise SchemaDriftError(f"vista: {where} session belongs to cinema {code!r}")
        time = link.css_first("time")
        stamp = time.attributes.get("datetime") if time is not None else None
        try:
            starts_at = datetime.fromisoformat(stamp or "")
        except ValueError as exc:
            raise SchemaDriftError(f"vista: {where} session has no usable datetime") from exc
        if starts_at.tzinfo is not None:
            raise SchemaDriftError("vista: session datetime now carries a time zone")
        # Same day as the heading, or the early hours of the next day (late-night show).
        if starts_at.date() != heading and not (
            starts_at.date() == heading + timedelta(days=1) and starts_at.hour < 6
        ):
            raise SchemaDriftError(
                f"vista: {where} session {stamp} disagrees with its heading {heading}"
            )
        alts = [a for img in link.css("img") if (a := (img.attributes.get("alt") or "").strip())]
        hall, fmt, lang = _classify(alts)
        return _Session(starts_at, session_id, hall, fmt, lang)

    # --- adapter contract --------------------------------------------------------------

    def list_movies(self, ctx: RunContext, cinema: CinemaConfig) -> list[RawMovie]:
        return [
            RawMovie(title=f.title, local_key=f.key, rating=f.rating)
            for f in self._films(ctx, cinema)
        ]

    def list_showtimes(
        self, ctx: RunContext, cinema: CinemaConfig, days: int = 7
    ) -> list[RawShowtime]:
        first_day = pkt_date(ctx.now)
        last_day = first_day + timedelta(days=days)
        shows = []
        for film in self._films(ctx, cinema):
            for s in film.sessions:
                if not first_day <= s.starts_at.date() <= last_day:
                    continue
                shows.append(
                    RawShowtime(
                        movie_title=film.title,
                        movie_local_key=film.key,
                        starts_at=s.starts_at,
                        hall=s.hall,
                        format_text=s.format_text,
                        language_text=s.language_text,
                        external_id=s.session_id,
                        booking_url=build_booking_url(
                            cinema.booking_url_template,
                            branch=cinema.branch,
                            sessionId=s.session_id,
                            filmId=film.key,
                            movieTitle=film.title,
                            cinemaName=cinema.name,
                        ),
                    )
                )
        shows.sort(key=lambda s: (s.starts_at, s.hall or "", s.movie_title))
        return shows

    def fetch_seat_status(
        self, ctx: RunContext, cinema: CinemaConfig, show: ShowRef
    ) -> RawSeats | None:
        """Seats are not published on the listing and seat maps are out of scope
        (``seats_allowed: false``)."""
        return None
