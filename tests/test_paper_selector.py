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


def _outcome(label: str, *, exit_time: datetime | None = None) -> dict:
    """Helper: build the dict the selector's outcome_resolver expects.

    Default ``exit_time=None`` would activate the position-open gate.
    The cap-focused tests below pass an explicit ``exit_time`` equal
    to (or earlier than) the entry candle so the gate is a no-op
    for tests that only care about cap behaviour.
    """
    return {"outcome": label, "exit_time": exit_time}


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
        # Pretend each TP2 trade closes instantly so the open-position
        # gate doesn't pre-empt the daily-cap behaviour under test.
        outcome_resolver=lambda r: _outcome("TP2_HIT", exit_time=r["candle_ts"]),
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
        outcome_resolver=lambda r: (
            _outcome("SL_HIT", exit_time=r["candle_ts"])
            if r["alert_id"] == "a1"
            else _outcome("TP2_HIT", exit_time=r["candle_ts"])
        ),
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
        outcome_resolver=lambda r: _outcome("SL_HIT", exit_time=r["candle_ts"]),
    )
    assert [r.decision for r in results] == [
        DECISION_TAKEN, DECISION_TAKEN, DECISION_SKIPPED,
    ]
    assert "circuit breaker" in results[2].decision_reason


def test_same_strike_killed_after_two_sl_on_same_strike():
    # Two SLs on strike 24050, then a third alert on the same strike.
    # Each trade's exit_time equals its own candle_ts so the
    # open-position gate (keyed by symbol+option_type) clears between
    # trades — leaving the same-strike rule as the active gate
    # under test.
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
        outcome_resolver=lambda r: _outcome("SL_HIT", exit_time=r["candle_ts"]),
    )
    decisions = [r.decision for r in results]
    assert decisions[0] == DECISION_TAKEN
    assert decisions[1] == DECISION_TAKEN
    assert decisions[2] == DECISION_SKIPPED
    assert "same-strike killed" in results[2].decision_reason
    assert decisions[3] == DECISION_TAKEN  # different strike, still OK


def test_unknown_outcome_does_not_count_as_sl():
    """Resolver returns None → caps treat as non-SL (best effort).

    Resolver returning None also means the position-open gate is
    not tracked (legacy semantics), so the second alert is free to
    fire.
    """
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


# ---------------------------------------------------------------------------
# Gate 0: paper_order_strikes relation filter
# ---------------------------------------------------------------------------


def test_paper_order_strike_atm_only_skips_itm1_rep():
    """With ATM-only bucket, an ITM1 rep is SKIPPED before §13/§14 run."""
    from src.config_loader import PaperOrderStrikesConfig

    pos = PaperOrderStrikesConfig(itm=False, atm=True, otm=False)
    reps = _df([_rep(aid="a1", hh=10, mm=0, relation="ITM1")])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=2,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: _outcome("TP2_HIT", exit_time=r["candle_ts"]),
        relation_filter=pos.allows_relation,
    )
    assert results[0].decision == DECISION_SKIPPED
    assert "paper_order_strike not enabled" in results[0].decision_reason
    assert "ITM1" in results[0].decision_reason
    assert "paper_order_strike_disabled" in results[0].triggered_caps


def test_paper_order_strike_atm_only_allows_atm_rep():
    from src.config_loader import PaperOrderStrikesConfig

    pos = PaperOrderStrikesConfig(itm=False, atm=True, otm=False)
    reps = _df([_rep(aid="a1", hh=10, mm=0, relation="ATM")])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=2,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: _outcome("TP2_HIT", exit_time=r["candle_ts"]),
        relation_filter=pos.allows_relation,
    )
    assert results[0].decision == DECISION_TAKEN


def test_paper_order_strike_itm_on_allows_itm2_rep():
    from src.config_loader import PaperOrderStrikesConfig

    pos = PaperOrderStrikesConfig(itm=True, atm=False, otm=False)
    reps = _df([_rep(aid="a1", hh=10, mm=0, relation="ITM2")])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=2,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: _outcome("TP2_HIT", exit_time=r["candle_ts"]),
        relation_filter=pos.allows_relation,
    )
    assert results[0].decision == DECISION_TAKEN


def test_paper_order_strike_blocks_disabled_then_taken_does_not_consume_slot():
    """A disabled-bucket SKIPPED rep must NOT eat into the daily cap."""
    from src.config_loader import PaperOrderStrikesConfig

    pos = PaperOrderStrikesConfig(itm=False, atm=True, otm=False)
    reps = _df([
        _rep(aid="a1", hh=10, mm=0, relation="ITM1"),   # blocked by gate 0
        _rep(aid="a2", hh=10, mm=30, relation="ATM"),   # slot 1
        _rep(aid="a3", hh=11, mm=0, relation="ATM"),    # slot 2 — proves a1
                                                        # did not consume.
    ])
    results = select_paper_trades(
        reps,
        max_trades_per_day=2,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: _outcome("TP2_HIT", exit_time=r["candle_ts"]),
        relation_filter=pos.allows_relation,
    )
    assert [r.decision for r in results] == [
        DECISION_SKIPPED, DECISION_TAKEN, DECISION_TAKEN,
    ]
    assert results[1].slot == 1
    assert results[2].slot == 2


def test_paper_order_strike_all_off_raises_validation_error():
    """Validator must reject a config where every bucket is OFF."""
    from pydantic import ValidationError

    from src.config_loader import PaperOrderStrikesConfig

    with pytest.raises(ValidationError):
        PaperOrderStrikesConfig(itm=False, atm=False, otm=False)


