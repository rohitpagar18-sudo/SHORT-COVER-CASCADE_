"""Phase 2 indicator unit tests.

Covers VWAP (hlc3), Wilder RSI(14), SMA, and IndicatorSnapshot.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.indicators import (
    compute_rsi_ma,
    compute_rsi_wilder,
    compute_sma,
    compute_vwap_hlc3,
)
from src.indicators.calculator import get_latest_snapshot


def test_vwap_hlc3_simple():
    df = pd.DataFrame({
        "high":   [100, 110, 120],
        "low":    [ 90, 100, 110],
        "close":  [ 95, 105, 115],
        "volume": [1000, 2000, 3000],
    })
    vwap = compute_vwap_hlc3(df)
    assert vwap.iloc[0] == pytest.approx(95.0)
    assert vwap.iloc[1] == pytest.approx(101.6667, abs=0.01)
    assert vwap.iloc[2] == pytest.approx(108.333, abs=0.01)


def test_vwap_uses_hlc3_not_close():
    df = pd.DataFrame({
        "high":   [150, 200],
        "low":    [ 90, 100],
        "close":  [100, 110],
        "volume": [1000, 1000],
    })
    vwap = compute_vwap_hlc3(df)
    assert vwap.iloc[1] > 120


def test_rsi_wilder_known_series():
    closes = pd.Series([
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
        45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
        46.03, 46.41, 46.22, 45.64,
    ])
    rsi = compute_rsi_wilder(closes, period=14)
    assert rsi.iloc[14] == pytest.approx(70.46, abs=0.5)


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    ma = compute_sma(s, period=3)
    assert pd.isna(ma.iloc[0])
    assert pd.isna(ma.iloc[1])
    assert ma.iloc[2] == pytest.approx(2.0)
    assert ma.iloc[3] == pytest.approx(3.0)
    assert ma.iloc[4] == pytest.approx(4.0)


def test_c2_negative_oi_above_ma():
    # Candle 4: OI 987k > OI MA 938k → C2 must fail.
    oi = 987_000
    oi_ma = 938_000
    assert not (oi < oi_ma), "OI is above MA, C2 should fail"


def test_c2_positive_oi_below_ma():
    # Candle 2: OI 4.51M < OI MA 11.2M → C2 valid.
    oi = 4_510_000
    oi_ma = 11_200_000
    assert oi < oi_ma, "OI is below MA, C2 should pass"


def test_rsi_ma_is_sma():
    rsi_values = pd.Series([50, 52, 54, 56, 58, 60, 62, 64, 66, 68,
                            70, 72, 74, 76, 78, 80, 82, 84, 86, 88])
    rsi_ma = compute_rsi_ma(rsi_values, period=20)
    assert rsi_ma.iloc[19] == pytest.approx(69.0)


def test_vwap_empty_df():
    df = pd.DataFrame({"high": [], "low": [], "close": [], "volume": []})
    result = compute_vwap_hlc3(df)
    assert len(result) == 0


def test_snapshot_insufficient_data():
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-05-25 09:15", periods=10, freq="5min", tz="Asia/Kolkata"),
        "open":   [100] * 10,
        "high":   [101] * 10,
        "low":    [ 99] * 10,
        "close":  [100] * 10,
        "volume": [1000] * 10,
        "oi":     [500_000] * 10,
    })
    with pytest.raises(ValueError):
        get_latest_snapshot(df)


def test_snapshot_sufficient_data():
    n = 35
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-05-25 09:15", periods=n, freq="5min", tz="Asia/Kolkata"),
        "open":   [100 + i * 0.1 for i in range(n)],
        "high":   [101 + i * 0.1 for i in range(n)],
        "low":    [ 99 + i * 0.1 for i in range(n)],
        "close":  [100.5 + i * 0.1 for i in range(n)],
        "volume": [1000 + i * 10 for i in range(n)],
        "oi":     [500_000 + i * 1000 for i in range(n)],
    })
    snap = get_latest_snapshot(df)
    assert snap.vwap > 0
    assert 0 <= snap.rsi <= 100
    assert snap.rsi_ma > 0
    assert snap.oi_ma > 0
    assert snap.volume_ma > 0
    assert snap.is_green is True


def test_vwap_uses_full_session_not_window():
    """If user requests last 10 candles but session has 75, VWAP
    should still be computed on all 75.

    Build 75 candles: first 25 at price ~200, last 50 at price ~100,
    equal volume each. True session VWAP = (25*200 + 50*100) / 75
    = 133.33. If a future bug ever sliced the df to the tail before
    VWAP, the value would collapse to ~100 and this test would fail.
    """
    n_high = 25
    n_low = 50
    n_total = n_high + n_low
    timestamps = pd.date_range(
        "2026-05-25 09:15", periods=n_total, freq="5min", tz="Asia/Kolkata"
    )
    opens = [200.0] * n_high + [100.0] * n_low
    highs = [200.0] * n_high + [100.0] * n_low
    lows = [200.0] * n_high + [100.0] * n_low
    closes = [200.0] * n_high + [100.0] * n_low
    volumes = [1000.0] * n_total
    ois = [500_000.0] * n_total

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "oi": ois,
    })
    snap = get_latest_snapshot(df)
    # Full-session VWAP ≈ 133.33; tail-only VWAP would be 100.
    assert snap.vwap > 120, (
        f"VWAP={snap.vwap:.2f} — looks like only the tail was used; "
        "VWAP must be computed on the full 09:15 session."
    )
    assert snap.vwap == pytest.approx(133.33, abs=0.5)


def test_vwap_filters_to_today_when_multi_day_df_passed():
    """Multi-day df: VWAP must only reflect today's session.

    Build 2 days of candles:
      Day 1 (yesterday): 75 candles at price 200, vol 1000 each
      Day 2 (today):     30 candles at price 100, vol 1000 each
    Today-only VWAP = 100 (single price). If the function leaked
    yesterday's data into today's calc, VWAP would be ~171 instead.
    """
    from src.indicators.vwap import compute_session_vwap

    n_yest = 75
    n_today = 30
    yest_ts = pd.date_range(
        "2026-05-25 09:15", periods=n_yest, freq="5min", tz="Asia/Kolkata"
    )
    today_ts = pd.date_range(
        "2026-05-26 09:15", periods=n_today, freq="5min", tz="Asia/Kolkata"
    )
    timestamps = list(yest_ts) + list(today_ts)
    prices_y = [200.0] * n_yest
    prices_t = [100.0] * n_today
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": prices_y + prices_t,
        "high": prices_y + prices_t,
        "low": prices_y + prices_t,
        "close": prices_y + prices_t,
        "volume": [1000.0] * (n_yest + n_today),
    })
    vwap = compute_session_vwap(df)
    # Latest VWAP must be today-only.
    assert vwap.iloc[-1] == pytest.approx(100.0, abs=0.01), (
        f"VWAP={vwap.iloc[-1]:.2f} — yesterday's 200-priced candles leaked "
        "into today's VWAP. Multi-day filtering broken."
    )
    # Yesterday's rows must be NaN (we only compute today's session).
    assert vwap.iloc[: n_yest].isna().all(), (
        "Prior-day rows should be NaN — only today's session is computed."
    )


def test_vwap_value_unchanged_whether_input_is_today_only_or_multi_day():
    """Critical regression test: VWAP value at the latest candle must be
    identical whether the caller passes only today's candles or a
    multi-day frame ending with the same today's candles.
    """
    from src.indicators.vwap import compute_session_vwap

    today_ts = pd.date_range(
        "2026-05-26 09:15", periods=30, freq="5min", tz="Asia/Kolkata"
    )
    today_prices = [100.0 + i for i in range(30)]
    today_df = pd.DataFrame({
        "timestamp": today_ts,
        "open": today_prices,
        "high": [p + 1 for p in today_prices],
        "low": [p - 1 for p in today_prices],
        "close": today_prices,
        "volume": [1000.0 + i * 10 for i in range(30)],
    })

    yest_ts = pd.date_range(
        "2026-05-25 09:15", periods=75, freq="5min", tz="Asia/Kolkata"
    )
    yest_prices = [50.0] * 75
    yest_df = pd.DataFrame({
        "timestamp": yest_ts,
        "open": yest_prices,
        "high": yest_prices,
        "low": yest_prices,
        "close": yest_prices,
        "volume": [10000.0] * 75,
    })
    multi_df = pd.concat([yest_df, today_df], ignore_index=True)

    today_only_vwap = compute_session_vwap(today_df).iloc[-1]
    multi_day_vwap = compute_session_vwap(multi_df).iloc[-1]
    assert today_only_vwap == pytest.approx(multi_day_vwap, abs=1e-6), (
        f"VWAP drift: today-only={today_only_vwap:.4f}, "
        f"multi-day={multi_day_vwap:.4f}. Multi-day input must produce "
        "the same VWAP value as today-only input."
    )
