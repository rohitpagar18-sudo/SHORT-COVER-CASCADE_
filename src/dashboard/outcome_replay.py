"""Phase 5B-A — Shared exit-replay kernel.

This module is the **single implementation** of the strategy's exit
logic used by:

  - the live dashboard sync (post-EOD virtual outcome stamping), and
  - Phase 7's backtest harness (called against historical candles).

It is a pure-function module: no broker calls, no file I/O. Callers
hand it a `pd.DataFrame` of 5-min option candles and the trade levels,
and get back a ``ReplayResult``. The wrappers in
``data_writer.sync_auto_outcomes_to_parquet`` and Phase 7 own the I/O.

Exit model follows Section 9 of ``ShortCoverCascade_v3.1_FINAL.md``:

  - SL hit (low <= current SL) before TP1 -> SL_HIT (full position).
  - Hard exit (complete red candle entirely below option session VWAP)
    before TP1 -> HARD_EXIT (full position).
  - TP1 touch -> exit 50%. If config.move_sl_to_breakeven_after_tp1 is
    ON, move SL of remainder to entry.
  - TP2 touch on remainder -> TP2_HIT.
  - SL/breakeven touch on remainder -> PARTIAL.
  - Hard exit on remainder -> PARTIAL.
  - Nothing hit by 3:00 PM -> EOD_FLAT (or TP1_HIT if TP1 was hit).
  - Intrabar ambiguity (one candle covers both stop and target):
    assume the stop fires first (conservative) and flag
    ``intrabar_ambiguous``.

Session VWAP for the hard-exit check is computed via
``src.indicators.vwap.compute_session_vwap`` — there is exactly one
VWAP implementation in this codebase.

Refusal: if ``config.risk_reward.trail_sl_after_tp1`` is ON the kernel
returns ``None`` from ``replay_alert`` with a loud warning. Silently
modelling breakeven would misrepresent a trailing strategy. v1
implements static breakeven-after-TP1 only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from src.indicators.vwap import compute_session_vwap

IST = ZoneInfo("Asia/Kolkata")

# Outcome category constants — matched against schema.md and the Excel
# Order Place sheet's color rules. Manual `order_status` uses the same
# names except EOD_FLAT and HARD_EXIT which are auto-only.
TP2_HIT = "TP2_HIT"
TP1_HIT = "TP1_HIT"
PARTIAL = "PARTIAL"
SL_HIT = "SL_HIT"
EOD_FLAT = "EOD_FLAT"
HARD_EXIT = "HARD_EXIT"


@dataclass(frozen=True)
class ExitConfig:
    """Per-trade exit knobs lifted from ``AppConfig.risk_reward`` /
    ``AppConfig.stop_loss`` / ``AppConfig.time_rules``.

    Kept as a dataclass so Phase 7 can construct it directly from a
    historical config snapshot without depending on the live pydantic
    model.
    """

    move_sl_to_breakeven_after_tp1: bool
    trail_sl_after_tp1: bool
    hard_exit_red_candle_below_vwap: bool
    hard_squareoff_time: time  # 15:00 IST in production


@dataclass(frozen=True)
class ReplayResult:
    """Output of one alert's virtual replay."""

    auto_order_status: str
    auto_exit_price: float
    auto_exit_time: str          # ISO IST timestamp
    auto_exit_reason: str
    auto_pnl_per_unit: float     # ₹ per unit, weighted 50/50 if TP1 hit
    mfe: float                   # max(high) − entry across walked candles
    mae: float                   # entry − min(low) across walked candles
    intrabar_ambiguous: bool


# ---------------------------------------------------------------------------
# Pure exit kernel — call this from anywhere (live sync, backtest, tests).
# ---------------------------------------------------------------------------


