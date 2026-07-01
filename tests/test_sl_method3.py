"""SL Method 3 — 19-SMA trailing tests.

Covers the pure ``compute_sma_trail_sl`` helper and the kernel-level
behavior in ``src.dashboard.outcome_replay.replay_alert`` /
``replay_exits`` when ``stop_loss.method == 3`` is configured. All
tests mock the feed via hand-built candle frames.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.dashboard.outcome_replay import (
    EOD_FLAT,
    PARTIAL,
    SL_HIT,
    TP2_HIT,
    ExitConfig,
    replay_alert,
    replay_exits,
)
from src.risk.stop_loss import SmaTrailParams, compute_sma_trail_sl

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
    """Pre-alert 5-min candles seeded with close=150."""
    rows = []
    for mm in (15, 20, 25, 30, 35, 40, 45, 50, 55):
        rows.append(_candle(9, mm, 148, 152, 148, 150))
    rows.append(_candle(10, 0, 150, 152, 149, 150))  # alert candle
    return rows


def _trail(direction: str = "both", n: int = 19, activate: int = 15, update: int = 15) -> SmaTrailParams:
    return SmaTrailParams(
        sma_period=n,
        activate_after_minutes=activate,
        update_interval_minutes=update,
        follow_direction=direction,
    )


def _cfg_method3(trail: SmaTrailParams, hard_exit: bool = True) -> ExitConfig:
    return ExitConfig(
        move_sl_to_breakeven_after_tp1=True,   # ignored under Method 3
        trail_sl_after_tp1=True,                # legacy flag — kernel must not refuse
        hard_exit_red_candle_below_vwap=hard_exit,
        hard_squareoff_time=time(15, 0),
        sl_method=3,
        sma_trail=trail,
    )


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_compute_sma_trail_sl_both_follows_up_and_down() -> None:
    # Both directions honored while the SMA stays above the Method-1 floor.
    assert compute_sma_trail_sl(
        prev_sl=140.0, sma_value=152.0, follow_direction="both", method1_initial_sl=140.0
    ) == 152.0
    assert compute_sma_trail_sl(
        prev_sl=152.0, sma_value=148.0, follow_direction="both", method1_initial_sl=140.0
    ) == 148.0


def test_compute_sma_trail_sl_ratchet_never_loosens() -> None:
    # Up moves are honored.
    assert compute_sma_trail_sl(
        prev_sl=140.0, sma_value=148.0, follow_direction="ratchet", method1_initial_sl=140.0
    ) == 148.0
    # Down moves are clamped to prev_sl.
    assert compute_sma_trail_sl(
        prev_sl=148.0, sma_value=140.0, follow_direction="ratchet", method1_initial_sl=140.0
    ) == 148.0


def test_compute_sma_trail_sl_early_entry_holds_prev_when_sma_none() -> None:
    # When fewer than N candles exist, SMA is None and prev SL is held.
    assert compute_sma_trail_sl(
        prev_sl=140.0, sma_value=None, follow_direction="both", method1_initial_sl=140.0
    ) == 140.0
    assert compute_sma_trail_sl(
        prev_sl=140.0, sma_value=None, follow_direction="ratchet", method1_initial_sl=140.0
    ) == 140.0


def test_compute_sma_trail_sl_both_floored_at_method1_initial() -> None:
    """ISSUE D fix: with ``both``, the SL can never loosen past the
    Method-1 initial SL, even when the SMA drops below it on a pullback."""
    # SMA = 130 < floor 140 → SL floored at 140, NOT 130.
    assert compute_sma_trail_sl(
        prev_sl=151.0, sma_value=130.0, follow_direction="both", method1_initial_sl=140.0
    ) == 140.0
    # SMA exactly at the floor.
    assert compute_sma_trail_sl(
        prev_sl=151.0, sma_value=140.0, follow_direction="both", method1_initial_sl=140.0
    ) == 140.0
    # SMA above the floor still followed down normally.
    assert compute_sma_trail_sl(
        prev_sl=151.0, sma_value=145.0, follow_direction="both", method1_initial_sl=140.0
    ) == 145.0


def test_compute_sma_trail_sl_ratchet_also_respects_floor() -> None:
    """Ratchet is floored too (a no-op in practice — prev_sl already
    >= the initial SL — but the invariant must hold)."""
    assert compute_sma_trail_sl(
        prev_sl=145.0, sma_value=120.0, follow_direction="ratchet", method1_initial_sl=140.0
    ) == 145.0


# ---------------------------------------------------------------------------
# Kernel integration tests
# ---------------------------------------------------------------------------


def test_method3_initial_sl_equals_method1_at_entry() -> None:
    """Before activate_after_minutes elapses, the kernel must use the
    Method-1 SL passed in via ``sl`` — not a trailed value. We exercise
    this by hitting the SL on the very first walked candle."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 152, 138, 142),  # low=138 dips below SL=140
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(
        df, ENTRY, SL, TP1, TP2, _cfg_method3(_trail()), ALERT_TS
    )
    assert res is not None
    assert res.auto_order_status == SL_HIT
    assert res.auto_exit_price == pytest.approx(SL)


