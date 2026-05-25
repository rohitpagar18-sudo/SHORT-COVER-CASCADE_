# Phase 2 — Indicator Calculations

**Goal:** Implement VWAP (hlc3), Wilder's RSI(14), OI MA(20), Volume MA(20),
and RSI MA(20) — all matching Upstox/TradingView chart values within
calibration tolerance.

**Time estimate:** 2 hours code + 30 min live calibration.

**Output:**
- Pure functions in `src/indicators/` that take a DataFrame and return values
- All match real Upstox chart values within tolerance
- A calibration script `scripts/check_indicators.py` that fetches live
  candles for any strike and prints current indicator values
- Comprehensive unit tests using the 5 real candles from
  `docs/known_indicator_values.md`

**What Phase 2 does NOT do:**
- No condition logic (Phase 3 — uses these indicators)
- No alerts (Phase 5)
- No order placement (Phase 8)

---

## STEP 1 — One quick BANKNIFTY ATM verification (60 seconds)

Before starting Phase 2 work, confirm BANKNIFTY ATM also works on
Machine 2:

```cmd
cd C:\Users\rohit\OneDrive\Desktop\trading\SHORT-COVER-CASCADE_
call venv\Scripts\activate.bat
python -c "from src.config_loader import load_config; from src.data.feed_factory import connect_feed; cfg = load_config('config/config.yaml'); feed = connect_feed(cfg); print('BANKNIFTY ATM:', feed.get_atm_strike('BANKNIFTY'))"
```

Expected: a number ending in 00 (e.g. 55300), close to current spot.
If this works, Phase 1 is fully cleared.

---

## STEP 2 — Paste this prompt into Claude Code (Machine 1)

```cmd
cd C:\trading\short-cover-cascade
claude
```

Paste the entire block below:

````
Read CLAUDE.md fully. Then read docs/phases/PHASE_2.md.
Also read docs/known_indicator_values.md — these are the test fixtures
you must match.

Current phase: Phase 2 — Indicator Calculations.

CRITICAL INSTRUCTION: If any file already exists, OVERWRITE it completely.
Do not skip, do not merge — overwrite.

CRITICAL CORRECTNESS RULES:
1. VWAP uses (H+L+C)/3, NOT close-only. Many internet examples are wrong.
2. RSI uses Wilder's smoothing (RMA), NOT SMA or EMA.
3. OI MA, Volume MA, RSI MA are all Simple MA (SMA), NOT EMA.
4. All functions are PURE — same input always gives same output, no side
   effects, no state, no logging inside the math.
5. Functions never raise on insufficient data — they return None or NaN
   for rows that lack lookback, and the caller decides what to do.

--- TASK 1: Create src/indicators/vwap.py ---

import pandas as pd
import numpy as np

def compute_vwap_hlc3(df: pd.DataFrame) -> pd.Series:
    """
    Session-anchored VWAP using hlc3.
    
    Args:
        df: DataFrame with columns [timestamp, open, high, low, close, volume]
            timestamp must be timezone-aware IST (Asia/Kolkata)
            Data must be from a single trading session (single date).
            If df spans multiple sessions, caller must split first.
    
    Returns:
        pd.Series of VWAP values, same index as df.
        First row's VWAP = first row's hlc3 (cumsum starts there).
    
    Formula:
        hlc3 = (high + low + close) / 3
        vwap[i] = sum(hlc3[0..i] * volume[0..i]) / sum(volume[0..i])
    
    Edge cases:
        - If any row has volume == 0, that row contributes 0 to numerator
          but 0 to denominator too. Skip-zero handling: if cumulative
          volume is 0, return hlc3 for that row.
        - If df is empty, return empty Series.
    """

def compute_session_vwap(df: pd.DataFrame, session_start_hour: int = 9, 
                         session_start_minute: int = 15) -> pd.Series:
    """
    Wrapper for multi-day data. Groups by session date and computes
    VWAP independently within each session.
    A new session starts at session_start (default 09:15 IST).
    
    Args:
        df: same as compute_vwap_hlc3, but may span multiple sessions
    Returns:
        pd.Series of VWAP values, VWAP resets at each session start.
    """

--- TASK 2: Create src/indicators/rsi.py ---

import pandas as pd
import numpy as np

