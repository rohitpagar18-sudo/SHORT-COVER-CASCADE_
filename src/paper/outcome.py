"""Phase 5D — Paper-outcome engine (D3).

REUSES the Phase 5B-A exit kernel (``src.dashboard.outcome_replay``).
There is intentionally **no second candle walk in this module** —
every candle-level decision (SL touch, TP touch, intrabar ambiguity,
hard-exit-below-VWAP, EOD force-close) is delegated to that kernel.
This module only computes the extra paper-side numbers the kernel
does not emit: ``realized_R``, ``paper_pnl``, ``mfe_R``, ``mae_R``,
``max_drawdown_R``, plus the ``fidelity`` flag.

When Phase 8 (live orders) lands, the broker callback replaces the
kernel call; the R / paper_pnl mapping below stays useful as a
post-trade analytic.

Key design points:
  - ``compute_paper_outcome`` accepts pre-loaded candles or asks the
    caller's ``candle_source`` callable to fetch them. It never
    touches a feed directly; the backfill / dashboard layers own
    that I/O.
  - ``fidelity == "ohlc"`` when full OHLC is available (kernel walk
    runs as designed). ``fidelity == "close_only"`` when the cache
    has close-only legacy rows — in that case we still call the
    kernel but flag the result so the user knows MFE/MAE are
    coarse-grained.
  - ``trail_sl_after_tp1: ON`` is forwarded to the kernel which
    refuses to stamp (same loud-warning path as 5B-A). We never
    silently model trailing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls
from typing import Any, Callable

import pandas as pd
from loguru import logger

# Reuse the kernel — DO NOT write a second candle walk here.
from src.dashboard.outcome_replay import (
    EOD_FLAT,
    HARD_EXIT,
    PARTIAL,
    SL_HIT,
    TP1_HIT,
    TP2_HIT,
    ReplayResult,
    replay_alert,
)


# ---------------------------------------------------------------------------
# Paper outcome labels (mirrors kernel + adds OPEN_SQOFF / NO_DATA)
# ---------------------------------------------------------------------------

OUTCOME_TP2 = "TP2_HIT"
OUTCOME_TP1_BE = "TP1_BE"           # TP1 banked, second leg breakeven/SL
OUTCOME_TP1_HIT = "TP1_HIT"         # TP1 banked, second leg EOD-flat
OUTCOME_SL = "SL_HIT"
OUTCOME_HARD_EXIT = "HARD_EXIT"
OUTCOME_OPEN_SQOFF = "OPEN_SQOFF"   # nothing hit by 15:00 — kernel's EOD close
OUTCOME_NO_DATA = "NO_DATA"

PAPER_OUTCOME_VALUES = {
    OUTCOME_TP2, OUTCOME_TP1_BE, OUTCOME_TP1_HIT,
    OUTCOME_SL, OUTCOME_HARD_EXIT, OUTCOME_OPEN_SQOFF,
    OUTCOME_NO_DATA,
}


def _map_kernel_to_paper(kernel_status: str) -> str:
    """Translate the kernel's status into a paper outcome label."""
    s = (kernel_status or "").upper()
    if s == TP2_HIT:
        return OUTCOME_TP2
    if s == PARTIAL:
        return OUTCOME_TP1_BE
    if s == TP1_HIT:
        return OUTCOME_TP1_HIT
    if s == SL_HIT:
        return OUTCOME_SL
    if s == HARD_EXIT:
        return OUTCOME_HARD_EXIT
    if s == EOD_FLAT:
        return OUTCOME_OPEN_SQOFF
    return s  # unknown — preserve verbatim


# ---------------------------------------------------------------------------
# R-multiple mapping (§9)
# ---------------------------------------------------------------------------


def _r_multiple(
    paper_outcome: str,
    pnl_per_unit: float,
    risk_per_unit: float,
    is_expiry_day: bool,
    *,
    tp1_R_normal: float,
    tp2_R_normal: float,
    tp1_R_expiry: float,
    tp2_R_expiry: float,
    tp1_then_be_R_normal: float,
    tp1_then_be_R_expiry: float,
    sl_R: float,
) -> float:
    """Map the kernel's outcome onto §9's R ladder.

    The kernel already returns the exact ₹/unit P&L. We could just do
    ``pnl_per_unit / R`` for every case — and that is the fallback —
    but for the discrete TP1/TP2/SL labels we return the strategy
    doc's canonical R values directly so the dashboard reads cleanly
    (1.5R / 2.5R, expiry 2.0R / 3.0R) instead of e.g. 1.4938R from
    floating-point drift.
    """
    if paper_outcome == OUTCOME_SL or paper_outcome == OUTCOME_HARD_EXIT:
        return float(sl_R)
    if paper_outcome == OUTCOME_TP2:
        return float(tp2_R_expiry if is_expiry_day else tp2_R_normal)
    if paper_outcome == OUTCOME_TP1_BE:
        return float(tp1_then_be_R_expiry if is_expiry_day else tp1_then_be_R_normal)
    if paper_outcome == OUTCOME_TP1_HIT:
        # TP1 banked + second leg EOD-flat at ≥SL. Use the per-unit P&L
        # the kernel computed — captures the actual close, not a label.
        if risk_per_unit and risk_per_unit > 0:
            return float(pnl_per_unit) / float(risk_per_unit)
        return float(tp1_R_expiry if is_expiry_day else tp1_R_normal) * 0.5
    if paper_outcome == OUTCOME_OPEN_SQOFF:
        if risk_per_unit and risk_per_unit > 0:
            return float(pnl_per_unit) / float(risk_per_unit)
        return 0.0
    return 0.0


