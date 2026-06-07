"""ADX(14) + directional indicators (+DI / -DI) on a SPOT OHLC series.

Phase 6.1 — used by the shadow C5 ADX trend filter.

Smoothing note: this implementation uses pandas
``ewm(alpha=1/period, adjust=False)`` to approximate Wilder's RMA. It
differs from canonical Wilder seeding (which begins with a simple mean of
the first ``period`` values, then applies the Wilder recursion) by a few
points in the first ~2*period rows. For a 150-candle multi-day fetch that
warm-up has long since washed out, so the latest ADX should land within
~3 points of TradingView/Kite's ADX(14). The calibration test in
``tests/test_indicators.py`` pins this against a real chart fixture; if
that test ever drifts outside ±4 points, the follow-up is to swap in true
Wilder seeding (same pattern as ``src/indicators/rsi.py``).

Source series: the SPOT INDEX 5-min candles fetched multi-day. ADX is a
rolling indicator and must NOT be session-anchored — computing it on
today's 5-10 candles makes it meaningless at session open. The caller
slices the trailing ``lookback_candles`` from the multi-day frame and
passes that in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdxSnapshot:
    """Latest closed-candle ADX / DI values plus the prior ADX.

    ``ok=False`` means insufficient data (fewer than ~2*period usable rows
    or any NaN at the tail). Callers must treat that as "C5 ❌ insufficient
    data" — never as a pass.
    """

    ok: bool
    adx: float
    adx_prev: float
    di_plus: float
    di_minus: float
    period: int
    rows_used: int
    reason: str = ""


def compute_adx_di(df: pd.DataFrame, period: int = 14) -> tuple[
    pd.Series, pd.Series, pd.Series
]:
    """Return (adx, di_plus, di_minus) Series aligned with df.index.

    Wilder-style smoothing via ``ewm(alpha=1/period, adjust=False)``. See
    module docstring for the canonical-Wilder caveat.

    Args:
        df: DataFrame with columns ``high``, ``low``, ``close``. Index/
            order is the time order of the candles. Multi-day OK — the
            ADX is rolling, not session-anchored.
        period: ADX period, default 14.

    Returns:
        Tuple ``(adx, di_plus, di_minus)`` each a pd.Series. Early rows
        are NaN until the smoothing has enough lookback. +DI/−DI scale
        is 0-100. ADX scale is 0-100.

    Edge cases:
        - +DI + −DI == 0 (no movement) → DX = 0 for that row, so ADX
          smooths toward 0 cleanly. Never divides by zero.
        - Empty / too-short df → empty or all-NaN Series.
    """
    n = len(df)
    if n == 0:
        empty = pd.Series([], dtype=float, index=df.index)
        return empty, empty.copy(), empty.copy()

    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = df["close"].astype(float).to_numpy()

    prev_close = np.concatenate(([np.nan], close[:-1]))
    prev_high = np.concatenate(([np.nan], high[:-1]))
    prev_low = np.concatenate(([np.nan], low[:-1]))

    # True Range
    tr1 = high - low
    tr2 = np.abs(high - prev_close)
    tr3 = np.abs(low - prev_close)
    tr = np.nanmax(np.vstack([tr1, tr2, tr3]), axis=0)
    tr[0] = np.nan  # first row has no prev close

    # Directional movement
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm[0] = np.nan
    minus_dm[0] = np.nan

    tr_s = pd.Series(tr, index=df.index, dtype=float)
    plus_dm_s = pd.Series(plus_dm, index=df.index, dtype=float)
    minus_dm_s = pd.Series(minus_dm, index=df.index, dtype=float)

    # Wilder-approx smoothing
    sm_tr = tr_s.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    sm_plus = plus_dm_s.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    sm_minus = minus_dm_s.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    # +DI / -DI
    di_plus = 100.0 * sm_plus / sm_tr.replace(0.0, np.nan)
    di_minus = 100.0 * sm_minus / sm_tr.replace(0.0, np.nan)

    di_sum = di_plus + di_minus
    dx = pd.Series(
        np.where(di_sum.to_numpy() > 0,
                 100.0 * np.abs(di_plus.to_numpy() - di_minus.to_numpy())
                 / np.where(di_sum.to_numpy() == 0, np.nan, di_sum.to_numpy()),
                 0.0),
        index=df.index,
        dtype=float,
    )

    # ADX = Wilder-smoothed DX
    adx = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    return adx, di_plus, di_minus


def get_latest_adx_snapshot(
    df: pd.DataFrame, period: int = 14, lookback_candles: int = 150,
) -> AdxSnapshot:
    """Compute the trailing ADX snapshot from ``df``.

    Slices the last ``lookback_candles`` rows of ``df`` (so a 600-candle
    multi-day frame still produces a stable rolling ADX), then computes
    +DI/-DI/ADX on that window. Returns the values at the last fully
    closed candle plus the prior ADX.

    Args:
        df: SPOT 5-min OHLC frame, multi-day, sorted by time ascending.
        period: ADX period.
        lookback_candles: how many trailing rows to use. Must be large
            enough that ADX is past its warm-up — at least ~2*period
            usable rows after the first ``period`` are dropped to NaN.

    Returns:
        ``AdxSnapshot``. On insufficient data ``ok=False`` and ``reason``
        explains why. Caller MUST treat ``ok=False`` as a non-passing
        condition and never as a default pass.
    """
    if df is None or len(df) == 0:
        return AdxSnapshot(False, 0.0, 0.0, 0.0, 0.0, period, 0,
                           "empty candle frame")

    need = 2 * period
    if len(df) < need:
        return AdxSnapshot(False, 0.0, 0.0, 0.0, 0.0, period, len(df),
                           f"only {len(df)} rows, need >= {need}")

    if lookback_candles > 0 and len(df) > lookback_candles:
        window = df.iloc[-lookback_candles:]
    else:
        window = df

    adx, di_plus, di_minus = compute_adx_di(window, period=period)

    if len(adx) < 2:
        return AdxSnapshot(False, 0.0, 0.0, 0.0, 0.0, period, len(window),
                           "not enough rows after slicing")

    adx_last = adx.iloc[-1]
    adx_prev = adx.iloc[-2]
    dip_last = di_plus.iloc[-1]
    dim_last = di_minus.iloc[-1]

    if any(pd.isna(x) for x in (adx_last, adx_prev, dip_last, dim_last)):
        return AdxSnapshot(False, 0.0, 0.0, 0.0, 0.0, period, len(window),
                           "ADX/DI NaN at tail — still warming up")

    return AdxSnapshot(
        ok=True,
        adx=float(adx_last),
        adx_prev=float(adx_prev),
        di_plus=float(dip_last),
        di_minus=float(dim_last),
        period=period,
        rows_used=len(window),
        reason="",
    )