def test_paper_order_strike_unknown_relation_is_allowed():
    """Unknown/missing relation labels fail-safe (allow through to caps)."""
    from src.config_loader import PaperOrderStrikesConfig

    pos = PaperOrderStrikesConfig(itm=False, atm=True, otm=False)
    assert pos.allows_relation(None) is True
    assert pos.allows_relation("") is True
    assert pos.allows_relation("weird") is True
    assert pos.allows_relation("atm") is True   # case-insensitive
    assert pos.allows_relation("itm3") is False
    assert pos.allows_relation("otm1") is False


# ---------------------------------------------------------------------------
# Open-position gate
# ---------------------------------------------------------------------------


def test_open_position_blocks_new_take_outside_dedup_window():
    """Two reps for (NIFTY, PE), 25 min apart on the same day.

    First rep's TP1_BE exits at 13:30; second rep fires at 13:10, so
    the prior position is still live → SKIPPED with the open-position
    reason. Mirrors the 19-Jun 2026 production bug.
    """
    rep_a = _rep(aid="a1", hh=12, mm=45, option_type="PE", strike=24000)
    rep_b = _rep(aid="a2", hh=13, mm=10, option_type="PE", strike=24000)
    reps = _df([rep_a, rep_b])
    exit_dt = datetime(2026, 5, 27, 13, 30, tzinfo=IST)
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: _outcome("TP1_BE", exit_time=exit_dt),
    )
    assert [r.decision for r in results] == [DECISION_TAKEN, DECISION_SKIPPED]
    assert "prior episode still open" in results[1].decision_reason
    assert "prior_episode_open" in results[1].triggered_caps


def test_open_position_blocks_same_key_different_strike():
    """The position-open gate is keyed by (symbol, option_type) only.

    A prior PE position on strike 24000 must block a new PE alert on
    a different strike (24050) on the same day — exactly the wider
    same-direction protection the gate is for.
    """
    reps = _df([
        _rep(aid="a1", hh=10, mm=0, option_type="PE", strike=24000),
        _rep(aid="a2", hh=10, mm=30, option_type="PE", strike=24050),
    ])
    exit_dt = datetime(2026, 5, 27, 11, 0, tzinfo=IST)
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: _outcome("TP1_BE", exit_time=exit_dt),
    )
    assert [r.decision for r in results] == [DECISION_TAKEN, DECISION_SKIPPED]
    assert "prior episode still open" in results[1].decision_reason


def test_open_position_does_not_block_different_option_type():
    """A live PE position must NOT block a CE alert (different direction)."""
    reps = _df([
        _rep(aid="a1", hh=10, mm=0, option_type="PE", strike=24000),
        _rep(aid="a2", hh=10, mm=30, option_type="CE", strike=24000),
    ])
    exit_dt = datetime(2026, 5, 27, 11, 0, tzinfo=IST)
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=True,
        outcome_resolver=lambda r: _outcome("TP1_BE", exit_time=exit_dt),
    )
    assert [r.decision for r in results] == [DECISION_TAKEN, DECISION_TAKEN]


def test_closed_position_allows_new_take_after_exit():
    """First rep's SL_HIT exits at 13:05; second rep at 13:25 is allowed.

    20-minute cooldown elapses by 13:25 too, so neither gate blocks.
    """
    reps = _df([
        _rep(aid="a1", hh=12, mm=45, option_type="PE", strike=24000),
        _rep(aid="a2", hh=13, mm=25, option_type="PE", strike=24000),
    ])
    exit_dt = datetime(2026, 5, 27, 13, 5, tzinfo=IST)
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=False,  # isolate the open-position gate
        outcome_resolver=lambda r: _outcome("SL_HIT", exit_time=exit_dt),
    )
    assert [r.decision for r in results] == [DECISION_TAKEN, DECISION_TAKEN]


def test_no_data_outcome_blocks_new_take():
    """``outcome_resolver`` returns {"exit_time": None} → position open.

    NO_DATA means we cannot prove the prior position closed, so any
    subsequent same-key alert is conservatively blocked for the day.
    """
    reps = _df([
        _rep(aid="a1", hh=10, mm=0, option_type="PE", strike=24000),
        _rep(aid="a2", hh=14, mm=0, option_type="PE", strike=24000),
    ])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=False,
        outcome_resolver=lambda r: _outcome("NO_DATA", exit_time=None),
    )
    assert [r.decision for r in results] == [DECISION_TAKEN, DECISION_SKIPPED]
    assert "prior episode still open" in results[1].decision_reason


def test_open_position_does_not_carry_across_days():
    """Cross-day cleanliness — yesterday's open position does not block today."""
    rep_a = _rep(aid="a1", hh=14, mm=45, option_type="PE", strike=24000)
    rep_b = _rep(aid="a2", hh=10, mm=0, option_type="PE", strike=24000)
    # Override day for rep_b — next calendar day.
    rep_b["candle_ts"] = datetime(2026, 5, 28, 10, 0, tzinfo=IST)
    reps = _df([rep_a, rep_b])
    results = select_paper_trades(
        reps,
        max_trades_per_day=10,
        circuit_breaker_sl_count=99,
        cooldown_minutes_after_sl=15,
        same_strike_kill_after_2_sl=False,
        # First trade ended with NO_DATA (exit_time None) — under the
        # cross-day rule this must NOT bleed into tomorrow.
        outcome_resolver=lambda r: _outcome("NO_DATA", exit_time=None),
    )
    assert [r.decision for r in results] == [DECISION_TAKEN, DECISION_TAKEN]
