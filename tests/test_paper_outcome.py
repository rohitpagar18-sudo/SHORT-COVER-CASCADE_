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
    # Normal day → 2.5R inherited from risk_reward (paper override is None).
    assert po.realized_R == pytest.approx(config.risk_reward.normal_day_tp2_r)


def test_tp1_be_outcome_mapping(base_alert, config):
    # Pin Method 1 — this test asserts the breakeven-after-TP1 path,
    # which is Method 1/2 only. Under Method 3 the SMA trail owns SL.
    cfg = config.model_copy(
        update={"stop_loss": config.stop_loss.model_copy(update={"method": 1})}
    )
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),    # TP1
        _candle(10, 10, 165, 168, 149, 160),   # back to breakeven
    ])
    po = compute_paper_outcome(base_alert, candles=candles, app_config=cfg)
    kernel = replay_alert(base_alert, candles, cfg)
    assert kernel.auto_order_status == PARTIAL
    assert po.outcome == OUTCOME_TP1_BE
    # PARTIAL R = tp1_fraction × tp1_r. 3-lot ceil split = (2, 1) →
    # tp1_fraction = 2/3, normal_day_tp1_r = 1.5 → 1.0R.
    assert po.realized_R == pytest.approx(
        (2 / 3) * cfg.risk_reward.normal_day_tp1_r
    )


def test_tp1_be_outcome_stores_both_leg_exit_prices(base_alert, config):
    """TP1_BE must expose leg1=tp1, leg2=second-leg exit, and the
    surfaced ``exit_price`` becomes the lot-weighted average of the
    two legs (the bug fix). The Phase 5B-A kernel's
    ``auto_exit_price`` is still the raw second-leg price; that field
    is the kernel's contract and is exposed separately for
    diagnostics."""
    cfg = config.model_copy(
        update={"stop_loss": config.stop_loss.model_copy(update={"method": 1})}
    )
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),    # TP1 banked at 165
        _candle(10, 10, 165, 168, 138, 142),   # second leg hits breakeven SL
    ])
    po = compute_paper_outcome(base_alert, candles=candles, app_config=cfg)
    assert po.outcome == OUTCOME_TP1_BE
    # leg1 == the alert's tp1; leg2 == kernel's second-leg exit
    # (=breakeven entry under Method 1).
    assert po.exit_price_leg1 == pytest.approx(165.0)
    assert po.exit_price_leg2 == pytest.approx(150.0)
    # 3-lot ceil split = (2, 1) → surfaced exit_price is the
    # lot-weighted average (2 lots at 165 + 1 lot at 150) / 3.
    assert po.exit_price == pytest.approx(
        (2 * 165.0 + 1 * 150.0) / 3.0
    )


def test_sl_hit_outcome_leg_prices_are_none(base_alert, config):
    """Single-leg outcomes must NOT populate the split-leg fields."""
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 152, 138, 142),  # low crosses SL
    ])
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    assert po.outcome == OUTCOME_SL
    assert po.exit_price_leg1 is None
    assert po.exit_price_leg2 is None
    # exit_price for single-leg outcomes is unchanged — it remains
    # the kernel's auto_exit_price (the SL hit value).
    assert po.exit_price == pytest.approx(140.0)