def test_method3_trail_does_not_activate_before_activate_after_minutes() -> None:
    """With activate_after_minutes=30 (well beyond the 2 candles we
    feed), no trail tick fires. SL stays at the Method-1 value of 140
    and the audit string carries no trail entries."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 160, 149, 158),
        _candle(10, 10, 158, 164, 156, 160),
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(
        df, ENTRY, SL, TP1, TP2,
        _cfg_method3(_trail(activate=30, update=15, n=3)),
        ALERT_TS,
    )
    assert res is not None
    assert res.auto_order_status == EOD_FLAT
    assert "SMA-trail" not in res.auto_exit_reason


def test_method3_trail_updates_only_every_update_interval() -> None:
    """The SL re-evaluates at +15, +30, +45 etc. from entry, NOT on
    every candle. We construct a sequence where the first tick lifts
    the SL to 151 and the next candle's low is below where a
    per-candle re-evaluation would have set the SL — but above 151.
    The trade must exit at 151 (tick-only) rather than at the lower
    per-candle SMA value."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 152, 149, 150),
        _candle(10, 10, 150, 152, 150, 151),
        # 10:15 TICK. last 3 closes ending at 10:15 = [150, 151, 152].
        # SMA = 151. SL → 151. Low=152 > 151 → safe.
        _candle(10, 15, 151, 153, 152, 152),
        # 10:20 — NOT a tick. SL stays at 151.
        # If the kernel wrongly recomputed each candle: last 3 closes
        # would be [151, 152, 140] → SMA = ~147.7, lower than 151.
        # We assert exit @ 151 (tick-only behavior).
        _candle(10, 20, 152, 152, 140, 140),
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(
        df, ENTRY, SL, TP1, TP2,
        _cfg_method3(_trail(n=3, activate=15, update=15)),
        ALERT_TS,
    )
    assert res is not None
    assert res.auto_order_status == SL_HIT
    assert res.auto_exit_price == pytest.approx(151.0)


def test_method3_both_updates_sl_to_sma_on_tick() -> None:
    """At the first trail tick with follow_direction=both, SL is set
    to the SMA value — even though the SMA is above the original SL.
    We hit the trailed SL within the same candle and verify the exit
    price equals the SMA value (not the original 140)."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 152, 149, 150),
        _candle(10, 10, 150, 152, 149, 151),
        # 10:15 TICK. last 3 closes = [150, 151, 152]. SMA = 151. SL → 151.
        # Then within the SAME candle, low dips to 145 → SL_HIT @ 151
        # (because the trail update fires BEFORE the SL check).
        _candle(10, 15, 151, 153, 145, 152),
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(
        df, ENTRY, SL, TP1, TP2,
        _cfg_method3(_trail(direction="both", n=3, activate=15, update=15)),
        ALERT_TS,
    )
    assert res is not None
    assert res.auto_order_status == SL_HIT
    # 'Both' lifted SL from 140 → 151. Exit at the trailed SL.
    assert res.auto_exit_price == pytest.approx(151.0)
    assert "SMA-trail" in res.auto_exit_reason


def test_method3_both_never_loosens_below_method1_floor_on_pullback() -> None:
    """ISSUE D regression: with follow_direction=both, a sharp pullback
    that drags the SMA BELOW the Method-1 initial SL must NOT loosen the
    stop. The trail update at 10:15 computes SMA = (150+150+110)/3 =
    136.67, which is below the ₹140 Method-1 floor. The floored SL must
    stay at 140 — so the exit price is 140, never 136.67."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 152, 149, 150),
        _candle(10, 10, 150, 152, 149, 150),
        # 10:15 TICK n=3: closes [150, 150, 110] → SMA = 136.67 (< 140).
        # 'both' would loosen to 136.67 WITHOUT the floor. The floored SL
        # holds at 140; the candle low (112) then hits it @ 140.
        _candle(10, 15, 150, 150, 112, 110),
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(
        df, ENTRY, SL, TP1, TP2,
        _cfg_method3(_trail(direction="both", n=3, activate=15, update=15)),
        ALERT_TS,
    )
    assert res is not None
    assert res.auto_order_status == SL_HIT
    # Floored at the Method-1 initial SL of 140 — NOT the 136.67 SMA.
    assert res.auto_exit_price == pytest.approx(140.0)
    assert res.auto_exit_price >= SL