def replay_exits(
    candles: pd.DataFrame,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    exit_cfg: ExitConfig,
    alert_timestamp: datetime,
) -> ReplayResult | None:
    """Walk ``candles`` after ``alert_timestamp`` and return the outcome.

    Args:
        candles: Strike's 5-min candles for the alert's trading day —
            full session (09:15 → 15:00) so session VWAP can be
            computed for the hard-exit rule. Must have columns
            ``timestamp, open, high, low, close, volume`` (``oi``
            optional). Timestamps are timezone-aware IST. Sorted
            oldest -> newest.
        entry: option entry price.
        sl: original stop-loss price.
        tp1: first target price.
        tp2: final target price.
        exit_cfg: exit-rule toggles read from app config.
        alert_timestamp: timezone-aware IST datetime of the alert
            candle. Candles with timestamp <= this are treated as the
            entry candle and earlier — the walk starts at the next
            candle.

    Returns:
        A ``ReplayResult`` describing the virtual outcome, OR ``None``
        if the day's data is insufficient to make a verdict (no
        post-alert candles available yet).

    Notes:
        - This function is pure (no I/O, no broker calls).
        - It does not enforce idempotency — that is the caller's job.
    """
    if candles is None or candles.empty:
        return None
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"candles missing columns: {sorted(missing)}")

    df = candles.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Session VWAP for the hard-exit rule. Single source of truth in
    # src/indicators/vwap — never reimplement here.
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["session_vwap"] = compute_session_vwap(df)

    # Walk window: strictly after the alert candle, strictly before the
    # 15:00 hard square-off, both treated by IST clock time.
    hard_cut = exit_cfg.hard_squareoff_time
    walk = df[
        (df["timestamp"] > alert_timestamp)
        & (df["timestamp"].dt.time < hard_cut)
    ].reset_index(drop=True)

    if walk.empty:
        return None  # No post-alert candles for the day yet.

    current_sl = float(sl)
    tp1_hit = False
    intrabar_ambiguous = False
    mfe = 0.0
    mae = 0.0
    pnl_per_unit = 0.0
    exit_price: float | None = None
    exit_time: str | None = None
    exit_reason: str | None = None
    outcome: str | None = None

    for _, c in walk.iterrows():
        ts: pd.Timestamp = c["timestamp"]
        o = float(c["open"])
        h = float(c["high"])
        low = float(c["low"])
        cl = float(c["close"])
        vwap = float(c["session_vwap"]) if pd.notna(c["session_vwap"]) else None

        # MFE/MAE tracked across the full walked window.
        mfe = max(mfe, h - entry)
        mae = max(mae, entry - low)

        # ---------- Hard exit (red candle entirely below VWAP) ----------
        # Per spec sections 7/8: open, high, low, close ALL strictly
        # below VWAP AND close < open (red body).
        if (
            exit_cfg.hard_exit_red_candle_below_vwap
            and vwap is not None
            and cl < o  # red
            and o < vwap
            and h < vwap
            and low < vwap
            and cl < vwap
        ):
            if tp1_hit:
                # Half banked at TP1, remainder hard-exits.
                pnl_per_unit += 0.5 * (cl - entry)
                outcome = PARTIAL
                exit_reason = (
                    f"TP1 banked then HARD_EXIT @ {cl:.2f} "
                    f"(red candle below VWAP {vwap:.2f})"
                )
            else:
                pnl_per_unit += 1.0 * (cl - entry)
                outcome = HARD_EXIT
                exit_reason = (
                    f"HARD_EXIT @ {cl:.2f} "
                    f"(red candle below VWAP {vwap:.2f})"
                )
            exit_price = cl
            exit_time = ts.isoformat()
            break

        sl_touched = low <= current_sl

        if not tp1_hit:
            tp1_touched = h >= tp1
            tp2_touched = h >= tp2

            if sl_touched and (tp1_touched or tp2_touched):
                # Intrabar ambiguity: assume stop first.
                intrabar_ambiguous = True
                pnl_per_unit += 1.0 * (current_sl - entry)
                outcome = SL_HIT
                exit_price = current_sl
                exit_time = ts.isoformat()
                exit_reason = (
                    f"SL_HIT @ {current_sl:.2f} (intrabar SL+TP "
                    f"ambiguity — assumed SL first)"
                )
                break

            if sl_touched:
                pnl_per_unit += 1.0 * (current_sl - entry)
                outcome = SL_HIT
                exit_price = current_sl
                exit_time = ts.isoformat()
                exit_reason = f"SL_HIT @ {current_sl:.2f}"
                break

            if tp2_touched:
                # TP1 and TP2 hit in the same candle, no SL touch.
                pnl_per_unit += 0.5 * (tp1 - entry) + 0.5 * (tp2 - entry)
                outcome = TP2_HIT
                exit_price = tp2
                exit_time = ts.isoformat()
                exit_reason = (
                    f"TP1 {tp1:.2f} and TP2 {tp2:.2f} both touched in "
                    f"same candle"
                )
                break

            if tp1_touched:
                # Half exits at TP1. Move SL to breakeven if config ON.
                pnl_per_unit += 0.5 * (tp1 - entry)
                tp1_hit = True
                if exit_cfg.move_sl_to_breakeven_after_tp1:
                    current_sl = float(entry)
                # Continue walking with remaining 50%.
                continue

        else:
            # TP1 already banked; walking the second 50%.
            tp2_touched = h >= tp2

            if sl_touched and tp2_touched:
                intrabar_ambiguous = True
                pnl_per_unit += 0.5 * (current_sl - entry)
                outcome = PARTIAL
                exit_price = current_sl
                exit_time = ts.isoformat()
                exit_reason = (
                    f"TP1 banked then SL_HIT @ {current_sl:.2f} "
                    f"(intrabar SL+TP2 ambiguity — assumed SL first)"
                )
                break

            if sl_touched:
                pnl_per_unit += 0.5 * (current_sl - entry)
                outcome = PARTIAL
                exit_price = current_sl
                exit_time = ts.isoformat()
                be_label = (
                    "breakeven"
                    if exit_cfg.move_sl_to_breakeven_after_tp1
                    else "original SL"
                )
                exit_reason = (
                    f"TP1 banked then second leg hit {be_label} "
                    f"@ {current_sl:.2f}"
                )
                break

            if tp2_touched:
                pnl_per_unit += 0.5 * (tp2 - entry)
                outcome = TP2_HIT
                exit_price = tp2
                exit_time = ts.isoformat()
                exit_reason = f"TP1 then TP2_HIT @ {tp2:.2f}"
                break

    if outcome is None:
        # Loop completed without exit -> force-close at last walked
        # candle's close (~ the 15:00 mark).
        last = walk.iloc[-1]
        last_close = float(last["close"])
        last_ts = pd.Timestamp(last["timestamp"]).isoformat()
        if tp1_hit:
            pnl_per_unit += 0.5 * (last_close - entry)
            outcome = TP1_HIT
            exit_reason = (
                f"TP1 banked, second leg force-closed at 15:00 "
                f"@ {last_close:.2f}"
            )
        else:
            pnl_per_unit += 1.0 * (last_close - entry)
            outcome = EOD_FLAT
            exit_reason = f"EOD_FLAT — force-closed at 15:00 @ {last_close:.2f}"
        exit_price = last_close
        exit_time = last_ts

    assert outcome is not None and exit_price is not None and exit_time is not None

    return ReplayResult(
        auto_order_status=outcome,
        auto_exit_price=float(exit_price),
        auto_exit_time=str(exit_time),
        auto_exit_reason=str(exit_reason or outcome),
        auto_pnl_per_unit=float(pnl_per_unit),
        mfe=float(mfe),
        mae=float(mae),
        intrabar_ambiguous=bool(intrabar_ambiguous),
    )


