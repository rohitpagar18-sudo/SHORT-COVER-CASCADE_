"""Phase 4 unit tests — VIX regime, SL Method 1/2, hard exit, TP, lots,
StateManager (with cooldowns + killed strikes), and strike selector.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.config_loader import AppConfig
from src.data.strike_selector import (
    StrikeChoice,
    _select_relation_strikes,
    get_alert_strikes,
    get_order_strikes,
    get_strike_interval,
)
from src.risk import (
    VixRegime,
    check_hard_exit_red_candle,
    classify_vix,
    compute_lots,
    compute_sl_method1,
    compute_sl_method2,
    compute_tps,
    get_base_buffer,
)
from src.state import MAX_SL_PER_STRIKE, DailyState, StateManager, TradeRecord

IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# VIX regime
# ---------------------------------------------------------------------------


def test_vix_low() -> None:
    info = classify_vix(10.5)
    assert info.regime is VixRegime.LOW
    assert info.method1_multiplier == 0.75
    assert info.method2_sl_normal_pct == 4.0
    assert info.method2_sl_expiry_pct == 12.0


def test_vix_normal_lower_boundary() -> None:
    info = classify_vix(12.0)
    # Boundary belongs to the higher regime — 12.0 is NORMAL, not LOW.
    assert info.regime is VixRegime.NORMAL
    assert info.method1_multiplier == 1.0


def test_vix_normal() -> None:
    info = classify_vix(14.2)
    assert info.regime is VixRegime.NORMAL
    assert info.method1_multiplier == 1.0
    assert info.method2_sl_normal_pct == 5.0
    assert info.method2_sl_expiry_pct == 15.0


def test_vix_elevated_boundary() -> None:
    info = classify_vix(16.0)
    assert info.regime is VixRegime.ELEVATED
    assert info.method1_multiplier == 1.25


def test_vix_elevated() -> None:
    info = classify_vix(18.0)
    assert info.regime is VixRegime.ELEVATED
    assert info.method1_multiplier == 1.25
    assert info.method2_sl_normal_pct == 6.0
    assert info.method2_sl_expiry_pct == 18.0


def test_vix_high_boundary() -> None:
    info = classify_vix(20.0)
    assert info.regime is VixRegime.HIGH
    assert info.method1_multiplier == 1.5


def test_vix_high() -> None:
    info = classify_vix(25.0)
    assert info.regime is VixRegime.HIGH
    assert info.method1_multiplier == 1.5
    assert info.method2_sl_normal_pct == 8.0
    assert info.method2_sl_expiry_pct == 22.0


# ---------------------------------------------------------------------------
# SL Method 1 — point buffer (covers all premium bands & both symbols)
# ---------------------------------------------------------------------------


def test_sl_m1_nifty_normal_premium100() -> None:
    # NIFTY normal, price 100 -> 100-200 band -> 10 pts (boundary = higher band).
    info = classify_vix(14.0)  # NORMAL, multiplier 1.0
    r = compute_sl_method1(
        vwap_at_entry=150.0, option_price=100.0, symbol="NIFTY",
        is_expiry_day=False, vix_info=info, use_vix_multiplier=True,
    )
    assert r.method == 1
    assert r.base_buffer == 10
    assert r.vix_multiplier == 1.0
    assert r.final_buffer_or_pct == 10
    assert r.sl_price == pytest.approx(140.0)


def test_sl_m1_nifty_expiry_premium250() -> None:
    # NIFTY expiry, 250 -> 200-400 band -> 25 pts.
    info = classify_vix(14.0)
    r = compute_sl_method1(
        vwap_at_entry=250.0, option_price=250.0, symbol="NIFTY",
        is_expiry_day=True, vix_info=info, use_vix_multiplier=True,
    )
    assert r.base_buffer == 25
    assert r.sl_price == pytest.approx(225.0)


def test_sl_m1_banknifty_normal_premium300() -> None:
    # BANKNIFTY normal, 300 -> 200-400 band -> 22 pts.
    info = classify_vix(14.0)
    r = compute_sl_method1(
        vwap_at_entry=300.0, option_price=300.0, symbol="BANKNIFTY",
        is_expiry_day=False, vix_info=info, use_vix_multiplier=True,
    )
    assert r.base_buffer == 22
    assert r.sl_price == pytest.approx(278.0)


def test_sl_m1_banknifty_expiry_premium500() -> None:
    # BANKNIFTY expiry, 500 -> 400+ band -> 45 pts.
    info = classify_vix(14.0)
    r = compute_sl_method1(
        vwap_at_entry=500.0, option_price=500.0, symbol="BANKNIFTY",
        is_expiry_day=True, vix_info=info, use_vix_multiplier=True,
    )
    assert r.base_buffer == 45
    assert r.sl_price == pytest.approx(455.0)


def test_sl_m1_vix_multiplier_applied() -> None:
    # Premium 150 -> NIFTY normal 100-200 band -> 10 pts; elevated VIX -> 1.25.
    info = classify_vix(18.0)
    r = compute_sl_method1(
        vwap_at_entry=150.0, option_price=150.0, symbol="NIFTY",
        is_expiry_day=False, vix_info=info, use_vix_multiplier=True,
    )
    assert r.vix_multiplier == 1.25
    assert r.final_buffer_or_pct == pytest.approx(12.5)
    assert r.sl_price == pytest.approx(137.5)


def test_sl_m1_vix_disabled_via_config() -> None:
    info = classify_vix(18.0)  # would otherwise be 1.25
    r = compute_sl_method1(
        vwap_at_entry=150.0, option_price=150.0, symbol="NIFTY",
        is_expiry_day=False, vix_info=info, use_vix_multiplier=False,
    )
    assert r.vix_multiplier == 1.0
    assert r.final_buffer_or_pct == 10
    assert r.sl_price == pytest.approx(140.0)


def test_sl_m1_premium_below_50_raises() -> None:
    info = classify_vix(14.0)
    with pytest.raises(ValueError, match="below 50"):
        compute_sl_method1(
            vwap_at_entry=40, option_price=40, symbol="NIFTY",
            is_expiry_day=False, vix_info=info, use_vix_multiplier=True,
        )


def test_sl_m1_unknown_symbol_raises() -> None:
    info = classify_vix(14.0)
    with pytest.raises(ValueError):
        compute_sl_method1(
            vwap_at_entry=150, option_price=150, symbol="FINNIFTY",
            is_expiry_day=False, vix_info=info, use_vix_multiplier=True,
        )


def test_get_base_buffer_nifty_400_plus() -> None:
    # 400 itself is in the 400+ band (lower bound inclusive).
    assert get_base_buffer("NIFTY", 400.0, False) == 20
    assert get_base_buffer("NIFTY", 400.0, True) == 35


def test_get_base_buffer_banknifty_lowest_band() -> None:
    assert get_base_buffer("BANKNIFTY", 60.0, False) == 8
    assert get_base_buffer("BANKNIFTY", 60.0, True) == 20


# ---------------------------------------------------------------------------
# SL Method 2 — percentage based
# ---------------------------------------------------------------------------


def test_sl_m2_normal_day_normal_vix() -> None:
    info = classify_vix(14.0)  # NORMAL -> 5%
    r = compute_sl_method2(
        vwap_at_entry=150.0, is_expiry_day=False, vix_info=info
    )
    assert r.method == 2
    assert r.final_buffer_or_pct == 5.0
    assert r.sl_price == pytest.approx(142.5)


def test_sl_m2_expiry_day_elevated_vix() -> None:
    info = classify_vix(18.0)  # ELEVATED -> 18% expiry
    r = compute_sl_method2(
        vwap_at_entry=150.0, is_expiry_day=True, vix_info=info
    )
    assert r.final_buffer_or_pct == 18.0
    assert r.sl_price == pytest.approx(123.0)


def test_sl_m2_high_vix_normal_day() -> None:
    info = classify_vix(25.0)  # HIGH -> 8% normal
    r = compute_sl_method2(
        vwap_at_entry=200.0, is_expiry_day=False, vix_info=info
    )
    assert r.final_buffer_or_pct == 8.0
    assert r.sl_price == pytest.approx(184.0)


# ---------------------------------------------------------------------------
# Hard exit — red candle entirely below VWAP
# ---------------------------------------------------------------------------


def test_hard_exit_red_below_vwap() -> None:
    ok, reason = check_hard_exit_red_candle(
        candle_open=98, candle_high=99, candle_low=95, candle_close=96,
        vwap_at_entry=100,
    )
    assert ok is True
    assert "below VWAP" in reason


def test_hard_exit_red_above_vwap_no_exit() -> None:
    # Red candle but body straddles VWAP — no hard exit.
    ok, reason = check_hard_exit_red_candle(
        candle_open=105, candle_high=106, candle_low=98, candle_close=99,
        vwap_at_entry=100,
    )
    assert ok is False
    assert "not entirely below" in reason


def test_hard_exit_green_no_exit() -> None:
    ok, reason = check_hard_exit_red_candle(
        candle_open=95, candle_high=99, candle_low=94, candle_close=98,
        vwap_at_entry=100,
    )
    assert ok is False
    assert "GREEN" in reason


def test_hard_exit_red_high_touches_vwap_no_exit() -> None:
    # High equals VWAP — not strictly below — no exit.
    ok, _ = check_hard_exit_red_candle(
        candle_open=99, candle_high=100, candle_low=95, candle_close=97,
        vwap_at_entry=100,
    )
    assert ok is False


# ---------------------------------------------------------------------------
# Profit targets
# ---------------------------------------------------------------------------


def test_tp_normal_day(config: AppConfig) -> None:
    r = compute_tps(entry_price=152.50, sl_price=140.0,
                    is_expiry_day=False, config=config)
    assert r.risk_per_unit == pytest.approx(12.5)
    assert r.risk_to_tp1_ratio == 1.5
    assert r.risk_to_tp2_ratio == 2.5
    assert r.tp1 == pytest.approx(171.25)
    assert r.tp2 == pytest.approx(183.75)


def test_tp_expiry_day(config: AppConfig) -> None:
    r = compute_tps(entry_price=152.50, sl_price=140.0,
                    is_expiry_day=True, config=config)
    assert r.risk_to_tp1_ratio == 2.0
    assert r.risk_to_tp2_ratio == 3.0
    assert r.tp1 == pytest.approx(177.50)
    assert r.tp2 == pytest.approx(190.00)


def test_tp_invalid_sl_above_entry_raises(config: AppConfig) -> None:
    with pytest.raises(ValueError, match="below"):
        compute_tps(entry_price=140.0, sl_price=150.0,
                    is_expiry_day=False, config=config)


def test_tp_zero_risk_raises(config: AppConfig) -> None:
    with pytest.raises(ValueError):
        compute_tps(entry_price=140.0, sl_price=140.0,
                    is_expiry_day=False, config=config)


# ---------------------------------------------------------------------------
# Lot sizing
# ---------------------------------------------------------------------------


def test_lots_nifty_typical(config: AppConfig) -> None:
    # R = 12.50, lot 65 -> raw = floor(3000 / (12.50*65)) = floor(3.69) = 3.
    r = compute_lots(entry_price=152.50, sl_price=140.0, symbol="NIFTY",
                     lot_size=65, config=config)
    assert r.lots == 3
    assert r.units == 195
    assert r.total_risk_rupees == pytest.approx(2437.50)
    assert r.capped_by_lot_limit is False


def test_lots_banknifty_typical(config: AppConfig) -> None:
    # R = 30, lot 30 -> raw = floor(3000 / (30*30)) = floor(3.33) = 3.
    # Hard cap for BankNifty is 3 — so we land at the cap exactly.
    r = compute_lots(entry_price=300.0, sl_price=270.0, symbol="BANKNIFTY",
                     lot_size=30, config=config)
    assert r.lots == 3
    assert r.units == 90


def test_lots_capped_by_lot_limit(config: AppConfig) -> None:
    # Cheap option with tiny SL -> formula yields >> cap; clipped to 5.
    r = compute_lots(entry_price=60.0, sl_price=58.0, symbol="NIFTY",
                     lot_size=65, config=config)
    # raw = floor(3000 / (2*65)) = 23 -> capped to 5.
    assert r.lots == 5
    assert r.capped_by_lot_limit is True


def test_lots_minimum_one(config: AppConfig) -> None:
    # Expensive option with wide SL -> formula < 1 lot, floor at 1.
    r = compute_lots(entry_price=500.0, sl_price=400.0, symbol="NIFTY",
                     lot_size=65, config=config)
    # raw = floor(3000 / (100*65)) = 0 -> floored to 1.
    assert r.lots == 1
    assert r.units == 65


def test_lots_round_down_never_up(config: AppConfig) -> None:
    # raw = 3000/(12*65) = 3.846 -> floor = 3 (NEVER 4).
    r = compute_lots(entry_price=152.0, sl_price=140.0, symbol="NIFTY",
                     lot_size=65, config=config)
    assert r.lots == 3


def test_lots_invalid_sl_raises(config: AppConfig) -> None:
    with pytest.raises(ValueError):
        compute_lots(entry_price=140.0, sl_price=150.0, symbol="NIFTY",
                     lot_size=65, config=config)


def test_lots_unknown_symbol_raises(config: AppConfig) -> None:
    with pytest.raises(ValueError):
        compute_lots(entry_price=150.0, sl_price=140.0, symbol="FINNIFTY",
                     lot_size=40, config=config)


def test_lots_cap_disabled_allows_above_cap(config: AppConfig) -> None:
    no_cap = config.model_copy(
        update={
            "position_sizing": config.position_sizing.model_copy(
                update={"lot_cap_enabled": False}
            )
        }
    )
    r = compute_lots(entry_price=60.0, sl_price=58.0, symbol="NIFTY",
                     lot_size=65, config=no_cap)
    # raw = floor(3000 / 130) = 23
    assert r.lots == 23
    assert r.capped_by_lot_limit is False


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> StateManager:
    state_path = tmp_path / "state.json"
    return StateManager(state_file=state_path)


def test_state_loads_fresh_on_new_day(tmp_path: Path) -> None:
    m = _make_manager(tmp_path)
    state = m.load_state()
    today_iso = datetime.now(IST).date().isoformat()
    assert state.trading_date == today_iso
    assert state.sl_count == 0
    assert state.killed_strikes == {}


def test_state_increments_sl(tmp_path: Path) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    m.increment_sl_count("NIFTY", 24050, "CE")
    assert m.get_daily_sl_count() == 1
    assert m.get_strike_sl_count("NIFTY", 24050, "CE") == 1
    m.increment_sl_count("NIFTY", 24100, "CE")
    assert m.get_daily_sl_count() == 2


def test_state_killed_strike_after_2_sl(tmp_path: Path) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    m.increment_sl_count("NIFTY", 24050, "CE")
    assert not m.is_strike_killed("NIFTY", 24050, "CE")
    m.increment_sl_count("NIFTY", 24050, "CE")
    assert m.is_strike_killed("NIFTY", 24050, "CE")
    # Different strike unaffected.
    assert not m.is_strike_killed("NIFTY", 24100, "CE")


def test_state_cooldown_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    base = datetime.now(IST).replace(microsecond=0)
    # Patch "now" so the SL is recorded at a known instant.
    monkeypatch.setattr(StateManager, "_now_ist", lambda self: base)
    m.increment_sl_count("NIFTY", 24050, "CE")
    # Advance time by 5 minutes — should still be in cooldown.
    monkeypatch.setattr(
        StateManager, "_now_ist", lambda self: base + timedelta(minutes=5)
    )
    assert m.is_in_cooldown(cooldown_minutes=15)
    remaining = m.get_cooldown_remaining_seconds(cooldown_minutes=15)
    assert 9 * 60 <= remaining <= 10 * 60 + 1


def test_state_cooldown_elapsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    base = datetime.now(IST).replace(microsecond=0)
    monkeypatch.setattr(StateManager, "_now_ist", lambda self: base)
    m.increment_sl_count("NIFTY", 24050, "CE")
    monkeypatch.setattr(
        StateManager, "_now_ist", lambda self: base + timedelta(minutes=16)
    )
    assert not m.is_in_cooldown(cooldown_minutes=15)
    assert m.get_cooldown_remaining_seconds(cooldown_minutes=15) == 0


def test_state_circuit_breaker_blocks_re_entry(
    tmp_path: Path, config: AppConfig
) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    m.trigger_circuit_breaker("test reason")
    ok, reason = m.can_re_enter(config, "NIFTY", 24050, "CE")
    assert ok is False
    assert "Circuit breaker" in reason


def test_state_re_entry_blocked_by_daily_sl_cap(
    tmp_path: Path, config: AppConfig
) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    # max_sl_per_day = 2 (config). Hit two SLs on different strikes.
    m.increment_sl_count("NIFTY", 24050, "CE")
    m.increment_sl_count("NIFTY", 24100, "CE")
    # Re-entry on a fresh strike — still blocked by daily cap.
    ok, reason = m.can_re_enter(config, "NIFTY", 24200, "CE")
    assert ok is False
    assert "Daily SL count" in reason


def test_state_re_entry_blocked_by_daily_loss(
    tmp_path: Path, config: AppConfig
) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    m.add_loss(config.circuit_breakers.max_loss_per_day_rupees)
    ok, reason = m.can_re_enter(config, "NIFTY", 24050, "CE")
    assert ok is False
    assert "Daily loss" in reason


def test_state_re_entry_blocked_by_killed_strike(
    tmp_path: Path, config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    base = datetime.now(IST).replace(microsecond=0)
    monkeypatch.setattr(StateManager, "_now_ist", lambda self: base)
    m.increment_sl_count("NIFTY", 24050, "CE")
    m.increment_sl_count("NIFTY", 24050, "CE")
    # Cooldown elapsed — only the killed-strike rule should now apply.
    monkeypatch.setattr(
        StateManager, "_now_ist", lambda self: base + timedelta(minutes=20)
    )
    # Daily SL cap is 2 — bumps the count to the cap. To isolate the
    # killed-strike check, raise the cap for this test.
    relaxed = config.model_copy(
        update={
            "circuit_breakers": config.circuit_breakers.model_copy(
                update={"max_sl_per_day": 10}
            )
        }
    )
    ok, reason = m.can_re_enter(relaxed, "NIFTY", 24050, "CE")
    assert ok is False
    assert "stopped out" in reason
    # A different strike is fine.
    ok2, _ = m.can_re_enter(relaxed, "NIFTY", 24100, "CE")
    assert ok2 is True


def test_state_re_entry_allowed_clean(
    tmp_path: Path, config: AppConfig
) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    ok, reason = m.can_re_enter(config, "NIFTY", 24050, "CE")
    assert ok is True


def test_state_atomic_write_survives_crash(tmp_path: Path) -> None:
    """If a save is interrupted, the live state.json must remain valid."""
    state_path = tmp_path / "state.json"
    m = StateManager(state_file=state_path)
    m.load_state()
    m.increment_sl_count("NIFTY", 24050, "CE")
    # Live file is valid JSON with sl_count = 1.
    with state_path.open("r", encoding="utf-8") as f:
        live = json.load(f)
    assert live["sl_count"] == 1

    # Simulate a crash partway through a NEW write: drop a half-written .tmp.
    tmp_file = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp_file.write_text("{ not valid json")

    # The live file remains untouched and valid.
    with state_path.open("r", encoding="utf-8") as f:
        live2 = json.load(f)
    assert live2["sl_count"] == 1
    # A fresh manager can still load it.
    m2 = StateManager(state_file=state_path)
    state = m2.load_state()
    assert state.sl_count == 1


def test_state_persists_across_restarts(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    m1 = StateManager(state_file=state_path)
    m1.load_state()
    m1.increment_sl_count("NIFTY", 24050, "CE")
    m1.add_loss(1500.0)
    m1.add_profit(200.0)

    # Restart simulation.
    m2 = StateManager(state_file=state_path)
    state = m2.load_state()
    assert state.sl_count == 1
    assert state.total_loss_rupees == pytest.approx(1500.0)
    assert state.total_profit_rupees == pytest.approx(200.0)
    assert m2.get_strike_sl_count("NIFTY", 24050, "CE") == 1


def test_state_resets_on_new_trading_day(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    # Manually plant a stale state file from yesterday.
    stale = {
        "trading_date": "2000-01-01",
        "sl_count": 5,
        "total_loss_rupees": 5000.0,
        "total_profit_rupees": 0.0,
        "last_sl_hit_timestamp": None,
        "killed_strikes": {"NIFTY_24050_CE": 2},
        "re_entry_count": 0,
        "trades_today": [],
        "circuit_breaker_triggered": False,
        "circuit_breaker_reason": None,
    }
    state_path.write_text(json.dumps(stale))

    m = StateManager(state_file=state_path)
    state = m.load_state()
    today_iso = datetime.now(IST).date().isoformat()
    assert state.trading_date == today_iso
    assert state.sl_count == 0
    assert state.killed_strikes == {}


def test_state_record_trade(tmp_path: Path) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    trade = TradeRecord(
        timestamp=datetime.now(IST).isoformat(),
        symbol="NIFTY",
        strike=24050,
        option_type="CE",
        entry=152.50,
        sl=140.0,
        exit_price=171.25,
        exit_type="TP1",
        pnl_rupees=1218.75,
        re_entry_number=0,
    )
    m.record_trade(trade)
    # Persist + reload.
    m2 = StateManager(state_file=m.state_file)
    state = m2.load_state()
    assert len(state.trades_today) == 1
    assert state.trades_today[0]["exit_type"] == "TP1"


def test_state_no_cooldown_when_no_sl(tmp_path: Path) -> None:
    m = _make_manager(tmp_path)
    m.load_state()
    assert m.get_cooldown_remaining_seconds(cooldown_minutes=15) == 0
    assert not m.is_in_cooldown(cooldown_minutes=15)


def test_state_corrupt_file_resets(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("not json at all")
    m = StateManager(state_file=state_path)
    state = m.load_state()
    assert state.sl_count == 0
    # File was rewritten with valid JSON.
    with state_path.open("r", encoding="utf-8") as f:
        assert "trading_date" in json.load(f)


# ---------------------------------------------------------------------------
# Strike selector
# ---------------------------------------------------------------------------


def test_strike_interval_nifty() -> None:
    assert get_strike_interval("NIFTY") == 50
    assert get_strike_interval("nifty") == 50


def test_strike_interval_banknifty() -> None:
    assert get_strike_interval("BANKNIFTY") == 100


def test_strike_interval_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_strike_interval("FINNIFTY")


def test_strikes_ce_atm_plus_minus_1() -> None:
    # spot 24030 -> ATM = round(24030/50)*50 = 24050.
    # Per-level relations: CE has ITMn = atm - n*interval, OTMn = atm + n*interval.
    rel = _select_relation_strikes(atm=24050, interval=50, option_type="CE")
    assert rel == {
        "ITM3": 23900, "ITM2": 23950, "ITM1": 24000,
        "ATM": 24050,
        "OTM1": 24100, "OTM2": 24150, "OTM3": 24200,
    }


def test_strikes_pe_atm_plus_minus_1() -> None:
    rel = _select_relation_strikes(atm=24050, interval=50, option_type="PE")
    assert rel == {
        "ITM3": 24200, "ITM2": 24150, "ITM1": 24100,
        "ATM": 24050,
        "OTM1": 24000, "OTM2": 23950, "OTM3": 23900,
    }


def test_strikes_unknown_option_type_raises() -> None:
    with pytest.raises(ValueError):
        _select_relation_strikes(atm=24050, interval=50, option_type="XX")


class _FakeFeed:
    """Minimal feed stub for strike-selector tests."""

    def __init__(self, chain_strikes: list[int]):
        self._strikes = chain_strikes

    def get_option_chain(self, symbol: str, expiry: str) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for s in self._strikes:
            for typ in ("CE", "PE"):
                rows.append({
                    "strike": float(s),
                    "instrument_type": typ,
                    "instrument_token": int(s * 10 + (1 if typ == "CE" else 2)),
                    "tradingsymbol": f"NIFTY26JUN{s}{typ}",
                    "expiry": expiry,
                    "lot_size": 65,
                })
        return pd.DataFrame(rows)


def test_strikes_alert_default_itm2_itm1_atm_on(config: AppConfig) -> None:
    """Default config ships with itm2/itm1/atm ON, rest OFF."""
    feed = _FakeFeed([23950, 24000, 24050, 24100])
    choices = get_alert_strikes(
        feed=feed, symbol="NIFTY", spot_price=24030.0, option_type="CE",
        expiry="2026-06-02", config=config,
    )
    relations = [c.relation for c in choices]
    assert relations == ["ITM2", "ITM1", "ATM"]
    strikes = [c.strike for c in choices]
    assert strikes == [23950, 24000, 24050]
    # Each choice has both instrument_key and trading_symbol resolved.
    for c in choices:
        assert c.instrument_key
        assert c.trading_symbol.startswith("NIFTY")


def test_strikes_alert_config_filters_off_itm(config: AppConfig) -> None:
    feed = _FakeFeed([24000, 24050, 24100])
    filtered = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={
                    "alert_strikes": config.strike.alert_strikes.model_copy(
                        update={
                            "itm3": False, "itm2": False, "itm1": False,
                            "atm": True,
                            "otm1": True, "otm2": False, "otm3": False,
                        }
                    )
                }
            )
        }
    )
    choices = get_alert_strikes(
        feed=feed, symbol="NIFTY", spot_price=24030.0, option_type="CE",
        expiry="2026-06-02", config=filtered,
    )
    relations = [c.relation for c in choices]
    assert relations == ["ATM", "OTM1"]


def test_strikes_order_config_only_atm(config: AppConfig) -> None:
    feed = _FakeFeed([24000, 24050, 24100])
    choices = get_order_strikes(
        feed=feed, symbol="NIFTY", spot_price=24030.0, option_type="CE",
        expiry="2026-06-02", config=config,
    )
    # Default config: only ATM is ON for order_strikes.
    assert [c.relation for c in choices] == ["ATM"]
    assert choices[0].strike == 24050


def test_strikes_missing_in_chain_skipped(config: AppConfig) -> None:
    # ITM1 (24000) is missing from the chain — should be silently skipped.
    feed = _FakeFeed([24050, 24100])
    forced = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={
                    "alert_strikes": config.strike.alert_strikes.model_copy(
                        update={
                            "itm3": False, "itm2": False, "itm1": True,
                            "atm": True,
                            "otm1": True, "otm2": False, "otm3": False,
                        }
                    )
                }
            )
        }
    )
    choices = get_alert_strikes(
        feed=feed, symbol="NIFTY", spot_price=24030.0, option_type="CE",
        expiry="2026-06-02", config=forced,
    )
    relations = [c.relation for c in choices]
    assert "ITM1" not in relations
    assert "ATM" in relations
    assert "OTM1" in relations


def test_strikes_empty_chain_returns_empty(config: AppConfig) -> None:
    feed = _FakeFeed([])
    choices = get_alert_strikes(
        feed=feed, symbol="NIFTY", spot_price=24030.0, option_type="CE",
        expiry="2026-06-02", config=config,
    )
    assert choices == []


def test_strikes_banknifty_uses_100_interval(config: AppConfig) -> None:
    feed = _FakeFeed([50800, 50900, 51000])
    forced = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={
                    "alert_strikes": config.strike.alert_strikes.model_copy(
                        update={
                            "itm3": False, "itm2": False, "itm1": True,
                            "atm": True,
                            "otm1": True, "otm2": False, "otm3": False,
                        }
                    )
                }
            )
        }
    )
    choices = get_alert_strikes(
        feed=feed, symbol="BANKNIFTY", spot_price=50930.0, option_type="CE",
        expiry="2026-06-25", config=forced,
    )
    strikes = [c.strike for c in choices]
    # ATM = round(50930/100)*100 = 50900; CE -> ITM1 50800, OTM1 51000.
    assert strikes == [50800, 50900, 51000]


# ---------------------------------------------------------------------------
# Config validators
# ---------------------------------------------------------------------------


def test_config_alert_strikes_all_off_rejected(config: AppConfig) -> None:
    """The AlertStrikesConfig validator must reject all-OFF — bot would
    never alert otherwise."""
    from src.config_loader import AlertStrikesConfig
    with pytest.raises(Exception):
        AlertStrikesConfig.model_validate({
            "itm3": False, "itm2": False, "itm1": False,
            "atm": False,
            "otm1": False, "otm2": False, "otm3": False,
        })


def test_config_order_strikes_blocked_when_order_mode_on(
    config: AppConfig,
) -> None:
    """If mode.order_place_mode is ON but all order_strikes are OFF, the
    AppConfig-level validator must trip."""
    from src.config_loader import AppConfig as _AppConfig

    raw = config.model_dump()
    raw["mode"]["order_place_mode"] = True
    raw["strike"]["order_strikes"] = {"itm": False, "atm": False, "otm": False}
    with pytest.raises(Exception):
        _AppConfig.model_validate(raw)
