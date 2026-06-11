"""IST time helpers. All datetimes in this API are IST (Asia/Kolkata).

Never use naive datetimes or UTC anywhere in the API.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date as date_cls
from typing import Optional


IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date_cls:
    return now_ist().date()


def parse_ist(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string (with or without tz) into an IST datetime.
    Returns None on any failure — callers must handle None.
    """
    if not s or not isinstance(s, str):
        return None
    try:
        # fromisoformat handles +05:30 offsets natively
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (ValueError, TypeError):
        return None


def fmt_ist(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(IST).isoformat()


def is_market_open(dt: Optional[datetime] = None) -> bool:
    """Rough IST market-hours check: Mon-Fri 09:15–15:30. Holidays NOT honored
    here — this is a coarse UI hint, not a trading guard.
    """
    dt = dt or now_ist()
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    return (t.hour, t.minute) >= (9, 15) and (t.hour, t.minute) <= (15, 30)