# ---------------------------------------------------------------------------
# Convenience adapter: take a logged alert row + config + candles -> result.
# Refuses (returns None) if trail_sl_after_tp1 is ON.
# ---------------------------------------------------------------------------


def replay_alert(
    alert_row: dict[str, Any] | pd.Series,
    candles: pd.DataFrame,
    app_config: Any,
) -> ReplayResult | None:
    """Adapter: pull entry/SL/TP from a logged alert row and replay.

    Args:
        alert_row: dict-like with ``timestamp_ist``, ``entry``, ``sl``,
            ``tp1``, ``tp2``. Either a dict (e.g. parsed alerts.jsonl
            row) or a ``pd.Series`` row from Parquet.
        candles: full-session 5-min option candles for the alert's
            trading day. Same shape as ``BaseFeed.get_5min_candles``.
        app_config: an ``AppConfig`` (or any object exposing
            ``.risk_reward.move_sl_to_breakeven_after_tp1`` etc.).

    Returns:
        ``ReplayResult`` or ``None`` if the kernel could not produce a
        verdict (insufficient candles, or the trailing-SL refusal).
    """
    if app_config.risk_reward.trail_sl_after_tp1:
        alert_id = _format_alert_id(alert_row)
        logger.warning(
            f"outcome_replay: SKIP {alert_id} — config "
            f"risk_reward.trail_sl_after_tp1 is ON but trailing logic "
            "is not implemented in v1. Silent breakeven would "
            "misrepresent a trailing strategy. Set this OFF or wait "
            "for trailing support before auto outcome-tracking can "
            "stamp this alert."
        )
        return None

    entry = float(alert_row["entry"])
    sl = float(alert_row["sl"])
    tp1 = float(alert_row["tp1"])
    tp2 = float(alert_row["tp2"])
    alert_ts = pd.to_datetime(alert_row["timestamp_ist"])

    # Build the hard-square-off time once from config (HH:MM).
    hh, mm = (int(x) for x in app_config.time_rules.hard_squareoff_time.split(":"))
    hard_cut = time(hh, mm)

    exit_cfg = ExitConfig(
        move_sl_to_breakeven_after_tp1=bool(
            app_config.risk_reward.move_sl_to_breakeven_after_tp1
        ),
        trail_sl_after_tp1=bool(app_config.risk_reward.trail_sl_after_tp1),
        hard_exit_red_candle_below_vwap=bool(
            app_config.stop_loss.hard_exit_red_candle_below_vwap
        ),
        hard_squareoff_time=hard_cut,
    )

    return replay_exits(
        candles=candles,
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        exit_cfg=exit_cfg,
        alert_timestamp=alert_ts,
    )


def _format_alert_id(alert_row: dict[str, Any] | pd.Series) -> str:
    ts = alert_row.get("timestamp_ist", "?") if hasattr(alert_row, "get") else "?"
    sym = alert_row.get("symbol", "?") if hasattr(alert_row, "get") else "?"
    strike = alert_row.get("strike", "?") if hasattr(alert_row, "get") else "?"
    opt = alert_row.get("option_type", "?") if hasattr(alert_row, "get") else "?"
    return f"{ts}|{sym}|{strike}|{opt}"
