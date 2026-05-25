"""Simple moving averages for OI, Volume, and RSI."""

from __future__ import annotations

import pandas as pd


def compute_sma(series: pd.Series, period: int = 20) -> pd.Series:
    """Simple Moving Average.

    Args:
        series: numeric input.
        period: window size, default 20.

    Returns:
        pd.Series same index as input; first ``period - 1`` rows are NaN.
    """
    return series.astype(float).rolling(window=period, min_periods=period).mean()


def compute_oi_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """SMA over df['oi']."""
    return compute_sma(df["oi"], period=period)


def compute_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """SMA over df['volume']."""
    return compute_sma(df["volume"], period=period)


def compute_rsi_ma(rsi_series: pd.Series, period: int = 20) -> pd.Series:
    """SMA over RSI values."""
    return compute_sma(rsi_series, period=period)
