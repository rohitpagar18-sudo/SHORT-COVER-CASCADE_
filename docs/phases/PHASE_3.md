# Phase 3 — Conditions C0–C4 + Dynamic Expiry Helper

**Goal:** Implement the 5 strategy conditions as pure functions, plus a
dynamic expiry-date resolver that pulls real expiries from the broker
instead of hardcoding day-of-week rules. After Phase 3 you can ask the
bot "would this strike trigger an alert right now?" and get a clean
yes/no with reason.

**Time estimate:** 2 hours code + 30 min live verification.

**Output:**
- 5 pure functions: `c0_spot_trend`, `c1_option_price_vwap`,
  `c2_oi_below_ma`, `c3_rsi_momentum`, `c4_volume`
- 1 dynamic expiry helper: `get_next_expiry(symbol)` reads from broker
- `scripts/check_conditions.py` — runs all 5 conditions on a live strike
  and prints which pass/fail with reasons
- `scripts/list_expiries.py` — lists all NIFTY/BankNifty expiries from
  broker (source of truth)
- Comprehensive unit tests using the candle data from
  `docs/known_indicator_values.md`

**What Phase 3 does NOT do:**
- No alerts yet (Phase 5)
- No order placement (Phase 8)
- No orchestration / candle-close loop (Phase 5)
- No risk/SL/lot sizing (Phase 4)

---

## STEP 1 — Paste this prompt into Claude Code (Machine 1)

```cmd
cd C:\trading\short-cover-cascade
claude
```

Paste the entire block below:

````
Read CLAUDE.md fully. Then read docs/ShortCoverCascade_v3_1_FINAL.md
Section 5 "THE 5 CONDITIONS" — that section is the SPECIFICATION for
this phase. Do not invent rules. Do not change thresholds. Read it.

Current phase: Phase 3 — Conditions + Dynamic Expiry Helper.

CRITICAL INSTRUCTION: If any file already exists, OVERWRITE it. Use the
load_secrets() helper before load_config() in all scripts.

CRITICAL CORRECTNESS RULES:
1. Every condition function is PURE — takes an IndicatorSnapshot (or
   minimal primitives) and returns (bool, reason_str). No I/O, no logging
   inside the math, no side effects.
2. The reason_str must explain BOTH outcomes — pass and fail. Examples:
   - Pass: "RSI 63.35 > 50 AND above MA(20) 49.65"
   - Fail: "RSI 45.84 below MA(20) 35.33 — C3 fails"
3. Threshold values come from config — never hardcode 50, 80, 30, etc.
4. Conditions never raise — caller decides if missing data is fatal.

--- TASK 1: Create src/conditions/c0_spot_trend.py ---

C0 = Spot Trend Filter. Direction of the underlying must agree with
option type.
- For CE trade: spot CLOSE must be ABOVE spot VWAP
- For PE trade: spot CLOSE must be BELOW spot VWAP
No buffer zone. Simple above/below.

from dataclasses import dataclass

def check_c0(spot_close: float, spot_vwap: float, option_type: str) -> tuple[bool, str]:
    """
    Args:
        spot_close: latest spot index close (NIFTY or BANKNIFTY)
        spot_vwap: spot's own session VWAP
        option_type: "CE" or "PE"
    Returns:
        (passed, reason)
    """
    if option_type == "CE":
        passed = spot_close > spot_vwap
        if passed:
            return True, f"C0 PASS: spot {spot_close:.2f} above VWAP {spot_vwap:.2f} (CE direction OK)"
        return False, f"C0 FAIL: spot {spot_close:.2f} not above VWAP {spot_vwap:.2f} (CE needs spot above)"
    elif option_type == "PE":
        passed = spot_close < spot_vwap
        if passed:
            return True, f"C0 PASS: spot {spot_close:.2f} below VWAP {spot_vwap:.2f} (PE direction OK)"
        return False, f"C0 FAIL: spot {spot_close:.2f} not below VWAP {spot_vwap:.2f} (PE needs spot below)"
    else:
        return False, f"C0 ERROR: invalid option_type '{option_type}', must be CE or PE"

--- TASK 2: Create src/conditions/c1_option_price_vwap.py ---

C1 = Option price above its own VWAP, on a GREEN candle.
Also has the "late entry" rule: if candle close is >= 30% above VWAP,
skip (caller decides to wait for retracement).

