"""Phase 5B-A — virtual exit-replay tests.

Mock 5-min option candle frames feed the exit kernel directly. No
broker calls. The kernel is pure, so these tests pin the exit logic
precisely — they are also the contract Phase 7's backtest harness
relies on.

Conventions used across the fixtures:

  - Alert candle is at 10:00 IST. The walk starts at the NEXT candle
    (10:05). Entry = 150.0, SL = 140.0, TP1 = 165.0, TP2 = 175.0
    (i.e. R = 10, 1.5R / 2.5R normal-day multipliers). Hard square-off
    at 15:00.
  - Helper ``_candle`` builds one row; helper ``_session`` strings
    them together. The first few candles before the alert give the
    session VWAP something to anchor on.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.dashboard.outcome_replay import (
    EOD_FLAT,
    ExitConfig,
    HARD_EXIT,
    PARTIAL,
    SL_HIT,
    TP1_HIT,
    TP2_HIT,
    replay_alert,
    replay_exits,
)

IST = ZoneInfo("Asia/Kolkata")


ENTRY = 150.0
SL = 140.0
TP1 = 165.0
TP2 = 175.0

ALERT_TS = datetime(2026, 5, 27, 10, 0, tzinfo=IST)


def _candle(hh: int, mm: int, o: float, h: float, low: float, c: float, vol: float = 1000.0):
    ts = datetime(2026, 5, 27, hh, mm, tzinfo=IST)
    return {
        "timestamp": ts,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": vol,
        "oi": 100000,
    }


def _session_prefix() -> list[dict]:
    """Pre-alert candles to give VWAP a stable anchor near ENTRY."""
    rows = []
    for offset, mm in enumerate((15, 20, 25, 30, 35, 40, 45, 50, 55)):
        rows.append(_candle(9, mm, 148, 152, 148, 150))
    rows.append(_candle(10, 0, 150, 152, 149, 150))  # the alert candle
    return rows


def _exit_cfg(
    move_be: bool = True,
    trail: bool = False,
    hard_exit_rule: bool = True,
) -> ExitConfig:
    return ExitConfig(
        move_sl_to_breakeven_after_tp1=move_be,
        trail_sl_after_tp1=trail,
        hard_exit_red_candle_below_vwap=hard_exit_rule,
        hard_squareoff_time=time(15, 0),
    )


# ---------------------------------------------------------------------------
# Pure-kernel tests
# ---------------------------------------------------------------------------


def test_sl_hit_before_any_tp():
    """First post-alert candle dips to SL — full position exits at SL."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 152, 138, 142),  # low crosses SL=140
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(df, ENTRY, SL, TP1, TP2, _exit_cfg(), ALERT_TS)
    assert res is not None
    assert res.auto_order_status == SL_HIT
    assert res.auto_exit_price == pytest.approx(SL)
    assert res.auto_pnl_per_unit == pytest.approx(SL - ENTRY)  # = -10
    assert res.intrabar_ambiguous is False


def test_tp1_then_tp2_two_candles():
    """TP1 then TP2 in two separate candles -> TP2_HIT, full reward."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),    # TP1 touch (high >= 165)
        _candle(10, 10, 165, 176, 160, 174),   # TP2 touch (high >= 175)
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(df, ENTRY, SL, TP1, TP2, _exit_cfg(), ALERT_TS)
    assert res is not None
    assert res.auto_order_status == TP2_HIT
    # 0.5 * (TP1 - entry) + 0.5 * (TP2 - entry) = 0.5*15 + 0.5*25 = 20
    assert res.auto_pnl_per_unit == pytest.approx(20.0)
    assert res.auto_exit_price == pytest.approx(TP2)


def test_tp1_then_breakeven_partial():
    """TP1 banked; second leg later hits the moved-to-breakeven SL."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),    # TP1 touch
        _candle(10, 10, 165, 168, 149, 160),   # dips to 149 — below entry=150
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(df, ENTRY, SL, TP1, TP2, _exit_cfg(move_be=True), ALERT_TS)
    assert res is not None
    assert res.auto_order_status == PARTIAL
    # First leg banks 0.5 * 15 = 7.5; second leg exits at breakeven (entry).
    # Second-leg PnL on breakeven = 0.5 * 0 = 0. Total = ~7.5
    assert res.auto_pnl_per_unit == pytest.approx(7.5)
    assert res.auto_exit_price == pytest.approx(ENTRY)  # breakeven