def test_eod_flat_is_open_sqoff(base_alert, config):
    # Pin Method 1 — the static-SL hover-band test. Under Method 3 the
    # SMA trail walks SL up into the hover band and fires SL_HIT.
    cfg = config.model_copy(
        update={"stop_loss": config.stop_loss.model_copy(update={"method": 1})}
    )
    # Hover band — never touches SL or TP1.
    rows = _prefix()
    for hh in range(10, 15):
        for mm in (5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
            if hh == 10 and mm < 5:
                continue
            rows.append(_candle(hh, mm, 152, 158, 148, 153))
    candles = pd.DataFrame(rows)
    po = compute_paper_outcome(base_alert, candles=candles, app_config=cfg)
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


def test_paper_engine_uses_stop_loss_method_from_config(base_alert, config):
    """The paper engine must respect ``stop_loss.method`` — flipping the
    live config to Method 3 changes the kernel's exit behavior, and the
    paper outcome reflects that change. We do not mock the engine; we
    flip ``config.stop_loss.method`` and verify the kernel route used."""
    # Build a candle frame where Method 1 produces SL_HIT (low<140) but
    # Method 3 with a high SMA-trail would have an even higher SL.
    rows = _prefix() + [
        _candle(10, 5, 150, 152, 149, 151),
        _candle(10, 10, 151, 153, 150, 152),
        # 10:15 with n=3 → SMA on last 3 = (150,151,152)/3 = 151.
        # Under Method 3 (both), SL → 151. low=152 > 151 → safe.
        _candle(10, 15, 151, 153, 152, 152),
        # 10:20: low=141.5 > 140 (Method-1 SL) but < 151 (Method-3 SL).
        # → Method 1 path: survives this candle.
        # → Method 3 path: SL_HIT @ 151.
        _candle(10, 20, 152, 152, 141.5, 142),
    ]
    candles = pd.DataFrame(rows)

    cfg1 = config.model_copy(
        update={"stop_loss": config.stop_loss.model_copy(update={"method": 1})}
    )
    cfg3 = config.model_copy(
        update={
            "stop_loss": config.stop_loss.model_copy(
                update={
                    "method": 3,
                    "sma_trail": config.stop_loss.sma_trail.model_copy(
                        update={
                            "sma_period": 3,
                            "activate_after_minutes": 15,
                            "update_interval_minutes": 15,
                            "follow_direction": "both",
                        }
                    ),
                }
            )
        }
    )

    po1 = compute_paper_outcome(base_alert, candles=candles, app_config=cfg1)
    po3 = compute_paper_outcome(base_alert, candles=candles, app_config=cfg3)

    # Method 1: SL untouched (low=141.5 > 140) — outcome should not be SL.
    assert po1.outcome != OUTCOME_SL
    # Method 3 with n=3: SMA of [151, 152, 152] at 10:15 ≈ 151.67. The
    # 10:20 dip to 141.5 sits below that trailed SL → SL outcome,
    # exit price equal to the trailed SL value.
    assert po3.outcome == OUTCOME_SL
    assert po3.exit_price == pytest.approx((151 + 152 + 152) / 3.0)


def test_paper_engine_reads_tp_multipliers_from_risk_reward(
    base_alert, config
):
    """The paper engine reads TP1/TP2 multipliers directly from
    ``risk_reward`` — the single source of truth. A change to
    ``risk_reward.normal_day_tp2_r`` must show up in ``realized_R``."""
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 176, 160, 174),
    ])
    po_default = compute_paper_outcome(
        base_alert, candles=candles, app_config=config
    )
    assert po_default.outcome == OUTCOME_TP2
    assert po_default.realized_R == pytest.approx(
        config.risk_reward.normal_day_tp2_r
    )

    bumped = config.model_copy(
        update={
            "risk_reward": config.risk_reward.model_copy(
                update={"normal_day_tp2_r": 3.7}
            )
        }
    )
    po_bumped = compute_paper_outcome(
        base_alert, candles=candles, app_config=bumped
    )
    assert po_bumped.outcome == OUTCOME_TP2
    assert po_bumped.realized_R == pytest.approx(3.7)


def test_paper_trading_block_has_no_r_override_fields(config):
    """The paper_trading block carries only episode/cap/path knobs —
    no paper-only R-multiplier overrides, no sl_R, no selection_mode."""
    pt_cls = type(config.paper_trading)
    forbidden = {
        "tp1_R_normal", "tp2_R_normal", "tp1_R_expiry", "tp2_R_expiry",
        "tp1_then_be_R_normal", "tp1_then_be_R_expiry",
        "sl_R", "selection_mode",
    }
    present = set(pt_cls.model_fields.keys())
    assert forbidden.isdisjoint(present), (
        f"paper_trading still carries forbidden fields: "
        f"{sorted(forbidden & present)}"
    )


