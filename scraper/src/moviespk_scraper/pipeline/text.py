"""Text normalization shared by the normalizer and the showtime ID (plan §10.3 step 2)."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize_text(value: str | None) -> str:
    """NFKC, trim and collapse whitespace. ``None`` becomes ``""``."""
    if value is None:
        return ""
    return _WS.sub(" ", unicodedata.normalize("NFKC", value)).strip()
