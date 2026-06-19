"""SL method shadow-comparison tests.

Pins that replay_alert_all_methods populates all three method slots and
that the authoritative slot matches replay_alert for the live method.

Conventions mirror test_outcome_replay.py:
  Entry = 150.0, SL = 140.0, TP1 = 165.0, TP2 = 175.0 (R = 10).
  Alert candle at 10:00 IST; walk starts at 10:05.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.dashboard.outcome_replay import (
    MultiMethodResult,
    replay_alert,
    replay_alert_all_methods,
)

IST = ZoneInfo("Asia/Kolkata")

ENTRY = 150.0
SL = 140.0
TP1 = 165.0
TP2 = 175.0
ALERT_TS = datetime(2026, 5, 27, 10, 0, tzinfo=IST)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candle(hh: int, mm: int, o: float, h: float, low: float, c: float, vol: float = 1000.0):
    ts = datetime(2026, 5, 27, hh, mm, tzinfo=IST)
    return {"timestamp": ts, "open": o, "high": h, "low": low, "close": c, "volume": vol}


def _session_prefix() -> list[dict]:
    rows = []
    for mm in (15, 20, 25, 30, 35, 40, 45, 50, 55):
        rows.append(_candle(9, mm, 148, 152, 148, 150))
    rows.append(_candle(10, 0, 150, 152, 149, 150))
    return rows


def _sl_hit_candles() -> pd.DataFrame:
    rows = _session_prefix() + [
        _candle(10, 5, 150, 152, 138, 141),  # low crosses SL=140
    ]
    return pd.DataFrame(rows)


def _tp2_candles() -> pd.DataFrame:
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),   # TP1 touch (high >= 165)
        _candle(10, 10, 165, 176, 160, 174),  # TP2 touch (high >= 175)
    ]
    return pd.DataFrame(rows)


def _alert_row() -> dict:
    return {
        "timestamp_ist": ALERT_TS.isoformat(),
        "entry": ENTRY,
        "sl": SL,
        "tp1": TP1,
        "tp2": TP2,
    }


# ---------------------------------------------------------------------------
# Minimal mock config
# ---------------------------------------------------------------------------


class _MockSmaTrail:
    sma_period = 19
    activate_after_minutes = 15
    update_interval_minutes = 15
    follow_direction = "both"


class _MockStopLoss:
    method = 1
    hard_exit_red_candle_below_vwap = False
    sma_trail = _MockSmaTrail()


class _MockRiskReward:
    move_sl_to_breakeven_after_tp1 = False
    trail_sl_after_tp1 = False


class _MockTimeRules:
    hard_squareoff_time = "15:00"


class _MockConfig:
    def __init__(self, live_method: int = 1):
        self.stop_loss = _MockStopLoss()
        self.stop_loss.method = live_method
        self.risk_reward = _MockRiskReward()
        self.time_rules = _MockTimeRules()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_three_columns_populate_sl_hit():
    """All three method slots are populated even when SL is hit early."""
    candles = _sl_hit_candles()
    result = replay_alert_all_methods(_alert_row(), candles, _MockConfig())

    assert isinstance(result, MultiMethodResult)
    assert result.method1 is not None
    assert result.method2 is not None
    assert result.method3 is not None

    assert isinstance(result.method1.auto_pnl_per_unit, float)
    assert isinstance(result.method2.auto_pnl_per_unit, float)
    assert isinstance(result.method3.auto_pnl_per_unit, float)

    assert isinstance(result.method1.auto_exit_reason, str)
    assert isinstance(result.method2.auto_exit_reason, str)
    assert isinstance(result.method3.auto_exit_reason, str)


def test_all_three_columns_populate_tp2_hit():
    """All three method slots are populated when TP2 is hit."""
    candles = _tp2_candles()
    result = replay_alert_all_methods(_alert_row(), candles, _MockConfig())

    assert result.method1 is not None
    assert result.method2 is not None
    assert result.method3 is not None

    # Under all three methods the trade exits at TP2 (no trail can move SL
    # above entry before the fast TP2 candle).
    assert result.method1.auto_pnl_per_unit == pytest.approx(20.0)
    assert result.method2.auto_pnl_per_unit == pytest.approx(20.0)
    assert result.method3.auto_pnl_per_unit == pytest.approx(20.0)


def test_authoritative_matches_live_method1():
    """When live method=1, method1 slot must equal replay_alert result."""
    candles = _sl_hit_candles()
    cfg = _MockConfig(live_method=1)
    alert_row = _alert_row()

    authoritative = replay_alert(alert_row, candles, cfg)
    multi = replay_alert_all_methods(alert_row, candles, cfg)

    assert authoritative is not None
    assert multi.method1 is not None
    assert authoritative.auto_pnl_per_unit == pytest.approx(
        multi.method1.auto_pnl_per_unit
    )
    assert authoritative.auto_exit_reason == multi.method1.auto_exit_reason


def test_authoritative_matches_live_method3():
    """When live method=3, method3 slot must equal replay_alert result."""
    candles = _tp2_candles()
    cfg = _MockConfig(live_method=3)
    alert_row = _alert_row()

    authoritative = replay_alert(alert_row, candles, cfg)
    multi = replay_alert_all_methods(alert_row, candles, cfg)

    assert authoritative is not None
    assert multi.method3 is not None
    assert authoritative.auto_pnl_per_unit == pytest.approx(
        multi.method3.auto_pnl_per_unit
    )
    assert authoritative.auto_exit_reason == multi.method3.auto_exit_reason


def test_none_returned_for_no_post_alert_candles():
    """All three slots are None when no post-alert candles exist."""
    only_prefix = pd.DataFrame(_session_prefix())
    result = replay_alert_all_methods(_alert_row(), only_prefix, _MockConfig())

    assert result.method1 is None
    assert result.method2 is None
    assert result.method3 is None


def test_shadow_columns_never_affect_paper_pnl():
    """Shadow method columns must not leak into paper_pnl calculations.

    This is a structural / import test: the paper module must not import
    anything from the shadow comparison path.
    """
    import importlib
    import src.paper.outcome as paper_outcome

    src_text = importlib.util.find_spec("src.paper.outcome").origin
    with open(src_text, "r", encoding="utf-8") as fh:
        code = fh.read()

    assert "replay_alert_all_methods" not in code
    assert "SHADOW_METHOD_COLUMNS" not in code
    assert "auto_pnl_method" not in code
