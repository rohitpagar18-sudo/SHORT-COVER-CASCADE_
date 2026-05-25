"""Wilder's RSI implementation (matches TradingView/Upstox exactly).

Uses canonical Wilder smoothing: the first ``period`` average is a
Simple Moving Average of gains/losses, after which the recursion
``avg = (prior_avg * (period - 1) + new_value) / period`` is applied.
This matches TradingView and Upstox chart RSI exactly. The pandas
``ewm(alpha=1/period, adjust=False)`` shortcut is a close approximation
but its EMA initialisation drifts from canonical Wilder by ~1-2 points
for the first several values, so we implement Wilder directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI(period) using Wilder's smoothing (RMA).

    Args:
        close: pd.Series of closing prices.
        period: RSI period, default 14.

    Returns:
        pd.Series of RSI values (0-100), same index as close.
        First ``period`` rows are NaN (insufficient lookback).

    Edge cases:
        - avg_loss == 0 → RSI = 100
        - avg_gain == 0 → RSI = 0
        - Both 0 → RSI = 50 (neutral)
        - len(close) < period + 1 → all NaN
    """
    close = close.astype(float)
    n = len(close)
    rsi = pd.Series(np.nan, index=close.index, dtype=float)
    if n < period + 1:
        return rsi

    change = close.diff().to_numpy()
    gains = np.where(change > 0, change, 0.0)
    losses = np.where(change < 0, -change, 0.0)

    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)

    avg_gain[period] = gains[1 : period + 1].mean()
    avg_loss[period] = losses[1 : period + 1].mean()

    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period

    values = np.full(n, np.nan)
    for i in range(period, n):
        g, l = avg_gain[i], avg_loss[i]
        if np.isnan(g) or np.isnan(l):
            continue
        if g == 0 and l == 0:
            values[i] = 50.0
        elif l == 0:
            values[i] = 100.0
        elif g == 0:
            values[i] = 0.0
        else:
            rs = g / l
            values[i] = 100.0 - (100.0 / (1.0 + rs))

    rsi.iloc[:] = values
    return rsi
