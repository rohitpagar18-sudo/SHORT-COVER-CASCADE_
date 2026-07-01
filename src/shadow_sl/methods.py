"""Shadow-SL methods. Each is self-contained and registers via
:func:`src.shadow_sl.engine.register`.

The candle walk lives in ``engine.walk_candles``; methods only define
a ``state_updater`` callback that returns the SL to apply for the
current candle (and optionally a ``force_exit``).

Registered methods
------------------

  * ``sma19``           — baseline. Uses the EXISTING live helper
                          ``src.risk.stop_loss.compute_sma_trail_sl``
                          (read-only) and applies the clamp:
                          ``trailed_sl <= last_close - 1 tick``.
  * ``atr_initial``     — static stop, ``SL = entry_vwap - k*ATR``.
                          No trail.
  * ``chandelier``      — ``SL = highest_high_since_entry - k*ATR``.
                          Ratchets up only.
  * ``chandelier_time`` — chandelier PLUS a time stop: if
                          ``max_unrealized_r < time_stop_min_r`` by
                          ``time_stop_minutes`` after entry, force-exit
                          at market that candle.

All methods accept ``params``-style kwargs forwarded by the runner from
``config.shadow_sl.methods.<name>``.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

import pandas as pd

# Read-only re-use of the live SMA helper — explicitly NOT modifying it.
from src.risk.stop_loss import compute_sma_trail_sl
from src.shadow_sl.engine import (
    TICK,
    WalkState,
    register,
    walk_candles,
)


# ---------------------------------------------------------------------------
# sma19 — baseline (mirrors live Method 3, plus the cap-below-price clamp).
# ---------------------------------------------------------------------------


def _clamp_below_price(new_sl: float, ref_price: float, tick: float) -> float:
    """Ensure ``new_sl <= ref_price - 1 tick``.

    Protects the sma19 baseline from emitting an SL >= current price,
    which would degenerate into an immediate exit. Matches the natural
    Method-3 behavior (an SMA above the close is unusual and signals
    that the trail has run away from price).
    """
    cap = float(ref_price) - float(tick)
    return min(float(new_sl), cap)


@register("sma19")
def evaluate_sma19(
    entry: float,
    initial_sl: float,
    tp1: float,
    tp2: float,
    candles_df: pd.DataFrame,
    params: dict[str, Any],
) -> dict[str, Any]:
    """SMA-trail baseline. Read-only delegate to live ``compute_sma_trail_sl``."""
    sma_period = int(params.get("sma_period", 19))
    activate_after_min = int(params.get("activate_after_minutes", 15))
    update_interval_min = int(params.get("update_interval_minutes", 15))
    follow_direction = str(params.get("follow_direction", "ratchet"))
    atr_period = int(params.get("atr_period", 14))
    tick = float(params.get("tick", TICK))
    hard_squareoff = _parse_hhmm(params.get("hard_squareoff_time", "15:00"))
    entry_ts = pd.to_datetime(params["entry_timestamp"]).to_pydatetime()

    activate_td = timedelta(minutes=activate_after_min)
    update_td = timedelta(minutes=update_interval_min)
    next_trail_due = entry_ts + activate_td

    state_box = {"next_due": next_trail_due}

    def updater(state: WalkState) -> dict[str, Any]:
        candle_ts = pd.Timestamp(state.candle["timestamp"]).to_pydatetime()
        new_sl: float | None = None
        # Tick through any due trail evaluations.
        while candle_ts >= state_box["next_due"]:
            # SMA on the option close — history up to and including the
            # current candle. (compute_sma_trail_sl is the live helper.)
            close_series = pd.concat(
                [state.history["close"], pd.Series([state.candle["close"]])],
                ignore_index=True,
            )
            if len(close_series) >= sma_period:
                sma_val: float | None = float(close_series.tail(sma_period).mean())
            else:
                sma_val = None
            candidate = compute_sma_trail_sl(
                prev_sl=state.current_sl if new_sl is None else new_sl,
                sma_value=sma_val,
                follow_direction=follow_direction,
                method1_initial_sl=initial_sl,
            )
            if sma_val is not None:
                # Apply the shadow-baseline clamp: trailed SL stays
                # at least 1 tick below this candle's close so the
                # SL never overtakes the current price.
                candidate = _clamp_below_price(
                    candidate, float(state.candle["close"]), tick
                )
            new_sl = candidate
            state_box["next_due"] = state_box["next_due"] + update_td
        return {"new_sl": new_sl} if new_sl is not None else {}

    return walk_candles(
        candles_df=candles_df,
        entry=entry,
        initial_sl=initial_sl,
        tp1=tp1,
        tp2=tp2,
        entry_timestamp=entry_ts,
        state_updater=updater,
        params=params,
        atr_period=atr_period,
        hard_squareoff_time=hard_squareoff,
    )


# ---------------------------------------------------------------------------
# atr_initial — static stop. SL = entry_vwap - k*ATR(opt) at entry.
# ---------------------------------------------------------------------------


@register("atr_initial")
def evaluate_atr_initial(
    entry: float,
    initial_sl: float,
    tp1: float,
    tp2: float,
    candles_df: pd.DataFrame,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Static SL anchored at ``entry_vwap - k*ATR`` (no trail).

    The reference ``entry_vwap`` is the option's session VWAP at the
    entry candle (the same hlc3 session VWAP the live bot uses). ATR
    is computed locally (Wilder, period=``atr_period``).
    """
    k = float(params.get("k", 2.0))
    atr_period = int(params.get("atr_period", 14))
    hard_squareoff = _parse_hhmm(params.get("hard_squareoff_time", "15:00"))
    entry_ts = pd.to_datetime(params["entry_timestamp"]).to_pydatetime()

    # Pre-prepare the session frame once just to read the entry-row
    # values for SL anchoring. The walker repeats this prep internally
    # — duplicated work is negligible at shadow-lab scale.
    from src.shadow_sl.engine import _prepare_session_candles  # local import to avoid cycle

    df = _prepare_session_candles(candles_df, atr_period=atr_period)
    entry_rows = df[df["timestamp"] <= pd.Timestamp(entry_ts)]
    if entry_rows.empty:
        # No history — fall back to the original SL (still produces an outcome).
        anchored_sl = float(initial_sl)
    else:
        entry_row = entry_rows.iloc[-1]
        entry_vwap = entry_row.get("session_vwap")
        entry_atr = entry_row.get("atr")
        if (
            entry_vwap is None
            or pd.isna(entry_vwap)
            or entry_atr is None
            or pd.isna(entry_atr)
        ):
            anchored_sl = float(initial_sl)
        else:
            anchored_sl = float(entry_vwap) - k * float(entry_atr)

    def updater(state: WalkState) -> dict[str, Any]:
        # First tick installs the anchored SL; subsequent ticks no-op.
        if state.candle_index == 0 and state.current_sl != anchored_sl:
            return {"new_sl": anchored_sl}
        return {}

    return walk_candles(
        candles_df=candles_df,
        entry=entry,
        initial_sl=anchored_sl,  # seed the walker with the anchored SL
        tp1=tp1,
        tp2=tp2,
        entry_timestamp=entry_ts,
        state_updater=updater,
        params=params,
        atr_period=atr_period,
        hard_squareoff_time=hard_squareoff,
    )


