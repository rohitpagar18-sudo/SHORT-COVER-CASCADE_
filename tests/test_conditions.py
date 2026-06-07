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


def _with_c0_enabled(config: AppConfig) -> AppConfig:
    """Return a copy of config with the C0 spot-trend filter ON.

    The default config ships with c0_spot_trend_filter_enabled=False
    (C0 is reported as SKIPPED and treated as PASS). Tests that exercise
    the real C0 direction logic need to flip the toggle.
    """
    return config.model_copy(
        update={
            "conditions": config.conditions.model_copy(
                update={"c0_spot_trend_filter_enabled": True}
            )
        }
    )


def _without_c5(config: AppConfig) -> AppConfig:
    """Return a config copy with C5 ADX disabled.

    Used by the pre-Phase-6.1 tests that assert exact counts on C0-C4
    only. Phase 6.1 config defaults to c5_adx.enabled=ON (shadow mode),
    which would otherwise add a 6th entry to results.
    """
    new_c5 = config.conditions.c5_adx.model_copy(update={"enabled": False})
    return config.model_copy(
        update={"conditions": config.conditions.model_copy(update={"c5_adx": new_c5})}
    )


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
    # Phase 6.1: this test predates C5. Disable C5 explicitly so the
    # exact-count assertions still mean "all C0-C4 pass" and nothing more.
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24530,
        spot_vwap=24500,
        option_type="CE",
        config=_without_c5(config),
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
    # C0 filter must be ON for this assertion (default is OFF).
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24400,
        spot_vwap=24500,
        option_type="CE",
        config=_with_c0_enabled(config),
    )
    assert result.all_passed is False
    assert "C0" in result.failed_conditions()


def test_all_conditions_runs_every_check(config: AppConfig) -> None:
    """Orchestrator must not short-circuit: every result must be present.

    Uses C0 filter ON so C0 itself can fail too (default is OFF, where
    C0 is reported as SKIPPED/PASS).
    """
    s = make_snapshot(
        close=95, vwap=100, open=100, is_green=False,
        rsi=30, rsi_ma=40,
        oi=3_000_000, oi_ma=2_000_000,
        volume=1_000, volume_ma=10_000,
    )
    # Phase 6.1: predates C5; disable C5 so the exact-name assertion
    # still pinpoints which C0-C4 entries appear (and in what order).
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24400,
        spot_vwap=24500,
        option_type="CE",
        config=_with_c0_enabled(_without_c5(config)),
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


# ---------------------------------------------------------------------------
# Phase 6.1 — C5 ADX shadow mode + gating semantics
# ---------------------------------------------------------------------------


from src.conditions import check_c5_adx  # noqa: E402


def _with_c5(
    config: AppConfig,
    *,
    enabled: bool = True,
    gating: bool = False,
    adx_min: float = 20.0,
    require_rising: bool = True,
    use_di_alignment: bool = True,
) -> AppConfig:
    """Return a config copy with c5_adx set to the requested values."""
    new_c5 = config.conditions.c5_adx.model_copy(update={
        "enabled": enabled,
        "gating": gating,
        "adx_min": adx_min,
        "require_rising": require_rising,
        "use_di_alignment": use_di_alignment,
    })
    new_cond = config.conditions.model_copy(update={"c5_adx": new_c5})
    return config.model_copy(update={"conditions": new_cond})


def _passing_snapshot() -> IndicatorSnapshot:
    return make_snapshot(
        close=110, vwap=100, open=105, is_green=True,
        rsi=65, rsi_ma=55,
        oi=1_000_000, oi_ma=2_000_000,
        volume=15_000, volume_ma=10_000,
    )


def _c5_inputs(
    adx=27.0, adx_prev=24.0, di_plus=30.0, di_minus=15.0, ok=True, reason="",
) -> dict:
    if not ok:
        return {"ok": False, "reason": reason}
    return {
        "ok": True,
        "adx": adx, "adx_prev": adx_prev,
        "di_plus": di_plus, "di_minus": di_minus,
    }


# ----- pure function tests -----


def test_c5_pass_aligned_rising_above_min(config: AppConfig) -> None:
    cfg = _with_c5(config).conditions.c5_adx
    ok, reason, fields = check_c5_adx(
        adx=27.0, adx_prev=24.0, di_plus=30.0, di_minus=15.0,
        option_type="CE", cfg=cfg,
    )
    assert ok is True
    assert "PASS" in reason
    assert fields["di_aligned"] is True


