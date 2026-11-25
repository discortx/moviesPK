"""Pakistan time (plan §10.3 step 2).

Pakistan Standard Time is UTC+05:00 with no daylight saving (none since 2009), so a fixed
offset is exact and needs no time-zone database (Windows has none by default).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

PKT = timezone(timedelta(hours=5), "PKT")


def pkt_date(moment: datetime) -> date:
    """The PKT calendar date of an aware datetime."""
    if moment.tzinfo is None:
        raise ValueError("an aware datetime is required")
    return moment.astimezone(PKT).date()
