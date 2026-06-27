"""Phase 5B-A — Shared exit-replay kernel.

This module is the **single implementation** of the strategy's exit
logic used by:

  - the live dashboard sync (post-EOD virtual outcome stamping), and
  - Phase 7's backtest harness (called against historical candles).

It is a pure-function module: no broker calls, no file I/O. Callers
hand it a `pd.DataFrame` of 5-min option candles and the trade levels,
and get back a ``ReplayResult``. The wrappers in
``data_writer.sync_auto_outcomes_to_parquet`` and Phase 7 own the I/O.

Exit model follows Sections 7/8/9 of ``ShortCoverCascade_v3.1_FINAL.md``.
The kernel honors whichever ``stop_loss.method`` is active:

  - Method 1 (point buffer) / Method 2 (percentage): SL is static
    until TP1, then optionally moved to breakeven when
    ``risk_reward.move_sl_to_breakeven_after_tp1`` is ON.
  - Method 3 (Method-1 initial then N-SMA trail): SL is the logged
    Method-1 price until ``sma_trail.activate_after_minutes`` after
    entry. After that, it is updated every
    ``sma_trail.update_interval_minutes`` to the N-SMA of the option
    close (``follow_direction = both | ratchet``). Trailing continues
    through and after TP1 — there is no breakeven step under Method 3.
    Early-entry fallback: hold the Method-1 SL until N candles are
    available; never trail on a partial SMA.

Common rules across all methods:

  - SL hit (low <= current SL) before TP1 -> SL_HIT (full position).
  - Hard exit (complete red candle entirely below option session VWAP)
    before TP1 -> HARD_EXIT (full position).
  - TP1 touch -> exit ``tp1_lots`` (see ``compute_lot_split``).
    Targets do NOT move with the trail.
  - Single-lot trades (``tp2_lots == 0``): TP1 touch closes the full
    position immediately. No breakeven step, no TP2 monitoring.
    Outcome = ``TP1_HIT``.
  - TP2 touch on remainder -> TP2_HIT.
  - SL/breakeven/trailed-SL touch on remainder -> PARTIAL.
  - Hard exit on remainder -> PARTIAL.
  - Nothing hit by 3:00 PM -> EOD_FLAT (or TP1_HIT if TP1 was hit).
  - Intrabar ambiguity (one candle covers both stop and target):
    assume the stop fires first (conservative) and flag
    ``intrabar_ambiguous``.

Session VWAP for the hard-exit check is computed via
``src.indicators.vwap.compute_session_vwap`` — there is exactly one
VWAP implementation in this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from src.indicators.vwap import compute_session_vwap
from src.risk.lot_sizing import compute_lot_split
from src.risk.stop_loss import SmaTrailParams, compute_sma_trail_sl

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
    # Method 3 fields. ``sl_method`` defaults to 1 so Phase 7 and existing
    # callers building an ExitConfig keep working without changes.
    sl_method: int = 1
    sma_trail: SmaTrailParams | None = None


@dataclass(frozen=True)
class MultiMethodResult:
    """Shadow-runs all three SL methods for one alert using the same candles.

    The authoritative outcome is the one matching the live
    ``stop_loss.method`` in config. The other two are SHADOW ONLY and
    never feed paper_pnl, win-rate, or any live metric.
    """

    method1: "ReplayResult | None"
    method2: "ReplayResult | None"
    method3: "ReplayResult | None"


@dataclass(frozen=True)
class ReplayResult:
    """Output of one alert's virtual replay."""

    auto_order_status: str
    auto_exit_price: float
    auto_exit_time: str          # ISO IST timestamp
    auto_exit_reason: str
    auto_pnl_per_unit: float     # ₹ per unit, weighted by lot split
                                 # (tp1_fraction/tp2_fraction). For even
                                 # lots this is 50/50; odd lots tilt the
                                 # weight toward the TP1 leg.
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
    lots: int = 2,
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
        lots: total lot count for the trade. Drives the lot split via
            :func:`src.risk.lot_sizing.compute_lot_split`. Defaults to
            ``2`` (clean 50/50) for legacy callers. When ``lots == 1``,
            TP1 closes the full position — no TP2 leg, no breakeven.

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
    tp1_lots, tp2_lots = compute_lot_split(max(1, int(lots)))
    total_lots = tp1_lots + tp2_lots
    tp1_frac = tp1_lots / total_lots
    tp2_frac = tp2_lots / total_lots
    single_lot = tp2_lots == 0
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

    # Method 3 (SMA-trail) state. Only used when sl_method == 3 AND a
    # trail config was provided. Tracks the next scheduled trail tick
    # (entry + activate_after_minutes, then every update_interval thereafter).
    trail_cfg = exit_cfg.sma_trail if exit_cfg.sl_method == 3 else None
    next_trail_due: datetime | None = None
    if trail_cfg is not None:
        activate_td = timedelta(minutes=int(trail_cfg.activate_after_minutes))
        update_td = timedelta(minutes=int(trail_cfg.update_interval_minutes))
        next_trail_due = pd.Timestamp(alert_timestamp).to_pydatetime() + activate_td
    else:
        activate_td = timedelta()
        update_td = timedelta()
    trail_reason_parts: list[str] = []

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

        # ---------- Method 3 — SMA trail tick ----------
        # Re-evaluate the SL when this candle's close-time has reached
        # the next scheduled trail tick. The SL update uses the SMA of
        # the last N closes including this candle. Early-entry fallback:
        # if fewer than N candles exist, hold the prior SL.
        if trail_cfg is not None and next_trail_due is not None:
            ts_py = pd.Timestamp(ts).to_pydatetime()
            while ts_py >= next_trail_due:
                history = df[df["timestamp"] <= ts]["close"]
                if len(history) >= trail_cfg.sma_period:
                    sma_val: float | None = float(
                        history.tail(trail_cfg.sma_period).mean()
                    )
                else:
                    sma_val = None
                new_sl = compute_sma_trail_sl(
                    prev_sl=current_sl,
                    sma_value=sma_val,
                    follow_direction=trail_cfg.follow_direction,
                )
                if sma_val is not None and new_sl != current_sl:
                    trail_reason_parts.append(
                        f"trail@{ts.strftime('%H:%M')}={new_sl:.2f}"
                    )
                    current_sl = new_sl
                next_trail_due = next_trail_due + update_td

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
                # TP1 leg banked; remainder (tp2_frac) hard-exits.
                pnl_per_unit += tp2_frac * (cl - entry)
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
                # Single-lot trades cannot run to TP2 — collapse to a
                # full TP1 exit on this same candle.
                if single_lot:
                    pnl_per_unit += 1.0 * (tp1 - entry)
                    outcome = TP1_HIT
                    exit_price = tp1
                    exit_time = ts.isoformat()
                    exit_reason = (
                        f"TP1_HIT @ {tp1:.2f} (single-lot full exit; "
                        f"TP2 also touched in same candle)"
                    )
                    break
                pnl_per_unit += tp1_frac * (tp1 - entry) + tp2_frac * (tp2 - entry)
                outcome = TP2_HIT
                exit_price = tp2
                exit_time = ts.isoformat()
                exit_reason = (
                    f"TP1 {tp1:.2f} and TP2 {tp2:.2f} both touched in "
                    f"same candle"
                )
                break

            if tp1_touched:
                # Single-lot trades cannot split — close the full
                # position at TP1, no breakeven step, no TP2 monitoring.
                if single_lot:
                    pnl_per_unit += 1.0 * (tp1 - entry)
                    outcome = TP1_HIT
                    exit_price = tp1
                    exit_time = ts.isoformat()
                    exit_reason = (
                        f"TP1_HIT @ {tp1:.2f} (single-lot full exit)"
                    )
                    break
                # Multi-lot: exit tp1_frac at TP1, runner stays open.
                # Under Method 1/2, move SL to breakeven if config ON.
                # Under Method 3, breakeven does NOT apply — the SMA
                # trail continues to manage the SL on the second leg.
                pnl_per_unit += tp1_frac * (tp1 - entry)
                tp1_hit = True
                if (
                    trail_cfg is None
                    and exit_cfg.move_sl_to_breakeven_after_tp1
                ):
                    current_sl = float(entry)
                # Continue walking with remaining tp2_frac of position.
                continue

        else:
            # TP1 already banked; walking the second 50%.
            tp2_touched = h >= tp2

            if sl_touched and tp2_touched:
                intrabar_ambiguous = True
                pnl_per_unit += tp2_frac * (current_sl - entry)
                outcome = PARTIAL
                exit_price = current_sl
                exit_time = ts.isoformat()
                exit_reason = (
                    f"TP1 banked then SL_HIT @ {current_sl:.2f} "
                    f"(intrabar SL+TP2 ambiguity — assumed SL first)"
                )
                break

            if sl_touched:
                pnl_per_unit += tp2_frac * (current_sl - entry)
                outcome = PARTIAL
                exit_price = current_sl
                exit_time = ts.isoformat()
                if trail_cfg is not None:
                    be_label = "trailed SL"
                elif exit_cfg.move_sl_to_breakeven_after_tp1:
                    be_label = "breakeven"
                else:
                    be_label = "original SL"
                exit_reason = (
                    f"TP1 banked then second leg hit {be_label} "
                    f"@ {current_sl:.2f}"
                )
                break

            if tp2_touched:
                pnl_per_unit += tp2_frac * (tp2 - entry)
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
            pnl_per_unit += tp2_frac * (last_close - entry)
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

    final_reason = str(exit_reason or outcome)
    if trail_reason_parts:
        final_reason = f"{final_reason} [SMA-trail: {', '.join(trail_reason_parts)}]"

    return ReplayResult(
        auto_order_status=outcome,
        auto_exit_price=float(exit_price),
        auto_exit_time=str(exit_time),
        auto_exit_reason=final_reason,
        auto_pnl_per_unit=float(pnl_per_unit),
        mfe=float(mfe),
        mae=float(mae),
        intrabar_ambiguous=bool(intrabar_ambiguous),
    )