# ---------------------------------------------------------------------------
# Lot-size lookup (config-driven, never hardcoded)
# ---------------------------------------------------------------------------


def _lot_size_for_symbol(symbol: str, app_config: Any) -> int:
    """Read NIFTY 65 / BankNifty 30 from config — never hardcode."""
    sym = (symbol or "").upper()
    instr = getattr(app_config, "instruments", None)
    if instr is None:
        return 0
    if sym == "NIFTY":
        return int(getattr(instr, "nifty_lot_size", 0))
    if sym in ("BANKNIFTY", "BANK_NIFTY", "BANK-NIFTY"):
        return int(getattr(instr, "banknifty_lot_size", 0))
    return 0


# ---------------------------------------------------------------------------
# Fidelity detector
# ---------------------------------------------------------------------------


def _detect_fidelity(candles: pd.DataFrame | None) -> str:
    """Return ``"ohlc"`` when full OHLC is present, else ``"close_only"``."""
    if candles is None or candles.empty:
        return "close_only"
    needed = {"open", "high", "low", "close"}
    if not needed.issubset(candles.columns):
        return "close_only"
    # If H/L/O are systematically equal to close, treat as close-only.
    sample = candles[["open", "high", "low", "close"]].head(10)
    same_high = (sample["high"] == sample["close"]).all()
    same_low = (sample["low"] == sample["close"]).all()
    same_open = (sample["open"] == sample["close"]).all()
    if same_high and same_low and same_open:
        return "close_only"
    return "ohlc"


# ---------------------------------------------------------------------------
# PaperOutcome dataclass + main entry point
# ---------------------------------------------------------------------------


@dataclass
class PaperOutcome:
    """Outcome record for one paper trade (one episode representative)."""

    alert_id: str
    outcome: str                  # OUTCOME_* constant
    exit_price: float | None
    exit_time: str | None
    exit_reason: str
    realized_R: float
    paper_pnl: float              # ₹ across lots
    paper_pnl_per_unit: float
    mfe: float
    mae: float
    mfe_R: float
    mae_R: float
    max_drawdown_R: float         # alias of -mae_R (worst-case R drawdown)
    intrabar_ambiguous: bool
    fidelity: str                 # "ohlc" | "close_only"
    is_expiry_day: bool
    lots: int
    lot_size: int


