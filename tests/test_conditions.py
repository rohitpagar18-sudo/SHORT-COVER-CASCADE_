"""Phase 3 unit tests for the five strategy conditions and the
``check_all_conditions`` orchestrator.

Fixture candles come from ``docs/known_indicator_values.md`` wherever
real data is available; the rest are minimal manufactured cases.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.conditions import (
    check_all_conditions,
    check_c0,
    check_c1,
    check_c2,
    check_c3,
    check_c4,
)
from src.config_loader import AppConfig
from src.indicators.calculator import IndicatorSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_snapshot(**kwargs: Any) -> IndicatorSnapshot:
    """Build IndicatorSnapshot with sensible defaults; override via kwargs."""
    defaults: dict[str, Any] = dict(
        vwap=100.0,
        rsi=60.0,
        rsi_ma=55.0,
        oi=1_000_000.0,
        oi_ma=2_000_000.0,
        volume=10_000.0,
        volume_ma=5_000.0,
        close=105.0,
        open=100.0,
        high=110.0,
        low=99.0,
        timestamp=pd.Timestamp("2026-05-26 14:55", tz="Asia/Kolkata"),
        is_green=True,
    )
    defaults.update(kwargs)
    return IndicatorSnapshot(**defaults)


# ---------------------------------------------------------------------------
# C0 — spot trend
# ---------------------------------------------------------------------------


def test_c0_ce_spot_above_vwap_passes() -> None:
    ok, reason = check_c0(spot_close=24530, spot_vwap=24500, option_type="CE")
    assert ok is True
    assert "PASS" in reason


def test_c0_ce_spot_below_vwap_fails() -> None:
    ok, reason = check_c0(spot_close=24470, spot_vwap=24500, option_type="CE")
    assert ok is False
    assert "FAIL" in reason


def test_c0_pe_spot_below_vwap_passes() -> None:
    ok, reason = check_c0(spot_close=24470, spot_vwap=24500, option_type="PE")
    assert ok is True
    assert "PASS" in reason


def test_c0_pe_spot_above_vwap_fails() -> None:
    ok, reason = check_c0(spot_close=24530, spot_vwap=24500, option_type="PE")
    assert ok is False
    assert "FAIL" in reason


def test_c0_ce_spot_equal_vwap_fails() -> None:
    # Strategy doc: strictly above for CE — equal is not a pass.
    ok, reason = check_c0(spot_close=24500, spot_vwap=24500, option_type="CE")
    assert ok is False


def test_c0_invalid_option_type() -> None:
    ok, reason = check_c0(spot_close=100, spot_vwap=100, option_type="XX")
    assert ok is False
    assert "invalid option_type" in reason


# ---------------------------------------------------------------------------
# C1 — option price > VWAP on a green candle (with late-entry guard)
# ---------------------------------------------------------------------------


def test_c1_green_above_vwap_passes() -> None:
    s = make_snapshot(close=110, vwap=100, open=100, is_green=True)
    ok, reason, pct = check_c1(s, late_entry_threshold_pct=30)
    assert ok is True
    assert "PASS" in reason
    assert pct == pytest.approx(10.0)


def test_c1_red_candle_fails() -> None:
    s = make_snapshot(close=95, vwap=100, open=100, is_green=False)
    ok, reason, pct = check_c1(s, late_entry_threshold_pct=30)
    assert ok is False
    assert "RED" in reason
    # pct still computed even on failure (Phase 5.2 needs it for logging).
    assert pct == pytest.approx(-5.0)


def test_c1_below_vwap_fails() -> None:
    s = make_snapshot(close=99, vwap=100, open=98, is_green=True)
    ok, reason, _pct = check_c1(s, late_entry_threshold_pct=30)
    assert ok is False
    assert "not above VWAP" in reason


def test_c1_equal_vwap_fails() -> None:
    s = make_snapshot(close=100, vwap=100, open=98, is_green=True)
    ok, _reason, _pct = check_c1(s, late_entry_threshold_pct=30)
    assert ok is False


def test_c1_late_entry_fails() -> None:
    # 35% above VWAP (greater than 30% threshold) — should fail
    s = make_snapshot(close=135, vwap=100, open=100, is_green=True)
    ok, reason, pct = check_c1(s, late_entry_threshold_pct=30)
    assert ok is False
    assert "LATE ENTRY" in reason
    assert pct == pytest.approx(35.0)


def test_c1_just_under_late_entry_passes() -> None:
    s = make_snapshot(close=129, vwap=100, open=100, is_green=True)
    ok, _reason, _pct = check_c1(s, late_entry_threshold_pct=30)
    assert ok is True


# ---------------------------------------------------------------------------
# C2 — OI < MA(20)
# ---------------------------------------------------------------------------


def test_c2_positive_candle_2() -> None:
    """known_indicator_values.md Candle 2: OI 4.51M vs MA 11.2M -> PASS"""
    s = make_snapshot(oi=4_510_000, oi_ma=11_200_000)
    ok, reason = check_c2(s)
    assert ok is True
    assert "below MA" in reason


def test_c2_negative_candle_4() -> None:
    """known_indicator_values.md Candle 4: OI 987k vs MA 938k -> FAIL"""
    s = make_snapshot(oi=987_000, oi_ma=938_000)
    ok, reason = check_c2(s)
    assert ok is False
    assert "above MA" in reason


def test_c2_negative_candle_5() -> None:
    """known_indicator_values.md Candle 5: OI 2.163M vs MA 2.018M -> FAIL"""
    s = make_snapshot(oi=2_163_008, oi_ma=2_018_445)
    ok, _ = check_c2(s)
    assert ok is False


def test_c2_equal_fails() -> None:
    # OI == MA: strict less-than required.
    s = make_snapshot(oi=1_000_000, oi_ma=1_000_000)
    ok, _ = check_c2(s)
    assert ok is False


# ---------------------------------------------------------------------------
# C3 — RSI above MA and in range
# ---------------------------------------------------------------------------


def test_c3_rsi_above_ma_in_range_passes() -> None:
    """known_indicator_values.md Candle 1: RSI 63.35 vs MA 49.65 -> PASS"""
    s = make_snapshot(rsi=63.35, rsi_ma=49.65)
    ok, reason = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is True
    assert "PASS" in reason


def test_c3_rsi_below_min_fails() -> None:
    s = make_snapshot(rsi=45, rsi_ma=40)
    ok, reason = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is False
    assert "below minimum" in reason


def test_c3_rsi_above_max_fails() -> None:
    s = make_snapshot(rsi=85, rsi_ma=70)
    ok, reason = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is False
    assert "above maximum" in reason


def test_c3_rsi_below_ma_fails() -> None:
    """known_indicator_values.md Candle 5: RSI 52.28 vs MA 53.24 -> FAIL"""
    s = make_snapshot(rsi=52.28, rsi_ma=53.24)
    ok, reason = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is False
    assert "not above MA" in reason


def test_c3_rsi_equals_ma_fails() -> None:
    s = make_snapshot(rsi=60, rsi_ma=60)
    ok, _ = check_c3(s, rsi_min=50, rsi_max=80)
    assert ok is False


# ---------------------------------------------------------------------------
# C4 — volume above MA on green candle
# ---------------------------------------------------------------------------


def test_c4_volume_above_ma_green_passes() -> None:
    s = make_snapshot(volume=15000, volume_ma=10000, is_green=True)
    ok, reason = check_c4(s)
    assert ok is True
    assert "PASS" in reason


def test_c4_volume_below_ma_fails() -> None:
    s = make_snapshot(volume=5000, volume_ma=10000, is_green=True)
    ok, reason = check_c4(s)
    assert ok is False
    assert "thin market" in reason


def test_c4_volume_above_ma_red_fails() -> None:
    s = make_snapshot(volume=15000, volume_ma=10000, is_green=False)
    ok, reason = check_c4(s)
    assert ok is False
    assert "RED" in reason


def test_c4_volume_equal_ma_fails() -> None:
    s = make_snapshot(volume=10000, volume_ma=10000, is_green=True)
    ok, _ = check_c4(s)
    assert ok is False


# ---------------------------------------------------------------------------
# All-conditions orchestrator
# ---------------------------------------------------------------------------


def test_all_conditions_all_pass(config: AppConfig) -> None:
    s = make_snapshot(
        close=110,
        vwap=100,
        open=105,
        is_green=True,
        rsi=65,
        rsi_ma=55,
        oi=1_000_000,
        oi_ma=2_000_000,
        volume=15_000,
        volume_ma=10_000,
    )
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24530,
        spot_vwap=24500,
        option_type="CE",
        config=config,
    )
    assert result.all_passed is True
    assert len(result.passed_conditions()) == 5
    assert result.failed_conditions() == []
    assert "C0 ✓" in result.short_summary()


def test_all_conditions_c1_fails_red_candle(config: AppConfig) -> None:
    s = make_snapshot(
        close=95, vwap=100, open=100, is_green=False,  # C1 fails (red)
        rsi=65, rsi_ma=55,
        oi=1_000_000, oi_ma=2_000_000,
        volume=15_000, volume_ma=10_000,
    )
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24530,
        spot_vwap=24500,
        option_type="CE",
        config=config,
    )
    assert result.all_passed is False
    assert "C1" in result.failed_conditions()
    # C4 also fails because the candle is red.
    assert "C4" in result.failed_conditions()


def test_all_conditions_c0_fails_wrong_direction(config: AppConfig) -> None:
    s = make_snapshot(
        close=110, vwap=100, open=105, is_green=True,
        rsi=65, rsi_ma=55,
        oi=1_000_000, oi_ma=2_000_000,
        volume=15_000, volume_ma=10_000,
    )
    # Asking for CE while spot is BELOW VWAP -> C0 fails.
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24400,
        spot_vwap=24500,
        option_type="CE",
        config=config,
    )
    assert result.all_passed is False
    assert "C0" in result.failed_conditions()


def test_all_conditions_runs_every_check(config: AppConfig) -> None:
    """Orchestrator must not short-circuit: every result must be present."""
    s = make_snapshot(
        close=95, vwap=100, open=100, is_green=False,
        rsi=30, rsi_ma=40,
        oi=3_000_000, oi_ma=2_000_000,
        volume=1_000, volume_ma=10_000,
    )
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24400,
        spot_vwap=24500,
        option_type="CE",
        config=config,
    )
    names = [r.name for r in result.results]
    assert names == ["C0", "C1", "C2", "C3", "C4"]
    assert result.all_passed is False
    assert set(result.failed_conditions()) == {"C0", "C1", "C2", "C3", "C4"}


def test_all_conditions_by_name_lookup(config: AppConfig) -> None:
    s = make_snapshot(close=110, vwap=100, open=105, is_green=True)
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24530,
        spot_vwap=24500,
        option_type="CE",
        config=config,
    )
    c1 = result.by_name("C1")
    assert c1 is not None
    assert c1.passed is True
    assert result.by_name("C99") is None


def test_all_conditions_uses_config_thresholds(config: AppConfig) -> None:
    """Reason string for C1 must echo config threshold, never a literal 30."""
    s = make_snapshot(close=110, vwap=100, open=105, is_green=True)
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24530,
        spot_vwap=24500,
        option_type="CE",
        config=config,
    )
    c1 = result.by_name("C1")
    assert c1 is not None
    assert str(config.strike.late_entry_threshold_percent) in c1.reason