def check_c1(snapshot, late_entry_threshold_pct: float) -> tuple[bool, str]:
    """
    Args:
        snapshot: IndicatorSnapshot from src/indicators/calculator.py
        late_entry_threshold_pct: from config.strike.late_entry_threshold_percent
    Returns:
        (passed, reason)
    """
    close = snapshot.close
    vwap = snapshot.vwap
    is_green = snapshot.is_green

    if not is_green:
        return False, f"C1 FAIL: candle is RED (close {close:.2f} <= open {snapshot.open:.2f})"

    if close <= vwap:
        return False, f"C1 FAIL: close {close:.2f} not above VWAP {vwap:.2f}"

    # Late entry check
    pct_above_vwap = ((close - vwap) / vwap) * 100
    if pct_above_vwap >= late_entry_threshold_pct:
        return False, (
            f"C1 FAIL (LATE ENTRY): close {close:.2f} is {pct_above_vwap:.1f}% above "
            f"VWAP {vwap:.2f} (threshold {late_entry_threshold_pct}%) — wait for retrace"
        )

    return True, (
        f"C1 PASS: green candle, close {close:.2f} above VWAP {vwap:.2f} "
        f"({pct_above_vwap:.1f}% above, under {late_entry_threshold_pct}% threshold)"
    )

--- TASK 3: Create src/conditions/c2_oi_below_ma.py ---

C2 = OI on the option must close BELOW its OI MA(20).
The "price rising" half of short-covering is enforced by C1's green
candle check. C2 only checks the OI side.

def check_c2(snapshot) -> tuple[bool, str]:
    """
    Args:
        snapshot: IndicatorSnapshot
    Returns:
        (passed, reason)
    """
    oi = snapshot.oi
    oi_ma = snapshot.oi_ma

    if oi < oi_ma:
        pct_below = ((oi_ma - oi) / oi_ma) * 100
        return True, (
            f"C2 PASS: OI {oi:,.0f} below MA(20) {oi_ma:,.0f} "
            f"({pct_below:.1f}% below MA — short covering signal)"
        )
    pct_above = ((oi - oi_ma) / oi_ma) * 100
    return False, (
        f"C2 FAIL: OI {oi:,.0f} above MA(20) {oi_ma:,.0f} "
        f"({pct_above:.1f}% above MA — not short covering)"
    )

--- TASK 4: Create src/conditions/c3_rsi_momentum.py ---

C3 = RSI must be above its MA(20), AND value between rsi_min and rsi_max.
The strategy doc mentions two valid forms (fresh crossover vs sustained
above) — for code simplicity we treat both as "RSI > MA" and add a
sub-flag indicating which form.

def check_c3(snapshot, rsi_min: float, rsi_max: float) -> tuple[bool, str]:
    """
    Args:
        snapshot: IndicatorSnapshot
        rsi_min: from config.conditions.c3_rsi_min (default 50)
        rsi_max: from config.conditions.c3_rsi_max (default 80)
    Returns:
        (passed, reason)
    """
    rsi = snapshot.rsi
    rsi_ma = snapshot.rsi_ma

    if rsi < rsi_min:
        return False, f"C3 FAIL: RSI {rsi:.2f} below minimum {rsi_min} (weak momentum)"
    if rsi > rsi_max:
        return False, f"C3 FAIL: RSI {rsi:.2f} above maximum {rsi_max} (overbought)"
    if rsi <= rsi_ma:
        return False, f"C3 FAIL: RSI {rsi:.2f} not above MA(20) {rsi_ma:.2f} (no upward momentum)"

    return True, (
        f"C3 PASS: RSI {rsi:.2f} above MA(20) {rsi_ma:.2f}, "
        f"within range [{rsi_min}, {rsi_max}]"
    )

--- TASK 5: Create src/conditions/c4_volume.py ---

C4 = Volume above MA(20) AND green volume bar.
"Green volume bar" = closing candle was green (close > open) on this
candle. (Some charts color volume bars green when close > open of same
candle — same definition.)

