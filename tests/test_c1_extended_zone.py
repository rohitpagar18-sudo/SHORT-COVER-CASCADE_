"""Phase 5.2 — C1 extended zone tests.

The orchestrator now logs ``would_alert_extended`` events when:
  - the option sits between c1_max_distance_pct and c1_extended_zone_max_pct
    above its own VWAP, AND
  - C1 is the only failing condition (all others would pass).

Strategy alerts are NOT fired for extended-zone events. They exist only
so we can study them later and tune the C1 threshold.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.conditions.all_conditions import check_all_conditions
from src.conditions.c1_option_price_vwap import check_c1


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_snapshot(**overrides):
    from src.indicators.calculator import IndicatorSnapshot

    base = dict(
        vwap=100.0, rsi=65.0, rsi_ma=55.0,
        oi=800_000.0, oi_ma=1_000_000.0,
        volume=15_000.0, volume_ma=5_000.0,
        close=120.0, open=110.0, high=125.0, low=109.0,
        timestamp=pd.Timestamp("2026-05-26 11:25", tz="Asia/Kolkata"),
        is_green=True,
    )
    base.update(overrides)
    return IndicatorSnapshot(**base)


def _make_config(c1_max=30.0, ext_max=50.0, ext_enabled=True, log_ext=True):
    return _NS(
        conditions=_NS(
            c3_rsi_min=50, c3_rsi_max=80,
            c1_max_distance_pct=c1_max,
            c1_extended_zone_enabled=ext_enabled,
            c1_extended_zone_max_pct=ext_max,
        ),
        strike=_NS(late_entry_threshold_percent=c1_max),
        logging=_NS(log_extended_zone=log_ext),
    )


# ---------------------------------------------------------------------------
# C1 returns the third value
# ---------------------------------------------------------------------------


def test_check_c1_returns_three_tuple() -> None:
    s = _make_snapshot(close=115, vwap=100)
    out = check_c1(s, late_entry_threshold_pct=30)
    assert len(out) == 3
    ok, reason, pct = out
    assert ok is True
    assert pct == pytest.approx(15.0)


def test_check_c1_late_entry_reports_pct() -> None:
    s = _make_snapshot(close=135, vwap=100)
    ok, _r, pct = check_c1(s, late_entry_threshold_pct=30)
    assert ok is False
    assert pct == pytest.approx(35.0)


def test_check_c1_below_vwap_pct_is_negative() -> None:
    s = _make_snapshot(close=98, vwap=100, is_green=True, open=99)
    _ok, _r, pct = check_c1(s, late_entry_threshold_pct=30)
    assert pct == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# Config threshold is honoured
# ---------------------------------------------------------------------------


def test_c1_config_threshold_25_rejects_30pct_above() -> None:
    s = _make_snapshot(close=130, vwap=100)
    ok, _r, _pct = check_c1(s, late_entry_threshold_pct=25)
    assert ok is False


def test_c1_config_threshold_via_all_conditions() -> None:
    """check_all_conditions reads from config.conditions.c1_max_distance_pct."""
    s = _make_snapshot(close=130, vwap=100)
    cfg = _make_config(c1_max=25.0)
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24530,
        spot_vwap=24500,
        option_type="CE",
        config=cfg,
    )
    assert result.by_name("C1").passed is False
    assert result.opt_above_vwap_pct == pytest.approx(30.0)


def test_c1_extended_zone_records_pct_on_result() -> None:
    s = _make_snapshot(close=137, vwap=100)
    cfg = _make_config(c1_max=30.0)
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24530,
        spot_vwap=24500,
        option_type="CE",
        config=cfg,
    )
    assert result.opt_above_vwap_pct == pytest.approx(37.0)


# ---------------------------------------------------------------------------
# Orchestrator-level: would_alert_extended logging
# ---------------------------------------------------------------------------


@pytest.fixture
def orch_with_logger(tmp_path):
    from src.main import Orchestrator

    o = object.__new__(Orchestrator)
    o.config = _make_config()
    o.signal_logger = MagicMock()
    o.gap_log_path = tmp_path / "gap_log.jsonl"
    o.session_vix = 14.0
    o.session_vix_info = _NS(regime=_NS(value="Normal"), method1_multiplier=1.0)
    o.state = MagicMock()
    o.state.can_re_enter = MagicMock(return_value=(True, "ok"))
    o.state.get_daily_sl_count = MagicMock(return_value=0)
    o.session_scan_count = 0
    o.session_alert_count = 0
    o.session_nifty_alerts = 0
    o.session_bn_alerts = 0
    return o


def _make_result(*, c1_pass: bool, opt_pct: float, others_pass: bool):
    from src.conditions.all_conditions import (
        AllConditionsResult,
        ConditionResult,
    )

    pass_other = others_pass
    results = [
        ConditionResult("C0", pass_other, "ok"),
        ConditionResult("C1", c1_pass, "ok" if c1_pass else "late entry"),
        ConditionResult("C2", pass_other, "ok"),
        ConditionResult("C3", pass_other, "ok"),
        ConditionResult("C4", pass_other, "ok"),
    ]
    return AllConditionsResult(
        all_passed=all(r.passed for r in results),
        results=results,
        opt_above_vwap_pct=opt_pct,
    )


def test_extended_zone_logged_when_only_c1_fails(orch_with_logger) -> None:
    o = orch_with_logger
    signal_record = {
        "event_type": "scan",
        "opt_above_vwap_pct": 37.0,
    }
    result = _make_result(c1_pass=False, opt_pct=37.0, others_pass=True)
    o._maybe_log_extended_zone(signal_record, result)
    o.signal_logger.log_signal.assert_called_once()
    payload = o.signal_logger.log_signal.call_args[0][0]
    assert payload["event_type"] == "would_alert_extended"


def test_extended_zone_not_logged_when_outside_zone(orch_with_logger) -> None:
    o = orch_with_logger
    signal_record = {
        "event_type": "scan",
        "opt_above_vwap_pct": 60.0,  # outside the (30, 50] window
    }
    result = _make_result(c1_pass=False, opt_pct=60.0, others_pass=True)
    o._maybe_log_extended_zone(signal_record, result)
    o.signal_logger.log_signal.assert_not_called()


def test_extended_zone_not_logged_when_other_condition_also_fails(
    orch_with_logger,
) -> None:
    o = orch_with_logger
    signal_record = {
        "event_type": "scan",
        "opt_above_vwap_pct": 37.0,
    }
    result = _make_result(c1_pass=False, opt_pct=37.0, others_pass=False)
    o._maybe_log_extended_zone(signal_record, result)
    o.signal_logger.log_signal.assert_not_called()


def test_extended_zone_disabled_when_toggle_off(orch_with_logger) -> None:
    o = orch_with_logger
    o.config = _make_config(log_ext=False)
    signal_record = {
        "event_type": "scan",
        "opt_above_vwap_pct": 37.0,
    }
    result = _make_result(c1_pass=False, opt_pct=37.0, others_pass=True)
    o._maybe_log_extended_zone(signal_record, result)
    o.signal_logger.log_signal.assert_not_called()
