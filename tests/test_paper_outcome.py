"""Phase 5D — paper-outcome wrapper tests.

Asserts that ``compute_paper_outcome`` PROPERLY delegates to the
Phase 5B-A kernel — it must never re-implement the candle walk.
We pin the kernel's verdict against a mock candle frame and check
the wrapper produces matching R-multiples + paper P&L.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.dashboard.outcome_replay import (
    HARD_EXIT, PARTIAL, SL_HIT, TP1_HIT, TP2_HIT, replay_alert,
)
from src.paper.outcome import (
    OUTCOME_NO_DATA, OUTCOME_OPEN_SQOFF, OUTCOME_SL,
    OUTCOME_TP1_BE, OUTCOME_TP1_HIT, OUTCOME_TP2,
    compute_paper_outcome,
)

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def base_alert():
    return {
        "alert_id": "test-1",
        "timestamp_ist": datetime(2026, 5, 27, 10, 0, tzinfo=IST).isoformat(),
        "candle_ts": datetime(2026, 5, 27, 10, 0, tzinfo=IST),
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "expiry": "2026-06-02",
        "entry": 150.0,
        "sl": 140.0,
        "tp1": 165.0,
        "tp2": 175.0,
        "lots": 3,
        "day_type": "Normal",
    }


def _candle(hh: int, mm: int, o: float, h: float, low: float, c: float):
    return {
        "timestamp": datetime(2026, 5, 27, hh, mm, tzinfo=IST),
        "open": o, "high": h, "low": low, "close": c,
        "volume": 1000.0, "oi": 100000,
    }


def _prefix() -> list[dict]:
    return [
        _candle(9, mm, 148, 152, 148, 150)
        for mm in (15, 20, 25, 30, 35, 40, 45, 50, 55)
    ] + [_candle(10, 0, 150, 152, 149, 150)]


def test_sl_outcome_mapping(base_alert, config):
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 152, 138, 142),  # low crosses SL
    ])
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    # Must match the kernel's verdict exactly.
    kernel = replay_alert(base_alert, candles, config)
    assert kernel is not None
    assert kernel.auto_order_status == SL_HIT
    assert po.outcome == OUTCOME_SL
    assert po.realized_R == -1.0
    # paper_pnl = pnl_per_unit * lots * lot_size (NIFTY 65 in config)
    expected_pnl = kernel.auto_pnl_per_unit * 3 * config.instruments.nifty_lot_size
    assert po.paper_pnl == pytest.approx(expected_pnl)


def test_tp2_outcome_mapping(base_alert, config):
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 176, 160, 174),
    ])
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    kernel = replay_alert(base_alert, candles, config)
    assert kernel.auto_order_status == TP2_HIT
    assert po.outcome == OUTCOME_TP2
    # Normal day → 2.5R from config (default).
    assert po.realized_R == pytest.approx(config.paper_trading.tp2_R_normal)


def test_tp1_be_outcome_mapping(base_alert, config):
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),    # TP1
        _candle(10, 10, 165, 168, 149, 160),   # back to breakeven
    ])
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    kernel = replay_alert(base_alert, candles, config)
    assert kernel.auto_order_status == PARTIAL
    assert po.outcome == OUTCOME_TP1_BE
    # Normal day → 0.75R.
    assert po.realized_R == pytest.approx(config.paper_trading.tp1_then_be_R_normal)


def test_eod_flat_is_open_sqoff(base_alert, config):
    # Hover band — never touches SL or TP1.
    rows = _prefix()
    for hh in range(10, 15):
        for mm in (5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
            if hh == 10 and mm < 5:
                continue
            rows.append(_candle(hh, mm, 152, 158, 148, 153))
    candles = pd.DataFrame(rows)
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    assert po.outcome == OUTCOME_OPEN_SQOFF
    # OPEN_SQOFF computes R from actual P&L / R per unit.
    assert po.realized_R == pytest.approx(0.3)  # (153-150)/10


def test_intrabar_ambiguity_propagated(base_alert, config):
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 139, 160),  # SL and TP1 in same candle
    ])
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    assert po.outcome == OUTCOME_SL
    assert po.intrabar_ambiguous is True


def test_no_candles_returns_no_data(base_alert, config):
    po = compute_paper_outcome(base_alert, candles=None, app_config=config)
    assert po.outcome == OUTCOME_NO_DATA
    assert po.realized_R == 0.0


def test_close_only_fidelity_detected(base_alert, config):
    # Build a frame where O=H=L=C — typical of legacy close-only rows.
    rows = []
    for mm in (15, 20, 25, 30, 35, 40, 45, 50, 55):
        v = 150.0
        rows.append({
            "timestamp": datetime(2026, 5, 27, 9, mm, tzinfo=IST),
            "open": v, "high": v, "low": v, "close": v,
            "volume": 100, "oi": 100000,
        })
    rows.append({
        "timestamp": datetime(2026, 5, 27, 10, 0, tzinfo=IST),
        "open": 150, "high": 150, "low": 150, "close": 150,
        "volume": 100, "oi": 100000,
    })
    candles = pd.DataFrame(rows)
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    assert po.fidelity == "close_only"