def check_c4(snapshot) -> tuple[bool, str]:
    """
    Args:
        snapshot: IndicatorSnapshot
    Returns:
        (passed, reason)
    """
    volume = snapshot.volume
    volume_ma = snapshot.volume_ma
    is_green = snapshot.is_green

    if volume <= volume_ma:
        return False, (
            f"C4 FAIL: volume {volume:,.0f} not above MA(20) {volume_ma:,.0f} "
            f"(thin market)"
        )
    if not is_green:
        return False, (
            f"C4 FAIL: volume above MA but candle is RED — sellers active, "
            f"wait one candle"
        )
    return True, (
        f"C4 PASS: volume {volume:,.0f} above MA(20) {volume_ma:,.0f} "
        f"on green candle"
    )

--- TASK 6: Create src/conditions/__init__.py ---

Re-export all condition functions for clean imports:

from src.conditions.c0_spot_trend import check_c0
from src.conditions.c1_option_price_vwap import check_c1
from src.conditions.c2_oi_below_ma import check_c2
from src.conditions.c3_rsi_momentum import check_c3
from src.conditions.c4_volume import check_c4

__all__ = ["check_c0", "check_c1", "check_c2", "check_c3", "check_c4"]

--- TASK 7: Create src/conditions/all_conditions.py (orchestrator) ---

This is the convenience helper that runs all 5 conditions and reports
the combined result. Used by Phase 5's main loop.

from dataclasses import dataclass, field

@dataclass
class ConditionResult:
    name: str           # "C0", "C1", etc.
    passed: bool
    reason: str

@dataclass
class AllConditionsResult:
    all_passed: bool
    results: list[ConditionResult] = field(default_factory=list)

    def failed_conditions(self) -> list[str]:
        return [r.name for r in self.results if not r.passed]

    def passed_conditions(self) -> list[str]:
        return [r.name for r in self.results if r.passed]

    def short_summary(self) -> str:
        """Returns 'C0 ✓ C1 ✓ C2 ✗ C3 ✓ C4 ✓' style summary."""
        return " ".join(f"{r.name} {'✓' if r.passed else '✗'}" for r in self.results)

def check_all_conditions(
    option_snapshot,        # IndicatorSnapshot from option candles
    spot_close: float,
    spot_vwap: float,
    option_type: str,       # "CE" or "PE"
    config,                 # AppConfig
) -> AllConditionsResult:
    """
    Runs all 5 conditions. ALL must pass for all_passed=True.

    Stops at first failure for efficiency? NO — run all 5 always so logs
    can show which combination failed (debugging value > tiny perf gain).
    """
    results = []

    ok, reason = check_c0(spot_close, spot_vwap, option_type)
    results.append(ConditionResult("C0", ok, reason))

    ok, reason = check_c1(option_snapshot, config.strike.late_entry_threshold_percent)
    results.append(ConditionResult("C1", ok, reason))

    ok, reason = check_c2(option_snapshot)
    results.append(ConditionResult("C2", ok, reason))

    ok, reason = check_c3(option_snapshot, config.conditions.c3_rsi_min, config.conditions.c3_rsi_max)
    results.append(ConditionResult("C3", ok, reason))

    ok, reason = check_c4(option_snapshot)
    results.append(ConditionResult("C4", ok, reason))

    all_passed = all(r.passed for r in results)
    return AllConditionsResult(all_passed=all_passed, results=results)

--- TASK 8: Create src/data/expiry_resolver.py ---

Dynamic expiry helper. ZERO hardcoded day-of-week. Source of truth is
the broker instrument dump.

from datetime import date, timedelta
import pandas as pd
from src.data.base_feed import BaseFeed

def get_all_expiries(feed: BaseFeed, symbol: str) -> list[date]:
    """
    Returns sorted list of all future expiry dates for symbol.
    symbol: "NIFTY" or "BANKNIFTY"
    """

def get_next_expiry(feed: BaseFeed, symbol: str, after: date = None) -> date:
    """
    Returns the next expiry date for symbol on or after `after`
    (default: today). Raises ValueError if no expiry found.
    """

def get_nth_expiry(feed: BaseFeed, symbol: str, n: int = 0) -> date:
    """
    Returns the nth upcoming expiry (0 = nearest, 1 = next, etc.).
    """

def is_expiry_day(feed: BaseFeed, symbol: str, today: date = None) -> bool:
    """
    Returns True if today is a valid expiry day for symbol.
    Used by strategy to apply expiry-day TP multipliers from config.
    """