def test_method3_ratchet_runs_to_completion_and_lifts_sl() -> None:
    """Ratchet trail produces a valid outcome with SL lifted upward —
    the helper-level "no loosening" semantics are covered by
    test_compute_sma_trail_sl_ratchet_never_loosens."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 152, 149, 151),
        _candle(10, 10, 151, 153, 150, 152),
        # 10:15 TICK n=3: closes [151, 152, 153] → SMA = 152. SL → 152.
        # Low at 10:15 = 151 ≤ 152 → SL_HIT @ 152.
        _candle(10, 15, 152, 154, 151, 153),
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(
        df, ENTRY, SL, TP1, TP2,
        _cfg_method3(_trail(direction="ratchet", n=3, activate=15, update=15)),
        ALERT_TS,
    )
    assert res is not None
    assert res.auto_order_status == SL_HIT
    assert res.auto_exit_price == pytest.approx(152.0)


def test_method3_post_tp1_keeps_trailing_no_breakeven() -> None:
    """Under Method 3 the breakeven step does NOT apply. The remaining
    50% keeps trailing the SMA. We verify the exit-reason label is
    "trailed SL" (not "breakeven" / "original SL")."""
    rows = _session_prefix() + [
        # TP1 banked at 10:05 (high=166 ≥ 165). close=165.
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 166, 158, 159),
        # 10:15 TICK n=3: closes [165, 159, 156] → SMA = 160. SL → 160.
        # Low=156 ≤ 160 → SL_HIT on second leg @ 160.
        _candle(10, 15, 159, 160, 156, 156),
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(
        df, ENTRY, SL, TP1, TP2,
        _cfg_method3(_trail(n=3, activate=15, update=15)),
        ALERT_TS,
    )
    assert res is not None
    assert res.auto_order_status == PARTIAL
    assert res.auto_exit_price == pytest.approx(160.0)
    # Method 3 must NOT call this "breakeven" — under the trail, the SL
    # is whatever the SMA last produced.
    assert "trailed SL" in res.auto_exit_reason


def test_method3_early_entry_fallback_holds_method1_sl_until_n_candles() -> None:
    """If fewer than N candles exist when the trail would activate, the
    Method-1 SL must be held. We seed only 3 prior candles and require
    N=10 — the SMA cannot be computed and the SL stays at 140."""
    rows = [
        _candle(9, 50, 148, 152, 148, 150),
        _candle(9, 55, 148, 152, 148, 150),
        _candle(10, 0, 150, 152, 149, 150),  # alert candle
        _candle(10, 5, 150, 152, 149, 151),
        _candle(10, 10, 151, 153, 150, 152),
        # 10:15 TICK with n=10. Available closes = ~5 < 10 → fallback.
        # SL stays at 140. Low=138 ≤ 140 → SL_HIT @ 140.
        _candle(10, 15, 152, 154, 138, 142),
    ]
    df = pd.DataFrame(rows)
    res = replay_exits(
        df, ENTRY, SL, TP1, TP2,
        _cfg_method3(_trail(n=10, activate=15, update=15)),
        ALERT_TS,
    )
    assert res is not None
    assert res.auto_order_status == SL_HIT
    assert res.auto_exit_price == pytest.approx(SL)


# ---------------------------------------------------------------------------
# replay_alert adapter — Method 3 wiring through AppConfig stubs
# ---------------------------------------------------------------------------


class _StubRiskReward:
    def __init__(self, *, move_be: bool, trail: bool):
        self.move_sl_to_breakeven_after_tp1 = move_be
        self.trail_sl_after_tp1 = trail


class _StubSmaTrail:
    def __init__(self, *, n: int, activate: int, update: int, direction: str):
        self.sma_period = n
        self.activate_after_minutes = activate
        self.update_interval_minutes = update
        self.follow_direction = direction


class _StubStopLoss:
    def __init__(self, *, method: int, sma_trail: _StubSmaTrail | None, hard_exit: bool = True):
        self.method = method
        self.sma_trail = sma_trail
        self.hard_exit_red_candle_below_vwap = hard_exit


class _StubTimeRules:
    hard_squareoff_time = "15:00"


class _StubConfig:
    def __init__(
        self,
        *,
        method: int = 1,
        sma_trail: _StubSmaTrail | None = None,
        trail_flag: bool = False,
    ):
        self.risk_reward = _StubRiskReward(move_be=True, trail=trail_flag)
        self.stop_loss = _StubStopLoss(method=method, sma_trail=sma_trail)
        self.time_rules = _StubTimeRules()


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


def test_replay_alert_method3_wiring_produces_real_outcome() -> None:
    """Confirm that ``stop_loss.method == 3`` plus an ``sma_trail`` stub
    flows through ``replay_alert`` and produces a real outcome — the
    previously-refused trail_sl_after_tp1 path now succeeds."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 176, 160, 174),
    ]
    df = pd.DataFrame(rows)
    cfg = _StubConfig(
        method=3,
        sma_trail=_StubSmaTrail(n=19, activate=15, update=15, direction="both"),
        trail_flag=True,
    )
    res = replay_alert(_alert_row(), df, cfg)
    assert res is not None
    assert res.auto_order_status == TP2_HIT


def test_kernel_no_longer_refuses_on_trail_sl_after_tp1_method1() -> None:
    """Even under Method 1, trail_sl_after_tp1: ON must not refuse —
    the legacy refusal rule is removed."""
    rows = _session_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 168, 149, 160),  # back to breakeven
    ]
    df = pd.DataFrame(rows)
    cfg = _StubConfig(method=1, sma_trail=None, trail_flag=True)
    res = replay_alert(_alert_row(), df, cfg)
    assert res is not None
    # Under Method 1, behavior matches breakeven-after-TP1 → PARTIAL.
    assert res.auto_order_status == PARTIAL