def test_c5_fail_di_misaligned(config: AppConfig) -> None:
    cfg = _with_c5(config).conditions.c5_adx
    # CE but +DI < -DI -> misaligned
    ok, reason, _ = check_c5_adx(
        adx=27.0, adx_prev=24.0, di_plus=15.0, di_minus=30.0,
        option_type="CE", cfg=cfg,
    )
    assert ok is False
    assert "DI misaligned" in reason


def test_c5_fail_adx_flat_or_falling(config: AppConfig) -> None:
    cfg = _with_c5(config).conditions.c5_adx
    ok, reason, _ = check_c5_adx(
        adx=22.0, adx_prev=22.0, di_plus=30.0, di_minus=15.0,
        option_type="CE", cfg=cfg,
    )
    assert ok is False
    assert "flat/falling" in reason


def test_c5_fail_below_adx_min(config: AppConfig) -> None:
    cfg = _with_c5(config).conditions.c5_adx
    ok, reason, _ = check_c5_adx(
        adx=18.0, adx_prev=15.0, di_plus=30.0, di_minus=15.0,
        option_type="CE", cfg=cfg,
    )
    assert ok is False
    assert "below" in reason


def test_c5_use_di_alignment_off_drops_di_requirement(config: AppConfig) -> None:
    cfg = _with_c5(config, use_di_alignment=False).conditions.c5_adx
    ok, _reason, _ = check_c5_adx(
        adx=27.0, adx_prev=24.0, di_plus=15.0, di_minus=30.0,
        option_type="CE", cfg=cfg,
    )
    assert ok is True


def test_c5_require_rising_off_drops_rise_requirement(config: AppConfig) -> None:
    cfg = _with_c5(config, require_rising=False).conditions.c5_adx
    ok, _reason, _ = check_c5_adx(
        adx=27.0, adx_prev=27.0, di_plus=30.0, di_minus=15.0,
        option_type="CE", cfg=cfg,
    )
    assert ok is True


def test_c5_pe_di_alignment(config: AppConfig) -> None:
    cfg = _with_c5(config).conditions.c5_adx
    # PE needs -DI > +DI
    ok, _, fields = check_c5_adx(
        adx=27.0, adx_prev=24.0, di_plus=15.0, di_minus=30.0,
        option_type="PE", cfg=cfg,
    )
    assert ok is True
    assert fields["di_aligned"] is True


# ----- orchestrator integration: shadow-mode gating semantics -----


def test_c5_disabled_absent_from_results(config: AppConfig) -> None:
    """enabled=False → C5 must not appear in results at all."""
    cfg = _with_c5(config, enabled=False)
    result = check_all_conditions(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        config=cfg, c5_inputs=_c5_inputs(),
    )
    names = [r.name for r in result.results]
    assert names == ["C0", "C1", "C2", "C3", "C4"]
    assert result.by_name("C5") is None
    assert result.c5_fields is None
    assert result.all_passed is True


def test_c5_shadow_pass_does_not_change_all_passed(config: AppConfig) -> None:
    cfg_no_c5 = _with_c5(config, enabled=False)
    cfg_shadow = _with_c5(config, enabled=True, gating=False)

    base = check_all_conditions(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        config=cfg_no_c5,
    )
    with_shadow = check_all_conditions(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        config=cfg_shadow, c5_inputs=_c5_inputs(),
    )
    # Shadow C5 PASS — all_passed unchanged.
    assert base.all_passed is True
    assert with_shadow.all_passed is True
    c5 = with_shadow.by_name("C5")
    assert c5 is not None and c5.passed is True
    assert c5.gating is False


def test_c5_shadow_fail_does_not_block_alert(config: AppConfig) -> None:
    """C1–C4 all pass; C5 fails — alert STILL fires because C5 is non-gating."""
    cfg = _with_c5(config, enabled=True, gating=False)
    # Make C5 fail (below adx_min) — passing C1-C4 snapshot otherwise.
    result = check_all_conditions(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        config=cfg,
        c5_inputs=_c5_inputs(adx=10.0, adx_prev=8.0),
    )
    assert result.all_passed is True, (
        "Shadow C5 failure must not block C1-C4 alert"
    )
    c5 = result.by_name("C5")
    assert c5 is not None and c5.passed is False
    assert c5.gating is False


