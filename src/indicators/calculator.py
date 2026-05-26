"""Bundles all indicators for a single DataFrame into one snapshot."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.indicators.moving_averages import (
    compute_oi_ma,
    compute_rsi_ma,
    compute_volume_ma,
)
from src.indicators.rsi import compute_rsi_wilder
from src.indicators.vwap import compute_session_vwap


@dataclass
class IndicatorSnapshot:
    """All indicator values for the LATEST candle in a DataFrame."""

    vwap: float
    rsi: float
    rsi_ma: float
    oi: float
    oi_ma: float
    volume: float
    volume_ma: float
    close: float
    open: float
    high: float
    low: float
    timestamp: pd.Timestamp
    is_green: bool


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a new DataFrame with vwap, rsi, rsi_ma, oi_ma, volume_ma columns.

    VWAP is computed via ``compute_session_vwap`` on the full input
    DataFrame so that it respects the 09:15 IST session reset. Callers
    must NOT slice ``df`` before passing it in — the session VWAP needs
    every candle from session start.

    Input is not modified.
    """
    out = df.copy()
    out["vwap"] = compute_session_vwap(out)
    out["rsi"] = compute_rsi_wilder(out["close"])
    out["rsi_ma"] = compute_rsi_ma(out["rsi"])
    out["oi_ma"] = compute_oi_ma(out)
    out["volume_ma"] = compute_volume_ma(out)
    return out


def get_latest_snapshot(df: pd.DataFrame) -> IndicatorSnapshot:
    """Return IndicatorSnapshot for the last row of ``df``.

    VWAP is computed on the FULL session DataFrame (must include every
    candle since 09:15 IST). RSI and the moving averages only need
    ~33 candles of lookback, but they are also computed on ``df``
    directly — this is correct as long as ``df`` is at least 33 rows
    long. Each indicator is computed independently and combined into
    the snapshot.

    Raises ValueError if the latest row has NaN in any indicator —
    typically because fewer than 33 candles are available (need 14 for
    RSI plus 20 for RSI MA).
    """
    if len(df) == 0:
        raise ValueError("Cannot build snapshot from empty DataFrame.")

    vwap_series = compute_session_vwap(df)
    rsi_series = compute_rsi_wilder(df["close"])
    rsi_ma_series = compute_rsi_ma(rsi_series)
    oi_ma_series = compute_oi_ma(df)
    volume_ma_series = compute_volume_ma(df)

    latest_vwap = vwap_series.iloc[-1]
    latest_rsi = rsi_series.iloc[-1]
    latest_rsi_ma = rsi_ma_series.iloc[-1]
    latest_oi_ma = oi_ma_series.iloc[-1]
    latest_volume_ma = volume_ma_series.iloc[-1]

    missing = [
        name for name, value in (
            ("vwap", latest_vwap),
            ("rsi", latest_rsi),
            ("rsi_ma", latest_rsi_ma),
            ("oi_ma", latest_oi_ma),
            ("volume_ma", latest_volume_ma),
        )
        if pd.isna(value)
    ]
    if missing:
        raise ValueError(
            f"Insufficient lookback for indicators {missing}; "
            f"need at least 33 candles (have {len(df)})."
        )

    last = df.iloc[-1]
    return IndicatorSnapshot(
        vwap=float(latest_vwap),
        rsi=float(latest_rsi),
        rsi_ma=float(latest_rsi_ma),
        oi=float(last["oi"]),
        oi_ma=float(latest_oi_ma),
        volume=float(last["volume"]),
        volume_ma=float(latest_volume_ma),
        close=float(last["close"]),
        open=float(last["open"]),
        high=float(last["high"]),
        low=float(last["low"]),
        timestamp=last["timestamp"],
        is_green=bool(last["close"] > last["open"]),
    )
