"""Normalizer (plan §10.3 step 2, P1-07): raw adapter rows → clean, typed rows.

* Text: NFKC, trimmed, whitespace collapsed (``pipeline/text.py``). Non-Latin titles (Urdu)
  are kept as they are, apart from NFKC.
* Titles: format, language and age markers are moved out of the title into fields:
  ``"Dune (IMAX) [Urdu]"`` → title ``Dune``, format ``IMAX``, language ``ur``;
  ``"18+Belkis (Turkish Urdu Dubbed)"`` → ``Belkis``, certification ``18+``, language ``ur``.
  A bracket is removed only when **every** word in it is a known marker, so
  ``"Mission: Impossible (The Final Reckoning)"`` keeps its subtitle.
* Format: the cinema's own format field wins, then a title marker; none at all → ``2D``;
  unrecognized text → ``OTHER`` (logged).
* Language: a dubbed language wins ("Turkish Urdu Dubbed" → Urdu); subtitle languages are
  never the spoken language; languages outside the vocabulary → ``other``; nothing → ``other``
  (logged), since a showtime must carry one.
* Genres: mapped to ``shared/constants/genres.json``; unknown → ``other`` (logged).
* Times: a naive time is cinema-local PKT; everything becomes aware UTC. A show's date is
  the PKT calendar date of its ``startsAt`` (the adapter already supplies the real date).
* Hall: text rules applied; missing, ``None``, empty or whitespace-only → ``""`` (§8.1).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import get_args

from structlog.typing import FilteringBoundLogger

from ..adapters.base import RawMovie, RawShowtime
from ..core.clock import PKT
from ..models.vocab import Format, Genre, Language
from .ids import canonical_hall
from .text import normalize_text

# --- vocabularies -----------------------------------------------------------------------

FORMATS: dict[str, Format] = {
    "2d": "2D",
    "3d": "3D",
    "imax": "IMAX",
    "imax 2d": "IMAX",
    "imax 3d": "IMAX",
    "4dx": "4DX",
    "4dx 3d": "4DX",
}

LANGUAGES: dict[str, Language] = {
    "urdu": "ur",
    "english": "en",
    "eng": "en",
    "punjabi": "pa",
    "hindi": "hi",
    "pashto": "ps",
    "pushto": "ps",
    "sindhi": "sd",
}
#: Language names that are real languages but outside the vocabulary → ``other``.
OTHER_LANGUAGES = frozenset(
    {
        "turkish",
        "chinese",
        "mandarin",
        "cantonese",
        "japanese",
        "japanes",  # as published by Cinepax ("Japanes With Eng Subtitles")
        "korean",
        "arabic",
        "persian",
        "farsi",
        "french",
        "spanish",
        "german",
        "italian",
        "russian",
        "tamil",
        "telugu",
        "malayalam",
        "bengali",
        "indonesian",
        "thai",
    }
)
DUBBED = frozenset({"dubbed", "dub", "dubbing"})
SUBTITLED = frozenset({"subtitle", "subtitles", "subtitled", "sub", "subs"})
MARKER_WORDS = (
    frozenset(w for key in FORMATS for w in key.split())
    | frozenset(LANGUAGES)
    | OTHER_LANGUAGES
    | DUBBED
    | SUBTITLED
    | frozenset({"version", "with"})
)

GENRES: dict[str, Genre] = {g: g for g in get_args(Genre)}
GENRES.update(
    {
        "sci-fi": "science-fiction",
        "scifi": "science-fiction",
        "science fiction": "science-fiction",
        "animated": "animation",
        "romantic": "romance",
        "biography": "history",
        "historical": "history",
        "musical": "music",
        "suspense": "thriller",
        "kids": "family",
        "children": "family",
    }
)

_BRACKET = re.compile(r"\s*[(\[]([^()\[\]]*)[)\]]\s*")
_AGE_ONLY = re.compile(r"^\s*(\d{1,2}\s*\+)\s*", re.I)
_TRAILING_FORMAT = re.compile(r"\s+(2D|3D|IMAX|4DX)\s*$", re.I)
_WORD = re.compile(r"[\w+-]+", re.UNICODE)
_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_WS = re.compile(r"\s+")


# --- titles -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedTitle:
    title: str
    formats: tuple[Format, ...] = ()
    languages: tuple[Language, ...] = ()  # spoken languages, dubbed first
    certification: str | None = None
    unknown_markers: tuple[str, ...] = ()


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _is_marker_group(words: list[str]) -> bool:
    return bool(words) and all(w in MARKER_WORDS for w in words)


def _marker_languages(words: list[str]) -> list[Language]:
    """Spoken languages named in one marker group, dubbed language first."""
    if any(w in SUBTITLED for w in words):
        # "Japanese English Subtitle": the word before "subtitle" is the subtitle
        # language, which is never the spoken one; anything before it still counts.
        idx = next(i for i, w in enumerate(words) if w in SUBTITLED)
        return _marker_languages_spoken(words[: max(0, idx - 1)])
    return _marker_languages_spoken(words)


def _marker_languages_spoken(words: list[str]) -> list[Language]:
    if any(w in DUBBED for w in words):
        idx = next(i for i, w in enumerate(words) if w in DUBBED)
        before = [w for w in words[:idx] if w in LANGUAGES or w in OTHER_LANGUAGES]
        if before:  # "Turkish Urdu Dubbed" → dubbed into Urdu
            dubbed = before[-1]
            return [LANGUAGES.get(dubbed, "other")]
    langs: list[Language] = []
    for w in words:
        code: Language | None = LANGUAGES.get(w) or ("other" if w in OTHER_LANGUAGES else None)
        if code and code not in langs:
            langs.append(code)
    return langs


def parse_title(raw_title: str) -> ParsedTitle:
    """Split format, language and age markers out of a listed title."""
    text = normalize_text(raw_title)
    certification: str | None = None
    age = _AGE_ONLY.match(text)
    if age:
        certification = age.group(1).replace(" ", "")
        text = text[age.end() :]

    formats: list[Format] = []
    languages: list[Language] = []

    def take(match: re.Match[str]) -> str:
        words = _words(match.group(1))
        if not _is_marker_group(words):
            return match.group(0)  # a real part of the title, e.g. "(The Final Reckoning)"
        joined = " ".join(w for w in words if w not in DUBBED | SUBTITLED | LANGUAGES.keys())
        for key in sorted(FORMATS, key=len, reverse=True):
            if re.search(rf"\b{re.escape(key)}\b", joined):
                fmt = FORMATS[key]
                if fmt not in formats:
                    formats.append(fmt)
                break
        for lang in _marker_languages(words):
            if lang not in languages:
                languages.append(lang)
        return " "

    text = _BRACKET.sub(take, text)
    trailing = _TRAILING_FORMAT.search(text)
    if trailing:
        fmt = FORMATS[trailing.group(1).lower()]
        if fmt not in formats:
            formats.append(fmt)
        text = text[: trailing.start()]
    title = normalize_text(text)
    return ParsedTitle(
        title=title or normalize_text(raw_title),
        formats=tuple(formats),
        languages=tuple(languages),
        certification=certification,
    )


def title_key(title: str) -> str:
    """Matching key (plan §10.4 step 1): lowercase, punctuation removed, spaces collapsed.
    Letters of every script are kept."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    return _WS.sub(" ", _NON_WORD.sub(" ", folded)).strip()