# ---------------------------------------------------------------------------
# chandelier — SL = highest_high_since_entry - k*ATR. Ratchets up only.
# ---------------------------------------------------------------------------


def _chandelier_sl(
    state: WalkState, k: float
) -> float | None:
    """Return the chandelier SL candidate based on history.atr & highest high."""
    # ATR available on the prior candle (history). If history is empty
    # (entry was the first session candle), look at the live frame
    # attached to the current candle.
    atr_val: float | None = None
    if not state.history.empty and "atr" in state.history.columns:
        atr_series = state.history["atr"].dropna()
        if not atr_series.empty:
            atr_val = float(atr_series.iloc[-1])
    if atr_val is None and "atr" in state.candle.index:
        cand = state.candle.get("atr")
        if cand is not None and not pd.isna(cand):
            atr_val = float(cand)
    if atr_val is None or atr_val <= 0:
        return None
    return float(state.highest_high_since_entry) - float(k) * atr_val


@register("chandelier")
def evaluate_chandelier(
    entry: float,
    initial_sl: float,
    tp1: float,
    tp2: float,
    candles_df: pd.DataFrame,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Chandelier exit — SL = highest_high_since_entry - k*ATR, ratchet up."""
    k = float(params.get("k", 3.0))
    atr_period = int(params.get("atr_period", 14))
    hard_squareoff = _parse_hhmm(params.get("hard_squareoff_time", "15:00"))
    entry_ts = pd.to_datetime(params["entry_timestamp"]).to_pydatetime()

    def updater(state: WalkState) -> dict[str, Any]:
        cand = _chandelier_sl(state, k=k)
        if cand is None:
            return {}
        # Ratchet up only — never loosen.
        if cand > state.current_sl:
            return {"new_sl": cand}
        return {}

    return walk_candles(
        candles_df=candles_df,
        entry=entry,
        initial_sl=initial_sl,
        tp1=tp1,
        tp2=tp2,
        entry_timestamp=entry_ts,
        state_updater=updater,
        params=params,
        atr_period=atr_period,
        hard_squareoff_time=hard_squareoff,
    )


# ---------------------------------------------------------------------------
# chandelier_time — chandelier + a time-stop. If max_unrealized_r < min_r
# by time_stop_minutes after entry, exit at this candle's close.
# ---------------------------------------------------------------------------


@register("chandelier_time")
def evaluate_chandelier_time(
    entry: float,
    initial_sl: float,
    tp1: float,
    tp2: float,
    candles_df: pd.DataFrame,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Chandelier + time-stop combo."""
    k = float(params.get("k", 3.0))
    time_stop_minutes = int(params.get("time_stop_minutes", 35))
    time_stop_min_r = float(params.get("time_stop_min_r", 1.0))
    atr_period = int(params.get("atr_period", 14))
    hard_squareoff = _parse_hhmm(params.get("hard_squareoff_time", "15:00"))
    entry_ts = pd.to_datetime(params["entry_timestamp"]).to_pydatetime()

    time_stop_at = entry_ts + timedelta(minutes=time_stop_minutes)
    fired = {"v": False}

    def updater(state: WalkState) -> dict[str, Any]:
        # 1) Chandelier ratchet update.
        cand = _chandelier_sl(state, k=k)
        new_sl: float | None = None
        if cand is not None and cand > state.current_sl:
            new_sl = cand

        # 2) Time stop. Fires once, at the first candle whose
        # timestamp >= time_stop_at, ONLY when MFE so far is below the
        # min_r threshold. Forces exit at the candle's close so we
        # don't mix with the candle's intrabar SL/TP logic.
        candle_ts = pd.Timestamp(state.candle["timestamp"]).to_pydatetime()
        if (
            not fired["v"]
            and candle_ts >= time_stop_at
            and state.max_unrealized_r < time_stop_min_r
        ):
            fired["v"] = True
            exit_px = float(state.candle["close"])
            reason = (
                f"time_stop @ {exit_px:.2f} after {time_stop_minutes}m "
                f"(MFE {state.max_unrealized_r:.2f}R < {time_stop_min_r:.2f}R)"
            )
            result: dict[str, Any] = {"force_exit": (exit_px, reason)}
            if new_sl is not None:
                result["new_sl"] = new_sl
            return result

        return {"new_sl": new_sl} if new_sl is not None else {}

    return walk_candles(
        candles_df=candles_df,
        entry=entry,
        initial_sl=initial_sl,
        tp1=tp1,
        tp2=tp2,
        entry_timestamp=entry_ts,
        state_updater=updater,
        params=params,
        atr_period=atr_period,
        hard_squareoff_time=hard_squareoff,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_hhmm(value: Any) -> time:
    """Accept either an HH:MM string or a ``datetime.time`` object."""
    if isinstance(value, time):
        return value
    s = str(value)
    hh, mm = s.split(":")
    return time(int(hh), int(mm))