def test_single_lot_tp1hit_full_exit(base_alert, config):
    """lots=1 cannot split — the kernel itself closes the full position at TP1,
    so a candle where both TP1 and TP2 touch still resolves to TP1_HIT."""
    base_alert["lots"] = 1
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 176, 160, 174),
    ])
    kernel = replay_alert(base_alert, candles, config)
    # Kernel is now lot-aware: lots=1 → full exit at TP1 → TP1_HIT.
    assert kernel.auto_order_status == TP1_HIT
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    assert po.outcome == OUTCOME_TP1_HIT
    assert po.exit_price == pytest.approx(base_alert["tp1"])
    expected_pnl = (base_alert["tp1"] - base_alert["entry"]) * config.instruments.nifty_lot_size
    assert po.paper_pnl == pytest.approx(expected_pnl)
    assert po.exit_price_leg1 is None
    assert po.exit_price_leg2 is None


def test_single_lot_tp1_then_drop_full_exit(base_alert, config):
    """lots=1 + later breakeven drop → kernel still exits the full lot at TP1.
    No second leg can hit breakeven because there is no second leg."""
    cfg = config.model_copy(
        update={"stop_loss": config.stop_loss.model_copy(update={"method": 1})}
    )
    base_alert["lots"] = 1
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),    # TP1 — single lot exits here
        _candle(10, 10, 165, 168, 138, 142),   # would have hit breakeven SL
    ])
    kernel = replay_alert(base_alert, candles, cfg)
    assert kernel.auto_order_status == TP1_HIT
    po = compute_paper_outcome(base_alert, candles=candles, app_config=cfg)
    assert po.outcome == OUTCOME_TP1_HIT
    assert po.exit_price == pytest.approx(base_alert["tp1"])
    expected_pnl = (base_alert["tp1"] - base_alert["entry"]) * cfg.instruments.nifty_lot_size
    assert po.paper_pnl == pytest.approx(expected_pnl)
    assert po.exit_price_leg1 is None
    assert po.exit_price_leg2 is None


def test_two_lot_tp2hit_splits_correctly(base_alert, config):
    """lots==2 → 1 lot at TP1, 1 lot at TP2 — clean 50/50 split."""
    base_alert["lots"] = 2
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 166, 149, 165),
        _candle(10, 10, 165, 176, 160, 174),
    ])
    kernel = replay_alert(base_alert, candles, config)
    assert kernel.auto_order_status == TP2_HIT
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    assert po.outcome == OUTCOME_TP2
    lot_size = config.instruments.nifty_lot_size
    tp1_leg = (base_alert["tp1"] - base_alert["entry"]) * 1 * lot_size
    tp2_leg = (kernel.auto_exit_price - base_alert["entry"]) * 1 * lot_size
    assert po.paper_pnl == pytest.approx(tp1_leg + tp2_leg)


def test_sl_hit_single_lot_unaffected(base_alert, config):
    """1 lot + kernel SL_HIT: outcome unchanged — no override applies."""
    base_alert["lots"] = 1
    candles = pd.DataFrame(_prefix() + [
        _candle(10, 5, 150, 152, 138, 142),  # low crosses SL
    ])
    kernel = replay_alert(base_alert, candles, config)
    assert kernel.auto_order_status == SL_HIT
    po = compute_paper_outcome(base_alert, candles=candles, app_config=config)
    assert po.outcome == OUTCOME_SL
    expected_pnl = kernel.auto_pnl_per_unit * 1 * config.instruments.nifty_lot_size
    assert po.paper_pnl == pytest.approx(expected_pnl)


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
