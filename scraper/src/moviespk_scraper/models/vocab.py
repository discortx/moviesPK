"""Shared vocabularies, written by hand to match ``shared/constants/*.json``.

Contract tests assert each tuple below equals its JSON list (plan §13). A change here
must be made in ``shared/constants`` and ``api/src/schemas`` in the same PR.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

Format = Literal["2D", "3D", "IMAX", "4DX", "OTHER"]
SeatStatusValue = Literal["available", "filling", "sold_out", "unknown"]
MatchStatus = Literal["matched", "provisional", "unmatched"]
RunStatus = Literal["ok", "partial", "failed", "blocked", "drift"]
HealthStatus = Literal["ok", "partial", "failed", "blocked", "drift", "unknown"]
Job = Literal["full", "seats", "canary"]
ShowtimeStatus = Literal["active", "cancelled"]
AliasSource = Literal["auto", "manual", "pending"]
RadiusKm = Literal[5, 10, 25, 50]
Genre = Literal[
    "action",
    "adventure",
    "animation",
    "comedy",
    "crime",
    "documentary",
    "drama",
    "family",
    "fantasy",
    "history",
    "horror",
    "music",
    "mystery",
    "romance",
    "science-fiction",
    "thriller",
    "war",
    "western",
    "other",
]
Language = Literal["ur", "en", "pa", "hi", "ps", "sd", "other"]

RESERVED_PATHS: Final = (
    "about",
    "privacy",
    "status",
    "search",
    "near-me",
    "movies",
    "cinemas",
    "api",
)
POSTER_WIDTHS: Final = (185, 342, 780)
POSTER_KEY_PATTERN: Final = r"^movies/[0-9a-f]{24}/poster-[0-9a-f]{8}$"

# Pakistan bounding box (plan §8.1).
MIN_LNG: Final = 60.8
MAX_LNG: Final = 77.9
MIN_LAT: Final = 23.6
MAX_LAT: Final = 37.1

#: Maps each ``shared/constants`` file stem to the values this module declares.
VOCABULARIES: Final[dict[str, tuple[object, ...]]] = {
    "formats": get_args(Format),
    "seat-statuses": get_args(SeatStatusValue),
    "match-statuses": get_args(MatchStatus),
    "run-statuses": get_args(RunStatus),
    "health-statuses": get_args(HealthStatus),
    "jobs": get_args(Job),
    "showtime-statuses": get_args(ShowtimeStatus),
    "alias-sources": get_args(AliasSource),
    "radius-km": get_args(RadiusKm),
    "genres": get_args(Genre),
    "languages": get_args(Language),
    "reserved-paths": RESERVED_PATHS,
}