def compute_rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI(14) using Wilder's smoothing (RMA).
    Matches TradingView and Upstox chart RSI exactly.
    
    Args:
        close: pd.Series of closing prices (float)
        period: RSI period, default 14
    
    Returns:
        pd.Series of RSI values (0-100), same index as close.
        First `period` rows are NaN (insufficient lookback).
    
    Formula:
        change = close.diff()
        gain = change.where(change > 0, 0.0)
        loss = -change.where(change < 0, 0.0)
        
        # Wilder's smoothing: alpha = 1/period
        avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        # Handle division by zero: when avg_loss == 0, RSI = 100
    
    Edge cases:
        - avg_loss == 0 → RSI = 100
        - avg_gain == 0 → RSI = 0
        - Both 0 → RSI = 50 (neutral)
        - close has < period+1 values → all NaN
    """

--- TASK 3: Create src/indicators/moving_averages.py ---

import pandas as pd

def compute_sma(series: pd.Series, period: int = 20) -> pd.Series:
    """
    Simple Moving Average. Used for OI MA, Volume MA, RSI MA.
    
    Args:
        series: pd.Series of numeric values
        period: window size, default 20
    
    Returns:
        pd.Series same index as input, first (period-1) rows are NaN.
    
    Implementation: series.rolling(window=period, min_periods=period).mean()
    """

def compute_oi_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Convenience wrapper: SMA on df['oi'] column with default period 20."""

def compute_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Convenience wrapper: SMA on df['volume'] column with default period 20."""

def compute_rsi_ma(rsi_series: pd.Series, period: int = 20) -> pd.Series:
    """Convenience wrapper: SMA on RSI values with default period 20."""

--- TASK 4: Create src/indicators/__init__.py ---

Re-export everything for clean imports:

from src.indicators.vwap import compute_vwap_hlc3, compute_session_vwap
from src.indicators.rsi import compute_rsi_wilder
from src.indicators.moving_averages import (
    compute_sma, compute_oi_ma, compute_volume_ma, compute_rsi_ma
)

__all__ = [
    "compute_vwap_hlc3",
    "compute_session_vwap",
    "compute_rsi_wilder",
    "compute_sma",
    "compute_oi_ma",
    "compute_volume_ma",
    "compute_rsi_ma",
]

--- TASK 5: Create src/indicators/calculator.py ---

This is the convenience class that the orchestrator (Phase 5) will use.
It bundles all indicators for one DataFrame in one call.

from dataclasses import dataclass
import pandas as pd
from src.indicators.vwap import compute_session_vwap
from src.indicators.rsi import compute_rsi_wilder
from src.indicators.moving_averages import compute_oi_ma, compute_volume_ma, compute_rsi_ma

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
    is_green: bool                  # close > open
    
def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds vwap, rsi, rsi_ma, oi_ma, volume_ma columns to df.
    Returns a NEW DataFrame, does not modify input.
    """

def get_latest_snapshot(df: pd.DataFrame) -> IndicatorSnapshot:
    """
    Calls compute_all_indicators(df), takes last row, returns
    IndicatorSnapshot. Raises ValueError if last row has NaN in any
    indicator (insufficient lookback — need at least 33 candles for
    RSI MA: 14 for RSI + 20 for RSI MA = 33 minimum).
    """

--- TASK 6: Unit tests ---

Create tests/test_indicators.py.

Use the 5 candles from docs/known_indicator_values.md as fixtures.
Since we don't have full OHLCV time series for those screenshots,
build test cases like this:

# Test 1: VWAP formula verification with synthetic but precise data
def test_vwap_hlc3_simple():
    # 3 candles, easy math
    df = pd.DataFrame({
        'high':   [100, 110, 120],
        'low':    [ 90, 100, 110],
        'close':  [ 95, 105, 115],
        'volume': [1000, 2000, 3000],
    })
    # hlc3 = [95, 105, 115]
    # numerator: 95*1000 + 105*2000 + 115*3000 = 95000 + 210000 + 345000 = 650000
    # denominator: 1000 + 2000 + 3000 = 6000
    # vwap[2] = 650000 / 6000 = 108.333...
    vwap = compute_vwap_hlc3(df)
    assert vwap.iloc[0] == pytest.approx(95.0)
    assert vwap.iloc[1] == pytest.approx(100.0)  # (95000+210000)/3000
    assert vwap.iloc[2] == pytest.approx(108.333, abs=0.01)