def compute_paper_outcome(
    rep_row: dict[str, Any] | pd.Series,
    *,
    candles: pd.DataFrame | None,
    app_config: Any,
    is_expiry_day: bool | None = None,
) -> PaperOutcome:
    """Run the 5B-A kernel on one representative alert + compute R / ₹ side.

    Args:
        rep_row: episode-representative row from ``alerts.jsonl`` plus
            the ``alert_id`` derived by ``episodes.derive_alert_id``.
            Must include ``timestamp_ist``, ``entry``, ``sl``, ``tp1``,
            ``tp2``, ``symbol``, ``strike``, ``option_type``,
            ``expiry``, ``lots``.
        candles: pre-loaded 5-min option candles for the alert's
            trading day (e.g. from ``replay_cache``). ``None`` → the
            outcome is recorded as ``NO_DATA`` and no kernel call is
            attempted.
        app_config: live ``AppConfig`` — passed straight through to
            the kernel for the exit knobs (trail_sl, breakeven, hard
            exit, hard square-off time).
        is_expiry_day: whether the alert's trading day was expiry. If
            ``None`` it is best-effort inferred from ``day_type ==
            "Expiry"``.

    Returns:
        ``PaperOutcome`` — never raises on missing data; missing/empty
        candles yield ``OUTCOME_NO_DATA``. A kernel refusal (trail-SL
        ON) also surfaces as ``OUTCOME_NO_DATA`` with a clear reason.
    """
    alert_id = str(rep_row.get("alert_id", "<unknown>"))
    lots = int(rep_row.get("lots") or 0)
    symbol = str(rep_row.get("symbol") or "")
    lot_size = _lot_size_for_symbol(symbol, app_config)

    if is_expiry_day is None:
        is_expiry_day = (
            str(rep_row.get("day_type") or "").strip().lower() == "expiry"
        )

    fidelity = _detect_fidelity(candles)

    if candles is None or candles.empty:
        return PaperOutcome(
            alert_id=alert_id,
            outcome=OUTCOME_NO_DATA,
            exit_price=None,
            exit_time=None,
            exit_reason="no candles available for replay",
            realized_R=0.0,
            paper_pnl=0.0,
            paper_pnl_per_unit=0.0,
            mfe=0.0, mae=0.0,
            mfe_R=0.0, mae_R=0.0, max_drawdown_R=0.0,
            intrabar_ambiguous=False,
            fidelity=fidelity,
            is_expiry_day=bool(is_expiry_day),
            lots=lots,
            lot_size=lot_size,
        )

    # Single source of truth for the walk — delegate to 5B-A.
    try:
        result: ReplayResult | None = replay_alert(rep_row, candles, app_config)
    except Exception as e:
        logger.warning(f"paper.outcome: kernel error for {alert_id}: {e}")
        result = None

    if result is None:
        # Refusal (trail_sl_after_tp1 ON) or insufficient candles.
        reason = "kernel refused (trail_sl_after_tp1 ON or insufficient candles)"
        return PaperOutcome(
            alert_id=alert_id,
            outcome=OUTCOME_NO_DATA,
            exit_price=None,
            exit_time=None,
            exit_reason=reason,
            realized_R=0.0,
            paper_pnl=0.0,
            paper_pnl_per_unit=0.0,
            mfe=0.0, mae=0.0,
            mfe_R=0.0, mae_R=0.0, max_drawdown_R=0.0,
            intrabar_ambiguous=False,
            fidelity=fidelity,
            is_expiry_day=bool(is_expiry_day),
            lots=lots,
            lot_size=lot_size,
        )

    entry = float(rep_row["entry"])
    sl = float(rep_row["sl"])
    risk_per_unit = abs(entry - sl)
    paper_outcome = _map_kernel_to_paper(result.auto_order_status)

    pt = app_config.paper_trading
    realized_R = _r_multiple(
        paper_outcome,
        result.auto_pnl_per_unit,
        risk_per_unit,
        bool(is_expiry_day),
        tp1_R_normal=pt.tp1_R_normal,
        tp2_R_normal=pt.tp2_R_normal,
        tp1_R_expiry=pt.tp1_R_expiry,
        tp2_R_expiry=pt.tp2_R_expiry,
        tp1_then_be_R_normal=pt.tp1_then_be_R_normal,
        tp1_then_be_R_expiry=pt.tp1_then_be_R_expiry,
        sl_R=pt.sl_R,
    )

    paper_pnl_per_unit = float(result.auto_pnl_per_unit)
    paper_pnl = paper_pnl_per_unit * lots * lot_size

    mfe_R = result.mfe / risk_per_unit if risk_per_unit else 0.0
    mae_R = result.mae / risk_per_unit if risk_per_unit else 0.0
    max_drawdown_R = -mae_R  # MAE is the worst-case R drawdown

    return PaperOutcome(
        alert_id=alert_id,
        outcome=paper_outcome,
        exit_price=float(result.auto_exit_price),
        exit_time=str(result.auto_exit_time),
        exit_reason=str(result.auto_exit_reason),
        realized_R=float(realized_R),
        paper_pnl=float(paper_pnl),
        paper_pnl_per_unit=paper_pnl_per_unit,
        mfe=float(result.mfe),
        mae=float(result.mae),
        mfe_R=float(mfe_R),
        mae_R=float(mae_R),
        max_drawdown_R=float(max_drawdown_R),
        intrabar_ambiguous=bool(result.intrabar_ambiguous),
        fidelity=fidelity,
        is_expiry_day=bool(is_expiry_day),
        lots=lots,
        lot_size=lot_size,
    )


# ---------------------------------------------------------------------------
# Convenience: pre-fetch helpers used by the backfill + dashboard
# ---------------------------------------------------------------------------


CandleSource = Callable[[str, int, str, str, date_cls], pd.DataFrame | None]
"""Function signature: ``(symbol, strike, option_type, expiry, trading_date) -> candles | None``.

Matches the existing ``src.dashboard.candle_cache.get_or_fetch_candles``
without binding to it directly — this keeps Phase 5D testable with
a one-line stub.
"""


def resolve_candles(
    rep_row: dict[str, Any] | pd.Series,
    *,
    source: CandleSource,
) -> pd.DataFrame | None:
    """Pull candles for a representative via a caller-supplied source."""
    symbol = str(rep_row.get("symbol") or "")
    strike = int(rep_row.get("strike") or 0)
    option_type = str(rep_row.get("option_type") or "")
    expiry = str(rep_row.get("expiry") or "")
    candle_ts = rep_row.get("candle_ts")
    if candle_ts is None:
        candle_ts = rep_row.get("timestamp_ist")
    ts = pd.to_datetime(candle_ts)
    if ts.tzinfo is None:
        # Best effort — treat naive as already IST.
        trading_date = ts.date()
    else:
        trading_date = ts.tz_convert("Asia/Kolkata").date()
    try:
        return source(symbol, strike, option_type, expiry, trading_date)
    except Exception as e:
        logger.warning(f"paper.outcome: candle source raised: {e}")
        return None
