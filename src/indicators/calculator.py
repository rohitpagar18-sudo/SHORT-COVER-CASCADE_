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

    Raises ValueError if the latest row has NaN in any indicator —
    typically because fewer than 33 candles are available (need 14 for
    RSI plus 20 for RSI MA).
    """
    enriched = compute_all_indicators(df)
    last = enriched.iloc[-1]

    required = ["vwap", "rsi", "rsi_ma", "oi_ma", "volume_ma"]
    missing = [col for col in required if pd.isna(last[col])]
    if missing:
        raise ValueError(
            f"Insufficient lookback for indicators {missing}; "
            f"need at least 33 candles (have {len(df)})."
        )

    return IndicatorSnapshot(
        vwap=float(last["vwap"]),
        rsi=float(last["rsi"]),
        rsi_ma=float(last["rsi_ma"]),
        oi=float(last["oi"]),
        oi_ma=float(last["oi_ma"]),
        volume=float(last["volume"]),
        volume_ma=float(last["volume_ma"]),
        close=float(last["close"]),
        open=float(last["open"]),
        high=float(last["high"]),
        low=float(last["low"]),
        timestamp=last["timestamp"],
        is_green=bool(last["close"] > last["open"]),
    )