# Test 2: VWAP rejects close-only mistake
def test_vwap_uses_hlc3_not_close():
    df = pd.DataFrame({
        'high':   [110],
        'low':    [ 90],
        'close':  [100],
        'volume': [1000],
    })
    # If using close-only: vwap = 100
    # If using hlc3: vwap = (110+90+100)/3 = 100
    # Same here by coincidence. Force divergence:
    df = pd.DataFrame({
        'high':   [120, 130],
        'low':    [ 80,  90],
        'close':  [100, 110],
        'volume': [1000, 1000],
    })
    # hlc3 = [100, 110]
    # close-only would also = [100, 110] → still same. Need asymmetric high/low.
    df = pd.DataFrame({
        'high':   [150, 200],   # high much higher than close
        'low':    [ 90, 100],
        'close':  [100, 110],
        'volume': [1000, 1000],
    })
    # hlc3 = [(150+90+100)/3, (200+100+110)/3] = [113.33, 136.67]
    # close-only would give [100, 105]
    # → these differ, so VWAP must reflect hlc3
    vwap = compute_vwap_hlc3(df)
    assert vwap.iloc[1] > 120  # Must be > close-only result of ~105

# Test 3: Wilder RSI baseline values
def test_rsi_wilder_known_series():
    # Use a known series with hand-verified RSI(14) values
    # Wikipedia RSI example (canonical reference):
    closes = pd.Series([
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
        45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
        46.03, 46.41, 46.22, 45.64,
    ])
    rsi = compute_rsi_wilder(closes, period=14)
    # Expected RSI at index 14 (15th value) ≈ 70.46 per Wilder's reference
    # Allow ±0.5 tolerance for implementation variants
    assert rsi.iloc[14] == pytest.approx(70.46, abs=0.5)

# Test 4: SMA basic
def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    ma = compute_sma(s, period=3)
    assert pd.isna(ma.iloc[0])
    assert pd.isna(ma.iloc[1])
    assert ma.iloc[2] == pytest.approx(2.0)
    assert ma.iloc[3] == pytest.approx(3.0)
    assert ma.iloc[4] == pytest.approx(4.0)

# Test 5: Negative test — C2 fails (OI above MA) using Candle 4 values
def test_c2_negative_oi_above_ma():
    # Candle 4 from known_indicator_values.md:
    # OI = 987k, OI MA(20) = 938k → OI above MA → C2 must fail
    # We test the comparison logic that Phase 3 will use:
    oi = 987_000
    oi_ma = 938_000
    assert not (oi < oi_ma), "OI is above MA, C2 should fail"

# Test 6: Positive test — C2 valid using Candle 2 values
def test_c2_positive_oi_below_ma():
    # Candle 2: OI = 4.51M, OI MA(20) = 11.2M → OI below MA → C2 valid
    oi = 4_510_000
    oi_ma = 11_200_000
    assert oi < oi_ma, "OI is below MA, C2 should pass"

# Test 7: RSI MA SMA over RSI values
def test_rsi_ma_is_sma():
    rsi_values = pd.Series([50, 52, 54, 56, 58, 60, 62, 64, 66, 68,
                            70, 72, 74, 76, 78, 80, 82, 84, 86, 88])
    rsi_ma = compute_rsi_ma(rsi_values, period=20)
    # SMA of 50..88 (step 2) = average of arithmetic progression = 69
    assert rsi_ma.iloc[19] == pytest.approx(69.0)

# Test 8: Empty DataFrame handling
def test_vwap_empty_df():
    df = pd.DataFrame({'high':[], 'low':[], 'close':[], 'volume':[]})
    result = compute_vwap_hlc3(df)
    assert len(result) == 0

# Test 9: IndicatorSnapshot raises on insufficient data
def test_snapshot_insufficient_data():
    # Only 10 candles → RSI(14) can't compute → should raise
    df = pd.DataFrame({
        'timestamp': pd.date_range('2026-05-25 09:15', periods=10, freq='5min', tz='Asia/Kolkata'),
        'open':   [100]*10, 'high': [101]*10, 'low': [99]*10,
        'close':  [100]*10, 'volume': [1000]*10, 'oi': [500_000]*10,
    })
    with pytest.raises(ValueError):
        get_latest_snapshot(df)

# Test 10: IndicatorSnapshot returns valid values on sufficient data
def test_snapshot_sufficient_data():
    # 35 candles → enough for RSI MA(20 over RSI(14))
    n = 35
    df = pd.DataFrame({
        'timestamp': pd.date_range('2026-05-25 09:15', periods=n, freq='5min', tz='Asia/Kolkata'),
        'open':   [100 + i*0.1 for i in range(n)],
        'high':   [101 + i*0.1 for i in range(n)],
        'low':    [ 99 + i*0.1 for i in range(n)],
        'close':  [100 + i*0.1 for i in range(n)],
        'volume': [1000 + i*10 for i in range(n)],
        'oi':     [500_000 + i*1000 for i in range(n)],
    })
    snap = get_latest_snapshot(df)
    assert snap.vwap > 0
    assert 0 <= snap.rsi <= 100
    assert snap.rsi_ma > 0
    assert snap.oi_ma > 0
    assert snap.volume_ma > 0
    assert snap.is_green is True  # close > open trend

