"""Dynamic expiry-date resolver.

Single source of truth for "what is the next NIFTY/BankNifty expiry?".
No weekday is hardcoded — every helper goes through the active feed's
``list_expiries(symbol)`` which reads the broker's instrument dump.
If SEBI moves NIFTY weekly from Tuesday to some other day, the next
``git pull`` of fresh instruments is enough — no code change needed.

The strategy module must always call into this resolver and never
infer expiry dates by counting weekdays.

A small per-symbol per-trading-day cache avoids re-walking the
instrument dump on every 5-min candle scan.
"""

from __future__ import annotations

from calendar import monthrange
from collections import Counter
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.data.base_feed import BaseFeed

IST = ZoneInfo("Asia/Kolkata")

# (broker_name, symbol, cache_date) -> sorted list of future expiries.
_EXPIRY_CACHE: dict[tuple[str, str, date], list[date]] = {}


def _today_ist() -> date:
    return datetime.now(IST).date()


def _is_last_weekday_of_month(d: date) -> bool:
    """True iff no later date in d's month falls on the same weekday."""
    days_in_month = monthrange(d.year, d.month)[1]
    return d.day + 7 > days_in_month


def _detect_pattern(expiries: list[date]) -> str:
    """Derive 'weekly <Day>' vs 'monthly <Day>' from the data alone.

    No weekday is assumed. We pick the modal weekday across the
    upcoming expiries and check expiry-per-month density: if there is
    on average more than one expiry per month, it's weekly; otherwise
    monthly. This way the same logic survives any SEBI weekday change.
    """
    if not expiries:
        return "no upcoming expiries"

    weekday_name = Counter(d.strftime("%A") for d in expiries).most_common(1)[0][0]
    per_month = Counter((d.year, d.month) for d in expiries)
    avg_per_month = sum(per_month.values()) / len(per_month)
    if avg_per_month > 1.5:
        return f"weekly {weekday_name}"
    return f"monthly last-{weekday_name}"


def _normalise_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s not in ("NIFTY", "BANKNIFTY"):
        raise ValueError(f"Unknown symbol '{symbol}', expected NIFTY or BANKNIFTY")
    return s


def get_all_expiries(feed: BaseFeed, symbol: str) -> list[date]:
    """Return sorted list of future expiry dates for ``symbol``.

    Cached per broker / symbol / trading-day. Returns a copy so callers
    can't mutate the cache.
    """
    sym = _normalise_symbol(symbol)
    today = _today_ist()
    key = (feed.get_broker_name(), sym, today)
    if key in _EXPIRY_CACHE:
        return list(_EXPIRY_CACHE[key])

    raw = feed.list_expiries(sym)
    # Defensive — feed might include past dates; drop them.
    future = sorted({d for d in raw if d >= today})
    _EXPIRY_CACHE[key] = future
    return list(future)


def get_next_expiry(
    feed: BaseFeed, symbol: str, after: date | None = None
) -> date:
    """Return the next expiry date for ``symbol`` on or after ``after``.

    Args:
        feed: active BaseFeed implementation.
        symbol: "NIFTY" or "BANKNIFTY".
        after: optional cutoff date. Defaults to today (IST).

    Raises:
        ValueError: no expiry on or after ``after`` is listed.
    """
    cutoff = after if after is not None else _today_ist()
    for d in get_all_expiries(feed, symbol):
        if d >= cutoff:
            return d
    raise ValueError(
        f"No upcoming expiry found for {symbol} on or after {cutoff.isoformat()}"
    )


def get_nth_expiry(feed: BaseFeed, symbol: str, n: int = 0) -> date:
    """Return the n-th upcoming expiry (0 = nearest).

    Raises:
        ValueError: ``n`` is negative or beyond the available expiries.
    """
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    expiries = get_all_expiries(feed, symbol)
    if n >= len(expiries):
        raise ValueError(
            f"Only {len(expiries)} upcoming expiries for {symbol}; cannot return n={n}"
        )
    return expiries[n]


def is_expiry_day(
    feed: BaseFeed, symbol: str, today: date | None = None
) -> bool:
    """Return True iff ``today`` is the nearest expiry for ``symbol``.

    Used by the risk module to apply the expiry-day TP multipliers
    (``risk_reward.expiry_day_tp*_r``) instead of the normal-day ones.
    """
    d = today if today is not None else _today_ist()
    expiries = get_all_expiries(feed, symbol)
    return d in expiries and d == expiries[0]


def get_expiry_summary(feed: BaseFeed) -> dict[str, Any]:
    """Return a debug summary for both NIFTY and BANKNIFTY.

    Shape::

        {
          "NIFTY":     {"next_4_expiries": [...], "weekday_pattern": "weekly Tuesday"},
          "BANKNIFTY": {"next_4_expiries": [...], "weekday_pattern": "monthly last-Tuesday"},
        }

    The ``weekday_pattern`` is DERIVED from the broker's instrument
    dump — not hardcoded.
    """
    summary: dict[str, Any] = {}
    for sym in ("NIFTY", "BANKNIFTY"):
        expiries = get_all_expiries(feed, sym)
        summary[sym] = {
            "next_4_expiries": expiries[:4],
            "weekday_pattern": _detect_pattern(expiries),
        }
    return summary


def clear_cache() -> None:
    """Drop the in-process expiry cache (used by tests and bot restart)."""
    _EXPIRY_CACHE.clear()
