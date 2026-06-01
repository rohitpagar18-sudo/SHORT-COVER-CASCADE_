"""Phase 5B-A — 5-min option-candle cache for completed trading days.

Phase 7's backtest harness will read this cache directly: each file is
a Parquet projection of ``BaseFeed.get_5min_candles`` output for one
``(symbol, strike, option_type, trading_date)`` slice. The format is
intentionally feed-agnostic so Phase 7 doesn't need to know which
broker recorded the day.

Path:

    data/replay_cache/<YYYY-MM-DD>/<SYMBOL>_<STRIKE>_<TYPE>.parquet

Columns: ``timestamp, open, high, low, close, volume, oi`` (oi
optional). Timestamps are timezone-aware IST.

Completion guard
----------------
A trading day is **complete** iff its IST date < today, OR it is today
AND the current IST time is >= ``hard_squareoff_time`` (15:00 default).
We refuse to cache an incomplete day — the file would be stale by
3:00 PM. The caller leaves the alert's ``auto_*`` columns null and
tries again on the next sync.

Cache misses
------------
Old alerts that pre-date this feature have no cached candles and
``BaseFeed.get_5min_candles`` typically only returns ~1.5 trading days
of history. Those alerts simply skip replay — they keep null
``auto_*`` columns. Phase 7's historical-data fetcher (out of scope
for 5B-A) will backfill the cache for older dates using the same path
format.
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

IST = ZoneInfo("Asia/Kolkata")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "replay_cache"

CANDLE_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "oi")


def _cache_path(symbol: str, strike: int, option_type: str, trading_date: date) -> Path:
    return (
        CACHE_DIR
        / trading_date.isoformat()
        / f"{symbol.upper()}_{int(strike)}_{option_type.upper()}.parquet"
    )


def is_day_complete(
    trading_date: date,
    now_ist: datetime | None = None,
    hard_cut: time = time(15, 0),
) -> bool:
    """A day is complete iff before today, or today at/after hard_cut."""
    now = now_ist if now_ist is not None else datetime.now(IST)
    if trading_date < now.date():
        return True
    if trading_date == now.date():
        return now.timetz().replace(tzinfo=None) >= hard_cut
    return False


def read_cached_candles(
    symbol: str, strike: int, option_type: str, trading_date: date
) -> pd.DataFrame | None:
    """Return cached candles for the slice, or None if no cache exists."""
    p = _cache_path(symbol, strike, option_type, trading_date)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        return df
    except Exception as e:
        logger.warning(f"candle_cache: failed to read {p}: {e}")
        return None


def write_cached_candles(
    symbol: str,
    strike: int,
    option_type: str,
    trading_date: date,
    candles: pd.DataFrame,
    *,
    now_ist: datetime | None = None,
    hard_cut: time = time(15, 0),
) -> Path | None:
    """Persist candles for a completed trading day. Returns the path or None.

    Refuses to write if the day isn't complete yet (would-be stale).
    Refuses to write an empty frame.
    """
    if candles is None or candles.empty:
        return None
    if not is_day_complete(trading_date, now_ist=now_ist, hard_cut=hard_cut):
        logger.debug(
            f"candle_cache: refusing to cache {trading_date} — "
            "day not complete yet (current time < hard square-off)"
        )
        return None

    keep_cols = [c for c in CANDLE_COLUMNS if c in candles.columns]
    df = candles[keep_cols].copy()
    p = _cache_path(symbol, strike, option_type, trading_date)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(p, index=False)
    except Exception as e:
        logger.warning(f"candle_cache: failed to write {p}: {e}")
        return None
    return p


def filter_candles_to_date(candles: pd.DataFrame, trading_date: date) -> pd.DataFrame:
    """Slice a multi-day candle frame to one IST trading date.

    Useful because ``BaseFeed.get_5min_candles`` returns 1.5+ days. We
    cache one day at a time so the on-disk format stays Phase-7-friendly.
    """
    if candles is None or candles.empty:
        return candles
    ts = pd.to_datetime(candles["timestamp"])
    return candles[ts.dt.date == trading_date].reset_index(drop=True)


def get_or_fetch_candles(
    feed: Any,
    symbol: str,
    strike: int,
    option_type: str,
    expiry: str,
    trading_date: date,
    *,
    now_ist: datetime | None = None,
    hard_cut: time = time(15, 0),
) -> pd.DataFrame | None:
    """Return candles for the slice from cache, else fetch via feed.

    Args:
        feed: An object implementing ``get_option_chain(symbol, expiry)``
            and ``get_5min_candles(instrument_key, lookback)``.
            Pass ``None`` to disable fetching (read-only mode).
        symbol: NIFTY / BANKNIFTY.
        strike: option strike.
        option_type: "CE" / "PE".
        expiry: ISO date string of the contract expiry.
        trading_date: the alert's IST trading date.

    Returns:
        DataFrame of that day's 5-min candles, or None if cache miss
        and feed unavailable, or the day isn't complete yet.
    """
    cached = read_cached_candles(symbol, strike, option_type, trading_date)
    if cached is not None and not cached.empty:
        return cached

    if feed is None:
        return None
    if not is_day_complete(trading_date, now_ist=now_ist, hard_cut=hard_cut):
        return None

    # Resolve the broker's instrument key for this specific option.
    try:
        chain = feed.get_option_chain(symbol, expiry)
    except Exception as e:
        logger.warning(
            f"candle_cache: get_option_chain({symbol}, {expiry}) failed: {e}"
        )
        return None
    if chain is None or chain.empty:
        return None

    key_col = "ce_instrument_key" if option_type.upper() == "CE" else "pe_instrument_key"
    if key_col not in chain.columns or "strike" not in chain.columns:
        logger.warning(
            f"candle_cache: chain for {symbol}/{expiry} missing "
            f"'{key_col}' or 'strike' column"
        )
        return None
    row = chain[chain["strike"] == int(strike)]
    if row.empty:
        return None
    instrument_key = row.iloc[0][key_col]

    try:
        # ~80 candles covers a full 09:15-15:30 session; ask for 200 to
        # be safe across weekends / partial sessions.
        full = feed.get_5min_candles(instrument_key, lookback_candles=200)
    except Exception as e:
        logger.warning(
            f"candle_cache: get_5min_candles failed for "
            f"{symbol}/{strike}{option_type}: {e}"
        )
        return None

    day_candles = filter_candles_to_date(full, trading_date)
    if day_candles.empty:
        return None

    write_cached_candles(
        symbol,
        strike,
        option_type,
        trading_date,
        day_candles,
        now_ist=now_ist,
        hard_cut=hard_cut,
    )
    return day_candles