Run pytest tests/ -v after writing. All 10 tests must pass.

--- TASK 7: Create scripts/check_indicators.py (calibration script) ---

This is the manual calibration tool. You run it during market hours,
it fetches live candles for an option strike, prints all indicators,
and you visually compare to the Kite chart.

import argparse
from datetime import datetime
from src.config_loader import load_config
from src.data.feed_factory import connect_feed
from src.indicators.calculator import compute_all_indicators, get_latest_snapshot

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=["NIFTY", "BANKNIFTY"], required=True)
    parser.add_argument("--strike", type=int, required=True,
                        help="Strike price, e.g. 24500")
    parser.add_argument("--option-type", choices=["CE", "PE"], required=True)
    parser.add_argument("--expiry", required=True,
                        help="Expiry date YYYY-MM-DD")
    parser.add_argument("--candles", type=int, default=50,
                        help="Number of recent candles to fetch (default 50)")
    args = parser.parse_args()
    
    config = load_config("config/config.yaml")
    feed = connect_feed(config)
    
    # Get option chain to find the instrument_key for this strike
    chain = feed.get_option_chain(args.symbol, args.expiry)
    row = chain[
        (chain["strike"] == args.strike) &
        (chain["instrument_type"] == args.option_type)
    ]
    if len(row) == 0:
        print(f"ERROR: Strike {args.strike}{args.option_type} not found in {args.symbol} {args.expiry} chain")
        return 1
    
    instrument_key = row.iloc[0]["instrument_key"] if "instrument_key" in row.columns else row.iloc[0]["instrument_token"]
    
    print(f"Fetching {args.candles} candles for {args.symbol} {args.strike}{args.option_type} expiry {args.expiry}...")
    df = feed.get_5min_candles(str(instrument_key), args.candles)
    print(f"Fetched {len(df)} candles, latest timestamp: {df['timestamp'].iloc[-1]}")
    
    print()
    print("Last 5 candles:")
    print(df.tail(5).to_string(index=False))
    print()
    
    snap = get_latest_snapshot(df)
    print("=" * 60)
    print(f"  Latest indicators for {args.symbol} {args.strike}{args.option_type}")
    print("=" * 60)
    print(f"  Timestamp    : {snap.timestamp}")
    print(f"  OHLC         : {snap.open:.2f} / {snap.high:.2f} / {snap.low:.2f} / {snap.close:.2f}")
    print(f"  Candle color : {'GREEN' if snap.is_green else 'RED'}")
    print(f"  VWAP (hlc3)  : {snap.vwap:.2f}    ({'ABOVE' if snap.close > snap.vwap else 'BELOW'})")
    print(f"  RSI(14)      : {snap.rsi:.2f}")
    print(f"  RSI MA(20)   : {snap.rsi_ma:.2f}    (RSI {'ABOVE' if snap.rsi > snap.rsi_ma else 'BELOW'} MA)")
    print(f"  OI           : {snap.oi:,.0f}")
    print(f"  OI MA(20)    : {snap.oi_ma:,.0f}    (OI  {'BELOW' if snap.oi < snap.oi_ma else 'ABOVE'} MA)")
    print(f"  Volume       : {snap.volume:,.0f}")
    print(f"  Volume MA(20): {snap.volume_ma:,.0f}    (Vol {'ABOVE' if snap.volume > snap.volume_ma else 'BELOW'} MA)")
    print("=" * 60)
    print()
    print("Now open the same strike on Kite chart and verify these values match within:")
    print("  VWAP: ±0.5%   RSI: ±2 points   MAs: ±1%")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

After writing all files, run:
  pytest tests/ -v

All tests must pass.

Report:
  1. Exact pytest output (test counts, any failures)
  2. Confirm src/indicators/ contains vwap.py, rsi.py, moving_averages.py,
     calculator.py, __init__.py
  3. Confirm scripts/check_indicators.py is callable (just run it with
     --help and confirm the args display)
````

---

## STEP 3 — Live Calibration (Machine 2, during market hours)

This is the most important Phase 2 step — you visually confirm bot values
match Kite chart values.

**You can do this any market day between 9:30 AM and 3:00 PM IST.**

### Setup (one-time)

Find a live NIFTY strike near ATM. On Machine 2:

```cmd
:: First fresh Kite token for today
python scripts\refresh_token_kite.py

:: Find current ATM
python scripts\feed_healthcheck.py
:: → note the ATM strike from output, e.g. 24050
```

### Run the calibration

