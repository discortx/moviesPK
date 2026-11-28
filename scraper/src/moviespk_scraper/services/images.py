"""Poster image step (plan §10.3 step 5a, §11.3, P1-23).

For each matched movie touched in a run, at most once per run, and only when it has no
poster, its TMDB data was refreshed this run, or `--rebuild-images` is set:

1. Download the TMDB `w780` poster (TMDB throttle, 10 s, JPEG/PNG/WebP, ≤ 5 MB).
2. Process with Pillow: pixel limit, decode, RGB, metadata stripped; widths 185, 342, 780
   (aspect kept, never upscaled); WebP quality 80.
3. `hash8` = first 8 hex characters of SHA-256 of the w780 WebP bytes; key stem
   `movies/{movieId}/poster-{hash8}`.
4. Stem equal to `movies.poster.key` → stop (no R2 call), unless rebuilding. Otherwise
   HEAD each variant and PUT the missing ones (1 MB and 200-per-run caps, `services/r2.py`).
5. Only after all three variants exist: `movies.poster = {key, width, height}` (w780 size)
   and `showtimes.movie.posterKey`. Old objects become orphans for the monthly cleanup.
6. Any failure is logged and counted (`imagesFailed`); the previous poster is kept; the
   cinema run never fails because of an image.
"""

from __future__ import annotations

import hashlib
import io
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from bson import ObjectId
from PIL import Image, UnidentifiedImageError
from structlog.typing import FilteringBoundLogger

from ..core.logging import get_logger
from ..db import repositories as repo
from ..db.client import DB
from .r2 import R2Error, R2Store, UploadCapReached
from .tmdb import TmdbClient, TmdbError

WIDTHS = (185, 342, 780)
WEBP_QUALITY = 80
#: Decompression-bomb guard: no TMDB poster is anywhere near this (w780 is about 780 x 1170).
MAX_PIXELS = 20_000_000

Outcome = Literal["uploaded", "unchanged", "skipped", "failed"]


class PosterProcessingError(Exception):
    pass


@dataclass(frozen=True)
class Processed:
    variants: dict[int, bytes]  # width label → WebP bytes
    width: int  # actual size of the w780 variant
    height: int
    hash8: str

    def stem(self, movie_id: str) -> str:
        return f"movies/{movie_id}/poster-{self.hash8}"


def process_poster(data: bytes) -> Processed:
    """Decode, strip metadata, resize to the three widths and encode WebP."""
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as src:
            if src.width * src.height > MAX_PIXELS:
                raise PosterProcessingError("poster is too large to decode safely")
            src.load()
            rgb = src.convert("RGB")  # drops alpha and palette; new image has no metadata
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise PosterProcessingError(f"cannot decode poster: {type(exc).__name__}") from exc

    variants: dict[int, bytes] = {}
    size_780 = (0, 0)
    for width in WIDTHS:
        if rgb.width > width:  # never upscale
            height = max(1, round(rgb.height * width / rgb.width))
            img = rgb.resize((width, height), Image.Resampling.LANCZOS)
        else:
            img = rgb
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=WEBP_QUALITY)  # no exif/icc passed → none kept
        variants[width] = out.getvalue()
        if width == 780:
            size_780 = img.size
    digest = hashlib.sha256(variants[780]).hexdigest()
    return Processed(variants, size_780[0], size_780[1], digest[:8])


@dataclass
class ImageCounts:
    uploaded: int = 0
    failed: int = 0


@dataclass
class ImageStep:
    """One per run; shared by the cinema threads."""

    tmdb: TmdbClient
    store: R2Store
    db: DB
    rebuild: bool = False
    log: FilteringBoundLogger = field(default_factory=get_logger)
    on_cap_reached: Any = None  # callable() → None, called once per run
    _done: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _image_base: str | None = None
    _cap_reported: bool = False

    def _base(self) -> str:
        if self._image_base is None:
            self._image_base = self.tmdb.configuration().image_base_url
        return self._image_base

    def poster_for(
        self,
        movie_id: str,
        tmdb_id: int,
        poster_path: str | None,
        current_key: str | None,
        now: datetime,
    ) -> tuple[Outcome, int]:
        """Run steps 1-5 for one movie. Returns (outcome, PUT count). Never raises."""
        with self._lock:
            if movie_id in self._done:
                return "skipped", 0
            self._done.add(movie_id)
        log = self.log.bind(phase="images", movieId=movie_id)
        try:
            if poster_path is None:
                poster_path = self.tmdb.movie_details(tmdb_id).poster_path
            if poster_path is None:
                log.info("images.no_poster", tmdbId=tmdb_id)
                return "skipped", 0
            processed = process_poster(self.tmdb.download_poster(self._base(), poster_path))
            stem = processed.stem(movie_id)
            if stem == current_key and not self.rebuild:
                log.info("images.unchanged", key=stem)
                return "unchanged", 0
            puts = 0
            for width in WIDTHS:
                if self.store.ensure(f"{stem}-w{width}.webp", processed.variants[width]):
                    puts += 1
            self._store_key(movie_id, stem, processed, now)
            log.info(
                "images.stored",
                key=stem,
                uploads=puts,
                bytes=sum(len(b) for b in processed.variants.values()),
            )
            return "uploaded", puts
        except UploadCapReached:
            self._report_cap()
            log.warning("images.cap_reached")
            return "failed", 0
        except (TmdbError, PosterProcessingError, R2Error) as exc:
            log.warning("images.failed", error=type(exc).__name__, detail=str(exc)[:200])
            return "failed", 0

    def _store_key(self, movie_id: str, stem: str, processed: Processed, now: datetime) -> None:
        oid = ObjectId(movie_id)
        self.db[repo.MOVIES].update_one(
            {"_id": oid},
            {
                "$set": {
                    "poster": {"key": stem, "width": processed.width, "height": processed.height},
                    "updatedAt": now,
                }
            },
        )
        self.db[repo.SHOWTIMES].update_many({"movieId": oid}, {"$set": {"movie.posterKey": stem}})

    def _report_cap(self) -> None:
        with self._lock:
            if self._cap_reported:
                return
            self._cap_reported = True
        if self.on_cap_reached is not None:
            self.on_cap_reached()