def get_expiry_summary(feed: BaseFeed) -> dict:
    """
    Returns a debug summary of expiry patterns detected from data:
    {
      "NIFTY": {"next_4_expiries": [...], "weekday_pattern": "Tuesday"},
      "BANKNIFTY": {"next_4_expiries": [...], "weekday_pattern": "Tuesday-monthly"}
    }
    Weekday pattern is DERIVED from the actual data — not hardcoded.
    """

Implementation notes:
- For Kite: use kite.instruments("NFO"), filter where name == symbol,
  segment == "NFO-OPT", extract unique expiry dates, sort.
- For Upstox: use the option chain API or instruments JSON dump.
- Cache the result for the trading day (lot sizes pattern — fetch once,
  reuse).

--- TASK 9: Create scripts/list_expiries.py ---

User-facing utility. Loads secrets, connects feed, prints expiries.

from src.config_loader import load_config, load_secrets
from src.data.feed_factory import connect_feed
from src.data.expiry_resolver import get_expiry_summary
import calendar

def main():
    load_secrets()
    config = load_config("config/config.yaml")
    feed = connect_feed(config)

    summary = get_expiry_summary(feed)
    print("=" * 60)
    print(f"  Expiry Calendar (source: {feed.get_broker_name()})")
    print("=" * 60)
    for symbol, info in summary.items():
        print(f"\n{symbol}:")
        print(f"  Pattern detected: {info['weekday_pattern']}")
        print(f"  Next expiries:")
        for d in info["next_4_expiries"]:
            day_name = calendar.day_name[d.weekday()]
            print(f"    {d}  ({day_name})")
    print()

if __name__ == "__main__":
    main()

--- TASK 10: Create scripts/check_conditions.py ---

The big calibration tool for this phase. Runs all 5 conditions on a
specified strike and prints the verdict.

Usage:
  python scripts/check_conditions.py --symbol NIFTY --strike 24050 --option-type CE --expiry 2026-06-02

Steps:
1. load_secrets(), load_config(), connect_feed()
2. Fetch spot price + spot VWAP via spot candles (use get_5min_candles
   with NIFTY spot instrument key — for kite: "NSE:NIFTY 50" but for
   historical_data we need the index instrument token)
3. Fetch option candles, compute IndicatorSnapshot
4. Run check_all_conditions(...)
5. Print formatted report:

   ============================================================
     Condition Check Report
     NIFTY 02 Jun 2026 24050 CE
     Time: 2026-05-26 14:55:00 IST
   ============================================================
   Spot NIFTY      : 24031.7 (VWAP 24015.3 — ABOVE)
   Option close    : 137.90 (VWAP 175.5 — BELOW)
   RSI(14)         : 35.35  (MA 28.42 — ABOVE MA)
   OI              : 1,268,280 (MA 1,259,105 — ABOVE MA)
   Volume          : 147,810  (MA 96,882 — ABOVE MA)
   ------------------------------------------------------------
     C0 ✗  FAIL: spot 24031.7 above VWAP 24015.3 (CE direction OK)
           — wait, this says "above VWAP" so CE should pass...
           Re-read condition... actually for CE spot above VWAP = pass
     C1 ✗  FAIL: close 137.90 not above VWAP 175.50
     C2 ✓  PASS: OI 1,268,280 below MA(20) 1,259,105
     ...
   ------------------------------------------------------------
   SUMMARY: 2/5 conditions pass — NO SIGNAL
   Failed: C1, C3
   ============================================================

For NIFTY spot candle fetching, use these Kite instrument tokens:
  NIFTY:     instrument_token = 256265   (NIFTY 50 index)
  BANKNIFTY: instrument_token = 260105   (NIFTY BANK index)
These tokens are stable. Add as constants in src/data/kite_feed.py
class attributes or a module-level dict.

For Upstox, use: "NSE_INDEX|Nifty 50" and "NSE_INDEX|Nifty Bank"

--- TASK 11: Unit tests ---

Create tests/test_conditions.py with these tests, using the candle data
from docs/known_indicator_values.md as fixtures:

# C0 tests
def test_c0_ce_spot_above_vwap_passes():
    ok, _ = check_c0(spot_close=24530, spot_vwap=24500, option_type="CE")
    assert ok is True

def test_c0_ce_spot_below_vwap_fails():
    ok, _ = check_c0(spot_close=24470, spot_vwap=24500, option_type="CE")
    assert ok is False