# --- fields -------------------------------------------------------------------------------


def to_utc(starts_at: datetime) -> datetime:
    """Naive → PKT; any aware time → UTC, to the second."""
    aware = starts_at.replace(tzinfo=PKT) if starts_at.tzinfo is None else starts_at
    return aware.astimezone(UTC).replace(microsecond=0)


def map_format(text: str | None, log: FilteringBoundLogger | None = None) -> Format | None:
    key = normalize_text(text).lower()
    if not key:
        return None
    if key in FORMATS:
        return FORMATS[key]
    if log is not None:
        log.info("normalize.unknown_format", value=key)
    return "OTHER"


def map_language(text: str | None) -> Language | None:
    words = _words(normalize_text(text))
    langs = _marker_languages(words)
    return langs[0] if langs else None


def map_genres(
    values: tuple[str, ...], log: FilteringBoundLogger | None = None
) -> tuple[Genre, ...]:
    out: list[Genre] = []
    for value in values:
        for part in re.split(r"[,/|]+", normalize_text(value).lower()):
            part = part.strip()
            if not part:
                continue
            genre = GENRES.get(part) or GENRES.get(part.replace(" ", "-"))
            if genre is None:
                if log is not None:
                    log.info("normalize.unknown_genre", value=part)
                genre = "other"
            if genre not in out:
                out.append(genre)
    return tuple(out)


# --- rows -------------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedMovie:
    title: str
    title_key: str
    local_key: str | None
    original_title: str | None
    runtime_min: int | None
    genres: tuple[Genre, ...]
    languages: tuple[Language, ...]
    synopsis: str | None
    release_date: date | None
    year: int | None
    certification: str | None


@dataclass(frozen=True)
class NormalizedShowtime:
    movie_title: str
    title_key: str
    movie_local_key: str | None
    starts_at: datetime  # aware UTC
    hall: str  # "" when missing (the canonical form used by the showtime ID)
    format: Format
    language: Language
    booking_url: str | None
    external_id: str | None
    seats_available: int | None
    seats_total: int | None
    notes: tuple[str, ...] = field(default=())


def normalize_movie(raw: RawMovie, log: FilteringBoundLogger | None = None) -> NormalizedMovie:
    parsed = parse_title(raw.title)
    languages = list(parsed.languages)
    for lang_text in raw.languages:
        lang = map_language(lang_text)
        if lang and lang not in languages:
            languages.append(lang)
    original = normalize_text(raw.original_title) or None
    return NormalizedMovie(
        title=parsed.title,
        title_key=title_key(parsed.title),
        local_key=normalize_text(raw.local_key) or None,
        original_title=original,
        runtime_min=raw.runtime_min,
        genres=map_genres(raw.genres, log),
        languages=tuple(languages),
        synopsis=normalize_text(raw.synopsis) or None,
        release_date=raw.release_date,
        year=raw.release_date.year if raw.release_date else None,
        certification=normalize_text(raw.rating) or parsed.certification,
    )


def normalize_showtime(
    raw: RawShowtime, log: FilteringBoundLogger | None = None
) -> NormalizedShowtime:
    parsed = parse_title(raw.movie_title)
    notes: list[str] = []
    fmt = map_format(raw.format_text, log) or (parsed.formats[0] if parsed.formats else None)
    if fmt is None:
        fmt = "2D"
        notes.append("format defaulted to 2D")
    language = map_language(raw.language_text) or (
        parsed.languages[0] if parsed.languages else None
    )
    if language is None:
        language = "other"
        notes.append("language unknown")
        if log is not None:
            log.info("normalize.unknown_language", title=parsed.title)
    return NormalizedShowtime(
        movie_title=parsed.title,
        title_key=title_key(parsed.title),
        movie_local_key=normalize_text(raw.movie_local_key) or None,
        starts_at=to_utc(raw.starts_at),
        hall=canonical_hall(raw.hall),
        format=fmt,
        language=language,
        booking_url=normalize_text(raw.booking_url) or None,
        external_id=normalize_text(raw.external_id) or None,
        seats_available=raw.seats_available,
        seats_total=raw.seats_total,
        notes=tuple(notes),
    )