# ---------------------------------------------------------------------------
# Convenience adapter: take a logged alert row + config + candles -> result.
# Simulates whichever stop_loss.method (1/2/3) is configured.
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
            ``.risk_reward.move_sl_to_breakeven_after_tp1``,
            ``.stop_loss.method``, ``.stop_loss.sma_trail``, etc.).

    Returns:
        ``ReplayResult`` or ``None`` only when the day's data is
        insufficient (no post-alert candles). The kernel simulates the
        active ``stop_loss.method`` — Method 1/2 with optional breakeven
        after TP1, or Method 3 with the SMA trail. It no longer refuses
        on ``risk_reward.trail_sl_after_tp1``: under Method 1/2 that
        legacy flag is informational (behavior matches
        ``move_sl_to_breakeven_after_tp1``); Method 3 owns trailing.
    """
    entry = float(alert_row["entry"])
    sl = float(alert_row["sl"])
    tp1 = float(alert_row["tp1"])
    tp2 = float(alert_row["tp2"])
    alert_ts = pd.to_datetime(alert_row["timestamp_ist"])
    # Lots drive the TP1/TP2 split fractions. Default to 2 (clean 50/50)
    # only when an alert row is missing the field — production rows
    # always carry it.
    lots_raw = alert_row.get("lots") if hasattr(alert_row, "get") else None
    try:
        lots = int(lots_raw) if lots_raw not in (None, "") else 2
    except (TypeError, ValueError):
        lots = 2
    if lots < 1:
        lots = 2

    # Build the hard-square-off time once from config (HH:MM).
    hh, mm = (int(x) for x in app_config.time_rules.hard_squareoff_time.split(":"))
    hard_cut = time(hh, mm)

    sl_method = int(getattr(app_config.stop_loss, "method", 1))
    sma_trail_params: SmaTrailParams | None = None
    if sl_method == 3:
        sma_cfg = getattr(app_config.stop_loss, "sma_trail", None)
        if sma_cfg is not None:
            sma_trail_params = SmaTrailParams(
                sma_period=int(getattr(sma_cfg, "sma_period", 19)),
                activate_after_minutes=int(
                    getattr(sma_cfg, "activate_after_minutes", 15)
                ),
                update_interval_minutes=int(
                    getattr(sma_cfg, "update_interval_minutes", 15)
                ),
                follow_direction=str(
                    getattr(sma_cfg, "follow_direction", "both")
                ),
            )

    exit_cfg = ExitConfig(
        move_sl_to_breakeven_after_tp1=bool(
            app_config.risk_reward.move_sl_to_breakeven_after_tp1
        ),
        trail_sl_after_tp1=bool(app_config.risk_reward.trail_sl_after_tp1),
        hard_exit_red_candle_below_vwap=bool(
            app_config.stop_loss.hard_exit_red_candle_below_vwap
        ),
        hard_squareoff_time=hard_cut,
        sl_method=sl_method,
        sma_trail=sma_trail_params,
    )

    return replay_exits(
        candles=candles,
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        exit_cfg=exit_cfg,
        alert_timestamp=alert_ts,
        lots=lots,
    )


# ---------------------------------------------------------------------------
# Shadow comparison helper — runs all three SL methods on the same candles.
# ---------------------------------------------------------------------------


def _build_exit_cfg_for_method(
    method: int,
    app_config: Any,
    hard_cut: time,
) -> ExitConfig:
    """Build an ExitConfig for an explicit SL method, reusing shared config fields."""
    move_be = bool(app_config.risk_reward.move_sl_to_breakeven_after_tp1)
    trail_after_tp1 = bool(app_config.risk_reward.trail_sl_after_tp1)
    hard_exit = bool(app_config.stop_loss.hard_exit_red_candle_below_vwap)

    sma_trail_params: SmaTrailParams | None = None
    if method == 3:
        sma_cfg = getattr(app_config.stop_loss, "sma_trail", None)
        if sma_cfg is not None:
            sma_trail_params = SmaTrailParams(
                sma_period=int(getattr(sma_cfg, "sma_period", 19)),
                activate_after_minutes=int(
                    getattr(sma_cfg, "activate_after_minutes", 15)
                ),
                update_interval_minutes=int(
                    getattr(sma_cfg, "update_interval_minutes", 15)
                ),
                follow_direction=str(
                    getattr(sma_cfg, "follow_direction", "both")
                ),
            )

    return ExitConfig(
        move_sl_to_breakeven_after_tp1=move_be,
        trail_sl_after_tp1=trail_after_tp1,
        hard_exit_red_candle_below_vwap=hard_exit,
        hard_squareoff_time=hard_cut,
        sl_method=method,
        sma_trail=sma_trail_params,
    )


def replay_alert_all_methods(
    alert_row: "dict[str, Any] | pd.Series",
    candles: pd.DataFrame,
    app_config: Any,
) -> MultiMethodResult:
    """Run the exit kernel for all three SL methods using the same candles.

    Candles are NOT re-fetched — the caller passes the already-loaded
    DataFrame. All three method walks share the same VWAP computation
    (computed inside ``replay_exits`` from the same candles object).

    The authoritative result is whichever method matches
    ``app_config.stop_loss.method``; the other two are SHADOW ONLY and
    must never influence live paper_pnl or win-rate figures.

    Returns a :class:`MultiMethodResult`.  Each slot is ``None`` only
    when ``replay_exits`` returns ``None`` (no post-alert candles) or
    if an unexpected exception occurs for that specific method.
    """
    entry = float(alert_row["entry"])
    sl = float(alert_row["sl"])
    tp1 = float(alert_row["tp1"])
    tp2 = float(alert_row["tp2"])
    alert_ts = pd.to_datetime(alert_row["timestamp_ist"])
    lots_raw = alert_row.get("lots") if hasattr(alert_row, "get") else None
    try:
        lots = int(lots_raw) if lots_raw not in (None, "") else 2
    except (TypeError, ValueError):
        lots = 2
    if lots < 1:
        lots = 2

    hh, mm = (int(x) for x in app_config.time_rules.hard_squareoff_time.split(":"))
    hard_cut = time(hh, mm)

    results: list[ReplayResult | None] = []
    for m in (1, 2, 3):
        cfg = _build_exit_cfg_for_method(m, app_config, hard_cut)
        try:
            r = replay_exits(
                candles=candles,
                entry=entry,
                sl=sl,
                tp1=tp1,
                tp2=tp2,
                exit_cfg=cfg,
                alert_timestamp=alert_ts,
                lots=lots,
            )
        except Exception:
            r = None
        results.append(r)

    return MultiMethodResult(method1=results[0], method2=results[1], method3=results[2])