def test_c0_pe_spot_below_vwap_passes():
    ok, _ = check_c0(spot_close=24470, spot_vwap=24500, option_type="PE")
    assert ok is True

def test_c0_pe_spot_above_vwap_fails():
    ok, _ = check_c0(spot_close=24530, spot_vwap=24500, option_type="PE")
    assert ok is False

def test_c0_invalid_option_type():
    ok, reason = check_c0(spot_close=100, spot_vwap=100, option_type="XX")
    assert ok is False
    assert "invalid option_type" in reason

# C1 tests (use helper to build snapshots)
def make_snapshot(**kwargs):
    """Helper to build IndicatorSnapshot with defaults."""
    defaults = dict(
        vwap=100.0, rsi=60.0, rsi_ma=55.0, oi=1_000_000, oi_ma=2_000_000,
        volume=10_000, volume_ma=5_000, close=105.0, open=100.0, high=110.0,
        low=99.0, timestamp=pd.Timestamp("2026-05-26 14:55", tz="Asia/Kolkata"),
        is_green=True,
    )
    defaults.update(kwargs)
    return IndicatorSnapshot(**defaults)

def test_c1_green_above_vwap_passes():
    s = make_snapshot(close=110, vwap=100, open=100, is_green=True)
    ok, _ = check_c1(s, late_entry_threshold_pct=30)
    assert ok is True

def test_c1_red_candle_fails():
    s = make_snapshot(close=95, vwap=100, open=100, is_green=False)
    ok, _ = check_c1(s, late_entry_threshold_pct=30)
    assert ok is False

def test_c1_below_vwap_fails():
    s = make_snapshot(close=99, vwap=100, open=98, is_green=True)
    ok, _ = check_c1(s, late_entry_threshold_pct=30)
    assert ok is False

def test_c1_late_entry_fails():
    # 35% above VWAP (greater than 30% threshold) — should fail
    s = make_snapshot(close=135, vwap=100, open=100, is_green=True)
    ok, reason = check_c1(s, late_entry_threshold_pct=30)
    assert ok is False
    assert "LATE ENTRY" in reason

# C2 tests using real fixture data
def test_c2_positive_candle_2():
    """Candle 2 from known_indicator_values.md: OI 4.51M, MA 11.2M -> PASS"""
    s = make_snapshot(oi=4_510_000, oi_ma=11_200_000)
    ok, _ = check_c2(s)
    assert ok is True

def test_c2_negative_candle_4():
    """Candle 4 from known_indicator_values.md: OI 987k, MA 938k -> FAIL"""
    s = make_snapshot(oi=987_000, oi_ma=938_000)
    ok, _ = check_c2(s)
    assert ok is False

# C3 tests
def test_c3_rsi_above_ma_in_range_passes():
    """Candle 1: RSI 63.35, MA 49.65"""
    s = make_snapshot(rsi=63.35, rsi_ma=49.65)
    ok, _ = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is True

def test_c3_rsi_below_min_fails():
    s = make_snapshot(rsi=45, rsi_ma=40)
    ok, _ = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is False

def test_c3_rsi_above_max_fails():
    s = make_snapshot(rsi=85, rsi_ma=70)
    ok, _ = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is False

def test_c3_rsi_below_ma_fails():
    """Candle 5: RSI 52.28, MA 53.24 -> FAIL"""
    s = make_snapshot(rsi=52.28, rsi_ma=53.24)
    ok, _ = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is False

# C4 tests
def test_c4_volume_above_ma_green_passes():
    s = make_snapshot(volume=15000, volume_ma=10000, is_green=True)
    ok, _ = check_c4(s)
    assert ok is True

def test_c4_volume_below_ma_fails():
    s = make_snapshot(volume=5000, volume_ma=10000, is_green=True)
    ok, _ = check_c4(s)
    assert ok is False

def test_c4_volume_above_ma_red_fails():
    s = make_snapshot(volume=15000, volume_ma=10000, is_green=False)
    ok, _ = check_c4(s)
    assert ok is False

# all_conditions integration tests
def test_all_conditions_all_pass():
    """Manufactured snapshot where every C0-C4 should pass."""
    s = make_snapshot(
        close=110, vwap=100, open=105, is_green=True,
        rsi=65, rsi_ma=55,
        oi=1_000_000, oi_ma=2_000_000,
        volume=15_000, volume_ma=10_000,
    )
    cfg = build_minimal_test_config()  # fixture
    result = check_all_conditions(
        option_snapshot=s, spot_close=24530, spot_vwap=24500,
        option_type="CE", config=cfg,
    )
    assert result.all_passed is True
    assert len(result.passed_conditions()) == 5