def test_c5_gating_flag_is_sole_determinant_of_all_passed(config: AppConfig) -> None:
    """Toggling ONLY c5_adx.gating flips all_passed when C5 fails.

    Everything else (the option snapshot, the C5 inputs, the spot context)
    is held constant. The only change is gating False -> True.
    """
    base_kwargs = dict(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        c5_inputs=_c5_inputs(adx=10.0, adx_prev=8.0),  # C5 will FAIL
    )
    cfg_shadow = _with_c5(config, enabled=True, gating=False)
    cfg_gating = _with_c5(config, enabled=True, gating=True)

    shadow_result = check_all_conditions(config=cfg_shadow, **base_kwargs)
    gating_result = check_all_conditions(config=cfg_gating, **base_kwargs)

    assert shadow_result.all_passed is True   # C5 non-gating, fail is logged only
    assert gating_result.all_passed is False  # C5 now gating, fail blocks


def test_c5_gating_true_with_pass_keeps_alert(config: AppConfig) -> None:
    """Flipping gating ON but C5 passes — alert still fires."""
    cfg = _with_c5(config, enabled=True, gating=True)
    result = check_all_conditions(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        config=cfg, c5_inputs=_c5_inputs(),
    )
    assert result.all_passed is True
    c5 = result.by_name("C5")
    assert c5 is not None and c5.passed is True and c5.gating is True


def test_c5_insufficient_data_in_shadow_mode_does_not_block(config: AppConfig) -> None:
    """ok=False C5 inputs → C5 ❌ with insufficient-data reason, alert still fires."""
    cfg = _with_c5(config, enabled=True, gating=False)
    result = check_all_conditions(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        config=cfg,
        c5_inputs=_c5_inputs(ok=False, reason="warm-up"),
    )
    assert result.all_passed is True  # shadow → cannot block
    c5 = result.by_name("C5")
    assert c5 is not None and c5.passed is False
    assert "insufficient" in c5.reason.lower()
    # c5_fields populated with explicit nulls for parquet pipeline.
    assert result.c5_fields == {
        "adx": None, "adx_prev": None,
        "di_plus": None, "di_minus": None, "di_aligned": None,
    }


def test_c5_insufficient_data_in_gating_mode_blocks(config: AppConfig) -> None:
    """ok=False C5 inputs in gating mode → blocks alert (cannot default to pass)."""
    cfg = _with_c5(config, enabled=True, gating=True)
    result = check_all_conditions(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        config=cfg,
        c5_inputs=_c5_inputs(ok=False, reason="warm-up"),
    )
    assert result.all_passed is False


# ----- orchestrator-level integration: crash isolation -----


def test_c5_crash_isolation_in_main_orchestrator(config: AppConfig, monkeypatch) -> None:
    """Forced C5 exception path: C5 logged as data_issue, C1-C4 alert STILL fires.

    Simulates the orchestrator's wrapper by raising inside check_c5_adx
    and confirming the safety net (the second check_all_conditions call
    with ok=False c5_inputs) keeps the alert alive.
    """
    from src.conditions import all_conditions as ac

    def boom(*args, **kwargs):
        raise RuntimeError("forced C5 explosion")

    monkeypatch.setattr(ac, "check_c5_adx", boom)
    cfg = _with_c5(config, enabled=True, gating=False)

    # First call mirrors the orchestrator's try/except: it raises.
    with pytest.raises(RuntimeError, match="forced C5 explosion"):
        check_all_conditions(
            option_snapshot=_passing_snapshot(),
            spot_close=24530, spot_vwap=24500, option_type="CE",
            config=cfg, c5_inputs=_c5_inputs(),
        )

    # Orchestrator falls back to ok=False inputs → check_all_conditions
    # succeeds and the alert still fires (C5 non-gating).
    monkeypatch.undo()
    fallback = check_all_conditions(
        option_snapshot=_passing_snapshot(),
        spot_close=24530, spot_vwap=24500, option_type="CE",
        config=cfg, c5_inputs={"ok": False, "reason": "crash: forced"},
    )
    assert fallback.all_passed is True  # C1-C4 alert survives
