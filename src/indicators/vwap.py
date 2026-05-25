"""Session-anchored VWAP using hlc3.

Confirmed source: Upstox chart label "VWAP hlc3 Session".
Many internet examples use close-only; that is WRONG for this strategy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_vwap_hlc3(df: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP using hlc3 = (high + low + close) / 3.

    Args:
        df: DataFrame with columns [high, low, close, volume]. Optional
            ``timestamp`` column is not consulted — caller must ensure the
            frame is a single session (use ``compute_session_vwap`` for
            multi-day data).

    Returns:
        pd.Series of VWAP values, same index as df.
        First row's VWAP = first row's hlc3.

    Edge cases:
        - Cumulative volume == 0 → fall back to hlc3 for that row.
        - Empty DataFrame → empty Series (float).
    """
    if len(df) == 0:
        return pd.Series([], dtype=float, index=df.index)

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    hlc3 = (high + low + close) / 3.0

    cum_pv = (hlc3 * volume).cumsum()
    cum_v = volume.cumsum()

    vwap = np.where(cum_v > 0, cum_pv / cum_v.replace(0, np.nan), hlc3)
    return pd.Series(vwap, index=df.index, dtype=float)


def compute_session_vwap(
    df: pd.DataFrame,
    session_start_hour: int = 9,
    session_start_minute: int = 15,
) -> pd.Series:
    """VWAP that resets at each session start (default 09:15 IST).

    Args:
        df: DataFrame with ``timestamp`` column (timezone-aware IST) plus
            high/low/close/volume.
        session_start_hour: hour at which a new session begins (24h).
        session_start_minute: minute at which a new session begins.

    Returns:
        pd.Series of VWAP values aligned with df.index. VWAP resets on
        each candle whose timestamp's calendar date differs from the prior
        candle's session date. "Session date" is the calendar date of
        timestamps at or after the session start time; timestamps before
        the session start map to the previous calendar date (rare for
        intraday equity options, but kept correct for completeness).
    """
    if len(df) == 0:
        return pd.Series([], dtype=float, index=df.index)

    ts = pd.to_datetime(df["timestamp"])
    minutes_since_midnight = ts.dt.hour * 60 + ts.dt.minute
    session_open_minutes = session_start_hour * 60 + session_start_minute
    pre_session_mask = minutes_since_midnight < session_open_minutes
    session_date = ts.dt.date.where(~pre_session_mask, (ts - pd.Timedelta(days=1)).dt.date)

    out = pd.Series(np.nan, index=df.index, dtype=float)
    for _, group_idx in pd.Series(session_date.values, index=df.index).groupby(session_date.values, sort=False).groups.items():
        sub = df.loc[group_idx]
        out.loc[group_idx] = compute_vwap_hlc3(sub).values
    return out