def test_all_conditions_c1_fails():
    """Same as above but red candle -> only C1 fails."""
    s = make_snapshot(
        close=95, vwap=100, open=100, is_green=False,   # C1 fails
        rsi=65, rsi_ma=55,
        oi=1_000_000, oi_ma=2_000_000,
        volume=15_000, volume_ma=10_000,
    )
    cfg = build_minimal_test_config()
    result = check_all_conditions(
        option_snapshot=s, spot_close=24530, spot_vwap=24500,
        option_type="CE", config=cfg,
    )
    assert result.all_passed is False
    assert "C1" in result.failed_conditions()

# Expiry resolver tests (use mocked feed)
def test_get_next_expiry_picks_earliest_future(mocker):
    """Mock feed.instruments() to return a known set of expiries."""
    # Implementation detail: mock get_all_expiries return value
    pass

def test_is_expiry_day_today(mocker):
    pass

After writing all files, run:
  call venv\Scripts\activate.bat
  pytest tests/ -v

All 26 prior tests must still pass, plus all new condition tests.
Total expected: 50+ tests passing.

Report:
1. Exact pytest output
2. Confirm src/conditions/ has c0_..., c1_..., c2_..., c3_..., c4_...,
   all_conditions.py, __init__.py
3. Confirm src/data/expiry_resolver.py created
4. Confirm scripts/check_conditions.py and scripts/list_expiries.py
   created
5. Any decisions you had to make about ambiguous parts of the strategy doc
````

---

## STEP 2 — Push to git (Machine 1)

```cmd
git add .
git commit -m "Phase 3 complete - conditions C0-C4 + dynamic expiry"
git push
```

---

## STEP 3 — Verification Checklist (Machine 2 during market hours)

Pull, refresh token, then run these in order:

### Check A: list_expiries.py works
```cmd
git pull
python scripts\refresh_token_kite.py
python scripts\list_expiries.py
```

Expected: prints NIFTY expiries (should show Tuesdays) and BANKNIFTY
expiries (should show last-Tuesdays). The script DETECTS these patterns
from data, doesn't assume them.

Send me the output.

### Check B: check_conditions.py on a real strike
```cmd
python scripts\check_conditions.py --symbol NIFTY --strike <ATM> --option-type CE --expiry <next_tuesday>
python scripts\check_conditions.py --symbol NIFTY --strike <ATM> --option-type PE --expiry <next_tuesday>
python scripts\check_conditions.py --symbol BANKNIFTY --strike <ATM> --option-type CE --expiry <last_tuesday_of_month>
python scripts\check_conditions.py --symbol BANKNIFTY --strike <ATM> --option-type PE --expiry <last_tuesday_of_month>
```

For each, the script prints which conditions pass/fail. **The bot will
not actually find a valid 5-of-5 signal most of the time** — that's
expected. The condition checker just confirms each rule evaluates
correctly.

Send me the output of at least one of these.

### Check C: pytest still green
```cmd
pytest tests\ -v
```
All 50+ tests pass.

---

## STEP 4 — When you confirm Phase 3 complete, send me

1. Full pytest output (test count + pass/fail)
2. Output of `list_expiries.py`
3. Output of one `check_conditions.py` run (your choice of strike)
4. Any decisions Claude Code flagged about ambiguous spec parts

If all of those look right, I write Phase 4.

---

## What Phase 4 will build (preview)

Phase 4 is the **risk + state management** module:
- SL calculation (Method 1 point buffer + Method 2 percentage, with VIX regime multiplier)
- Lot sizing (₹3,000 target risk → number of lots, capped at config max)
- TP1 + TP2 calculation
- Daily state: SL counter, cooldown timer, killed strikes
- State persists to `logs/state.json` so a bot restart doesn't lose
  daily counters
- A `scripts/check_risk.py` that takes a hypothetical entry + SL and
  prints lots, TP1, TP2, total risk

After Phase 4 the bot will have everything except the orchestration
loop and Telegram alerts (Phase 5).

**End of Phase 3.**