def test_neither_hit_eod_flat():
    """Walk all the way to 15:00 without touching SL or TP1 -> EOD_FLAT."""
    rows = _session_prefix()
    # 5-min candles 10:05 through 14:55 all hover in [148, 158]
    for hh in range(10, 15):
        for mm in (5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
            if hh == 10 and mm < 5:
                continue
            if hh == 15:
                break
            rows.append(_candle(hh, mm, 152, 158, 148, 153))
    df = pd.DataFrame(rows)
    res = replay_exits(df, ENTRY, SL, TP1, TP2, _exit_cfg(), ALERT_TS)
    assert res is not None
    assert res.auto_order_status == EOD_FLAT
    # The last walked candle is 14:55 with close=153 -> pnl = 3
    assert res.auto_exit_price == pytest.approx(153.0)
    assert res.auto_pnl_per_unit == pytest.approx(3.0)


def test_intrabar_ambiguity_assumes_sl_first():
    """One candle covers both SL and TP1 — SL fires first, ambiguous flag set."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 139, 160),   # low=139 (SL) AND high=166 (TP1)
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(df, ENTRY, SL, TP1, TP2, _exit_cfg(), ALERT_TS)
    assert res is not None
    assert res.auto_order_status == SL_HIT
    assert res.intrabar_ambiguous is True
    assert res.auto_pnl_per_unit == pytest.approx(SL - ENTRY)


def test_hard_exit_red_candle_below_vwap():
    """A complete red candle entirely below the option's session VWAP -> HARD_EXIT."""
    # Pre-alert candles anchor VWAP near 150. Then a single red candle
    # below ~130 makes O/H/L/C all below VWAP and close<open.
    rows = _session_prefix() + [
        _candle(10, 5, 130, 131, 125, 126),   # red AND fully below VWAP ~150
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(df, ENTRY, SL, TP1, TP2, _exit_cfg(), ALERT_TS)
    assert res is not None
    # The first thing to trigger is HARD_EXIT (low=125 also < SL=140, but
    # the kernel checks the hard-exit rule before the SL rule).
    assert res.auto_order_status == HARD_EXIT
    assert res.auto_exit_price == pytest.approx(126.0)
    assert res.auto_pnl_per_unit == pytest.approx(126.0 - ENTRY)  # = -24


def test_tp1_only_then_eod_flat_classifies_as_tp1_hit():
    """TP1 hit; second leg never stops out -> auto_order_status == TP1_HIT."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 149, 164),  # TP1 touched
    ]
    # Then a quiet drift that never touches breakeven (entry=150) nor TP2.
    for hh, mm in [(10, 10), (10, 15), (10, 20), (10, 25), (10, 30),
                   (11, 0), (12, 0), (13, 0), (14, 0), (14, 55)]:
        rows.append(_candle(hh, mm, 162, 168, 158, 162))
    df = pd.DataFrame(rows)
    res = replay_exits(df, ENTRY, SL, TP1, TP2, _exit_cfg(move_be=True), ALERT_TS)
    assert res is not None
    assert res.auto_order_status == TP1_HIT
    # 0.5 * 15 (TP1) + 0.5 * (162 - 150) = 7.5 + 6 = 13.5
    assert res.auto_pnl_per_unit == pytest.approx(13.5)


def test_no_post_alert_candles_returns_none():
    """If there are no candles after the alert, the kernel returns None."""
    rows = _session_prefix()
    df = pd.DataFrame(rows)
    res = replay_exits(df, ENTRY, SL, TP1, TP2, _exit_cfg(), ALERT_TS)
    assert res is None


# ---------------------------------------------------------------------------
# replay_alert adapter — refusal + config wiring
# ---------------------------------------------------------------------------


class _StubRiskReward:
    def __init__(self, *, move_be: bool, trail: bool):
        self.move_sl_to_breakeven_after_tp1 = move_be
        self.trail_sl_after_tp1 = trail


class _StubStopLoss:
    def __init__(self, hard_exit: bool):
        self.hard_exit_red_candle_below_vwap = hard_exit


class _StubTimeRules:
    hard_squareoff_time = "15:00"


class _StubDashboard:
    auto_outcome_tracking = True


class _StubConfig:
    def __init__(self, *, trail: bool = False):
        self.risk_reward = _StubRiskReward(move_be=True, trail=trail)
        self.stop_loss = _StubStopLoss(hard_exit=True)
        self.time_rules = _StubTimeRules()
        self.dashboard = _StubDashboard()


def _alert_row() -> dict:
    return {
        "timestamp_ist": ALERT_TS.isoformat(),
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "entry": ENTRY,
        "sl": SL,
        "tp1": TP1,
        "tp2": TP2,
    }


def test_replay_alert_refuses_when_trail_sl_after_tp1_is_on(caplog):
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 176, 160, 174),
    ]
    df = pd.DataFrame(rows)
    cfg = _StubConfig(trail=True)
    # loguru -> std logging propagation. Capture loguru output via a sink.
    from loguru import logger

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        res = replay_alert(_alert_row(), df, cfg)
    finally:
        logger.remove(sink_id)
    assert res is None
    assert any("trail_sl_after_tp1" in m for m in messages)
    assert any("not implemented in v1" in m for m in messages)


def test_replay_alert_normal_path_returns_result():
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 176, 160, 174),
    ]
    df = pd.DataFrame(rows)
    cfg = _StubConfig(trail=False)
    res = replay_alert(_alert_row(), df, cfg)
    assert res is not None
    assert res.auto_order_status == TP2_HIT


# ---------------------------------------------------------------------------
# Idempotency + manual-precedence (data_writer)
# ---------------------------------------------------------------------------


def test_sync_auto_outcomes_is_idempotent_and_preserves_manual(
    tmp_path, monkeypatch
):
    """A second sync neither re-stamps already-stamped rows nor overwrites
    a manual ``order_status`` cell."""
    import src.dashboard.data_writer as dw
    from src.dashboard.data_writer import sync_auto_outcomes_to_parquet

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(dw, "DATA_DIR", data_dir)

    # Build a Parquet file with one alert row already stamped and one
    # not-yet-stamped row. The second should remain unstamped because
    # there is no candle cache + no feed (cache-only mode).
    rows = [
        {
            "timestamp_ist": ALERT_TS.isoformat(),
            "month": "2026-05",
            "event_type": "alert",
            "symbol": "NIFTY",
            "strike": 24050,
            "option_type": "CE",
            "expiry": "2026-06-02",
            "entry": ENTRY, "sl": SL, "tp1": TP1, "tp2": TP2,
            # Already stamped:
            "auto_order_status": "TP2_HIT",
            "auto_exit_price": 175.0,
            "auto_pnl_per_unit": 20.0,
            # Manual outcome filled by the user:
            "order_status": "TP1_HIT",
            "exit_price": 165.0,
        },
    ]
    pq = pd.DataFrame(rows)
    pq.to_parquet(data_dir / "scc_data_2026-05.parquet", index=False)

    cfg = _StubConfig(trail=False)
    out = sync_auto_outcomes_to_parquet(feed=None, app_config=cfg)
    assert out["alerts_stamped"] == 0  # already stamped row is skipped

    after = pd.read_parquet(data_dir / "scc_data_2026-05.parquet")
    # Manual columns untouched.
    assert after.loc[0, "order_status"] == "TP1_HIT"
    assert after.loc[0, "exit_price"] == 165.0
    # Auto columns preserved (not re-stamped).
    assert after.loc[0, "auto_order_status"] == "TP2_HIT"
    assert after.loc[0, "auto_pnl_per_unit"] == 20.0


def test_sync_auto_outcomes_noop_when_toggle_off(tmp_path, monkeypatch):
    import src.dashboard.data_writer as dw
    from src.dashboard.data_writer import sync_auto_outcomes_to_parquet

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(dw, "DATA_DIR", data_dir)

    cfg = _StubConfig(trail=False)
    cfg.dashboard.auto_outcome_tracking = False

    out = sync_auto_outcomes_to_parquet(feed=None, app_config=cfg)
    assert out["alerts_stamped"] == 0
    assert "OFF" in (out["skipped_reason"] or "")
