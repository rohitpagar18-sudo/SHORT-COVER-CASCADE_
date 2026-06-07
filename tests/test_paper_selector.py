"""Phase 5D — selection-gate tests.

Caps replayed in chronological order over episode representatives.
Outcomes are injected via a stub ``outcome_resolver`` so each test
controls SL / non-SL behavior deterministically.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.paper.selector import (
    DECISION_SKIPPED,
    DECISION_TAKEN,
    select_paper_trades,
)

IST = ZoneInfo("Asia/Kolkata")


def _rep(
    *,
    aid: str,
    hh: int, mm: int,
    symbol: str = "NIFTY",
    option_type: str = "CE",
    strike: int = 24050,
    relation: str = "ATM",
) -> dict:
    ts = datetime(2026, 5, 27, hh, mm, tzinfo=IST)
    return {
        "alert_id": aid,
        "candle_ts": ts,
        "symbol": symbol,
        "option_type": option_type,
        "strike": strike,
        "relation": relation,
        "bot_remark": "",
        "bot_tags": "",
    }


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_daily_cap_skips_after_three_taken():
    times = [(10, 0), (10, 30), (11, 0), (11, 30), (12, 0)]
    reps = _df([
        _rep(aid=f"a{i}", hh=hh, mm=mm) for i, (hh, mm) in enumerate(times)
    ])
    results = select_paper_trades(
        reps,
        max_trades_per_day=3,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: "TP2_HIT",
    )
    decisions = [r.decision for r in results]
    assert decisions == [
        DECISION_TAKEN, DECISION_TAKEN, DECISION_TAKEN,
        DECISION_SKIPPED, DECISION_SKIPPED,
    ]
    assert "daily cap" in results[3].decision_reason


def test_cooldown_after_sl_skips_inside_window():
    reps = _df([
        _rep(aid="a1", hh=10, mm=0),
        _rep(aid="a2", hh=10, mm=10),  # 10 min after first → cooldown
        _rep(aid="a3", hh=10, mm=20),  # 20 min after first → OK
    ])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: "SL_HIT" if r["alert_id"] == "a1" else "TP2_HIT",
    )
    assert [r.decision for r in results] == [
        DECISION_TAKEN, DECISION_SKIPPED, DECISION_TAKEN,
    ]
    assert "cooldown" in results[1].decision_reason


def test_circuit_breaker_after_two_sl():
    reps = _df([
        _rep(aid="a1", hh=10, mm=0),
        _rep(aid="a2", hh=11, mm=0),  # past cooldown
        _rep(aid="a3", hh=12, mm=0),  # should be blocked by circuit breaker
    ])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=2,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=False,  # isolate breaker logic
        outcome_resolver=lambda r: "SL_HIT",
    )
    assert [r.decision for r in results] == [
        DECISION_TAKEN, DECISION_TAKEN, DECISION_SKIPPED,
    ]
    assert "circuit breaker" in results[2].decision_reason


def test_same_strike_killed_after_two_sl_on_same_strike():
    # Two SLs on strike 24050, then a third alert on the same strike.
    reps = _df([
        _rep(aid="a1", hh=10, mm=0, strike=24050),
        _rep(aid="a2", hh=11, mm=0, strike=24050),
        _rep(aid="a3", hh=12, mm=0, strike=24050),
        _rep(aid="a4", hh=12, mm=30, strike=24100),  # different strike — OK
    ])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        # Set breaker > 2 so the same-strike rule fires first.
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: "SL_HIT",
    )
    decisions = [r.decision for r in results]
    assert decisions[0] == DECISION_TAKEN
    assert decisions[1] == DECISION_TAKEN
    assert decisions[2] == DECISION_SKIPPED
    assert "same-strike killed" in results[2].decision_reason
    assert decisions[3] == DECISION_TAKEN  # different strike, still OK


def test_unknown_outcome_does_not_count_as_sl():
    """Resolver returns None → caps treat as non-SL (best effort)."""
    reps = _df([
        _rep(aid="a1", hh=10, mm=0),
        _rep(aid="a2", hh=10, mm=5),  # inside cooldown only if a1 was SL
    ])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=2,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: None,
    )
    # Because a1's outcome is unknown, no cooldown fires; a2 is taken.
    assert [r.decision for r in results] == [
        DECISION_TAKEN, DECISION_TAKEN,
    ]