Pick the upcoming weekly expiry date (find it on Kite web — usually Tuesday).
Example: if today is 27 May 2026 and expiry is 29 May 2026:

```cmd
python scripts\check_indicators.py --symbol NIFTY --strike 24050 --option-type CE --expiry 2026-05-29
```

The script will print all indicator values for the latest 5-min candle.

### Visual comparison with Kite

1. Open Kite Web → Charts → search NIFTY24050CE → 5-min timeframe
2. Add indicators: **VWAP**, **RSI(14)** with MA(20), **OI** with MA(20), **Volume** with MA(20)
3. Look at the **most recent completed candle**
4. Compare each value:

| Bot value | Kite chart value | Tolerance | Pass/Fail |
|---|---|---|---|
| VWAP | VWAP (hlc3) | ±0.5% | |
| RSI | RSI(14) | ±2 points | |
| RSI MA | RSI MA(20) | ±1% | |
| OI MA | OI MA(20) | ±1% | |
| Volume MA | Volume MA(20) | ±1% | |

If all 5 within tolerance → Phase 2 calibration ✅

### What to do if values don't match

Send me:
1. Bot output (full text)
2. Screenshot of the Kite chart for the same strike, same candle
3. The exact candle timestamp

We diagnose together. The most common issue:
- **VWAP too low/high**: candle count too short (try `--candles 100`)
- **RSI off by 5+ points**: smoothing method wrong (we'd be using EMA instead of Wilder)
- **OI shows 0**: Kite's intraday OI endpoint returning zeros for that strike — try a different strike with higher OI

---

## STEP 4 — Repeat calibration for all 4 combinations

To confirm the bot works for ALL the cases your strategy alerts on:

```cmd
:: 1. NIFTY CE near ATM
python scripts\check_indicators.py --symbol NIFTY --strike <atm> --option-type CE --expiry <expiry>

:: 2. NIFTY PE near ATM
python scripts\check_indicators.py --symbol NIFTY --strike <atm> --option-type PE --expiry <expiry>

:: 3. BANKNIFTY CE near ATM
python scripts\check_indicators.py --symbol BANKNIFTY --strike <atm> --option-type CE --expiry <expiry>

:: 4. BANKNIFTY PE near ATM
python scripts\check_indicators.py --symbol BANKNIFTY --strike <atm> --option-type PE --expiry <expiry>
```

For each, verify VWAP/RSI/MAs match Kite chart within tolerance.

If all 4 strikes calibrate cleanly → **Phase 2 fully verified.**

---

## STEP 5 — Verification Checklist

| # | Check | Pass condition |
|---|---|---|
| 1 | `pytest tests/ -v` runs all green | 0 failures across 10 tests |
| 2 | `python scripts\check_indicators.py --help` works | Argparse usage prints |
| 3 | Calibration: NIFTY CE values match Kite within tolerance | All 5 indicators within range |
| 4 | Calibration: NIFTY PE values match Kite | Same |
| 5 | Calibration: BANKNIFTY CE values match Kite | Same |
| 6 | Calibration: BANKNIFTY PE values match Kite | Same |
| 7 | VWAP uses hlc3 (not close-only) | test_vwap_uses_hlc3_not_close passes |
| 8 | Negative test C2 logic | test_c2_negative passes (OI above MA fails) |
| 9 | Positive test C2 logic | test_c2_positive passes (OI below MA works) |

Minimum to call Phase 2 done: checks 1, 2, 7, 8, 9 plus at least
**one** live calibration (#3 or #5) passing. The other strikes can be
verified later.

---

## When you confirm Phase 2 done, send me

1. Full pytest output (test count + pass/fail breakdown)
2. Full output of ONE calibration run (e.g. NIFTY CE)
3. Confirmation that those values match your Kite chart (or screenshot of
   any mismatch)
4. Anything weird Claude Code did

---

## What Phase 3 will build (preview)

Once Phase 2 calibrates:

- `src/conditions/c0_spot_trend.py` — C0 filter
- `src/conditions/c1_option_price_vwap.py` — C1 logic
- `src/conditions/c2_oi_below_ma.py` — C2 logic
- `src/conditions/c3_rsi_momentum.py` — C3 logic
- `src/conditions/c4_volume.py` — C4 logic
- All pure functions returning `(bool, reason_str)`
- A `scripts/check_conditions.py` that runs all 5 conditions on a
  given strike and tells you why each passes or fails

Phase 3 doesn't send alerts yet — that's Phase 5. But after Phase 3 you can
manually run the script during market and see which strikes would have
triggered alerts.

**End of Phase 2.**
