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
    """VWAP for today's session only, anchored at 09:15 IST.

    Multi-day input is safe: this function filters to the calendar date
    of the most recent candle in ``df`` BEFORE computing VWAP, so that
    a multi-day frame (now returned by ``get_5min_candles`` for RSI MA
    lookback) does not pollute today's VWAP with prior-day data.

    Args:
        df: DataFrame with ``timestamp`` column (timezone-aware IST) plus
            high/low/close/volume.
        session_start_hour: hour at which a new session begins (24h).
        session_start_minute: minute at which a new session begins.

    Returns:
        pd.Series aligned with df.index. Rows from today's session carry
        the running VWAP value; rows from earlier sessions are NaN.
        Callers that only need the latest VWAP (``.iloc[-1]``) get
        today's value since today's last candle is the final row.
    """
    if len(df) == 0:
        return pd.Series([], dtype=float, index=df.index)

    ts = pd.to_datetime(df["timestamp"])
    minutes_since_midnight = ts.dt.hour * 60 + ts.dt.minute
    session_open_minutes = session_start_hour * 60 + session_start_minute
    pre_session_mask = minutes_since_midnight < session_open_minutes
    session_date = ts.dt.date.where(
        ~pre_session_mask, (ts - pd.Timedelta(days=1)).dt.date
    )

    # "Today" = the session date of the most recent candle in the frame.
    latest_session_date = session_date.iloc[-1]
    today_mask = session_date.values == latest_session_date

    out = pd.Series(np.nan, index=df.index, dtype=float)
    today_idx = df.index[today_mask]
    if len(today_idx) == 0:
        return out
    today_df = df.loc[today_idx]
    out.loc[today_idx] = compute_vwap_hlc3(today_df).values
    return out
