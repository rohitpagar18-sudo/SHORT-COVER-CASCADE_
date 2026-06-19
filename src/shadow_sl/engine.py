"""Shadow-SL engine: method registry + shared candle walker.

The candle walk lives HERE — it is intentionally a separate
implementation from the live Phase 5B-A kernel
(``src.dashboard.outcome_replay``). Both walks share the same
intrabar convention (stop-first) so shadow results are directly
comparable to live outcomes, but they are otherwise independent. The
live kernel must never depend on this module.

Method authoring contract
-------------------------
Each method registers an ``evaluate`` callable via :func:`register`.
The signature is fixed::

    evaluate(entry, initial_sl, tp1, tp2, candles_df, params) -> dict

``candles_df`` is the FULL session's option candles
(``timestamp, open, high, low, close, volume`` — ``oi`` optional, ``timestamp``
timezone-aware IST, oldest first). ``params`` is a free-form dict that
MUST include ``entry_timestamp`` (timezone-aware IST datetime). Methods
delegate to :func:`walk_candles`, supplying a method-specific
``state_updater`` callback that maintains the current SL (and may
force-exit, e.g. the chandelier_time time-stop).

Return value (one dict per (alert × method))::

    {
        "exit_price":        float,
        "exit_time":         str (ISO IST timestamp),
        "exit_reason":       str,
        "r_multiple":        float,
        "max_unrealized_r":  float,
        "gave_back_r":       float,  # = max_unrealized_r - r_multiple
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Callable

import numpy as np
import pandas as pd

from src.indicators.vwap import compute_session_vwap

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {}


def register(name: str) -> Callable[[Callable[..., dict]], Callable[..., dict]]:
    """Decorator: bind ``func`` into :data:`REGISTRY` under ``name``."""

    def _decorate(func: Callable[..., dict]) -> Callable[..., dict]:
        REGISTRY[name] = func
        return func

    return _decorate


# ---------------------------------------------------------------------------
# Wilder's ATR — shadow-local. Live indicators are untouched.
# ---------------------------------------------------------------------------


def compute_atr_wilder(
    df: pd.DataFrame, period: int = 14
) -> pd.Series:
    """Wilder's-smoothed Average True Range on a candle frame.

    Args:
        df: DataFrame with columns ``high, low, close`` (chronological).
        period: lookback period (default 14).

    Returns:
        ``pd.Series`` aligned with ``df.index``. The first ``period``
        rows are NaN (seed window). Empty frame -> empty Series.
    """
    if df is None or len(df) == 0:
        return pd.Series([], dtype=float, index=df.index if df is not None else None)

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # First row has no prev_close — fall back to high-low.
    tr.iloc[0] = high.iloc[0] - low.iloc[0]

    # Wilder's RMA == EWM with alpha = 1/period, adjust=False.
    atr = tr.ewm(alpha=1.0 / float(period), adjust=False).mean()
    return atr.astype(float)


# ---------------------------------------------------------------------------
# Shared candle walker
# ---------------------------------------------------------------------------


@dataclass
class WalkState:
    """Per-candle state passed to ``state_updater``.

    Attributes:
        entry:           Position entry price.
        initial_sl:      Original SL (entry - R).
        tp1:             First-target price.
        tp2:             Final-target price.
        entry_ts:        Entry candle timestamp (timezone-aware IST).
        current_sl:      The SL in effect at the start of THIS candle.
        history:         Slice of the full session frame up to and
                         including the previous candle. Includes
                         ``session_vwap`` and ``atr`` columns.
        candle:          The current candle (a pd.Series) with
                         ``timestamp, open, high, low, close, volume,
                         session_vwap, atr``.
        candle_index:    Position of ``candle`` within the walked
                         window (0-based; the entry candle is -1).
        tp1_hit:         Whether TP1 has already been banked.
        max_unrealized_r: Best (high - entry) / R seen so far.
        highest_high_since_entry: Running max(high) since entry, used
                         by chandelier methods.
        params:          The method-specific params dict (forwarded as-is).
    """

    entry: float
    initial_sl: float
    tp1: float
    tp2: float
    entry_ts: datetime
    current_sl: float
    history: pd.DataFrame
    candle: pd.Series
    candle_index: int
    tp1_hit: bool
    max_unrealized_r: float
    highest_high_since_entry: float
    params: dict[str, Any] = field(default_factory=dict)


StateUpdater = Callable[[WalkState], dict[str, Any]]
"""Method-specific callback invoked at the START of each walked candle.

Return value is a dict that may contain:

  * ``new_sl`` (float, optional): the SL to apply BEFORE checking this
    candle's price action. Omit to keep ``state.current_sl`` unchanged.
  * ``force_exit`` (tuple[float, str], optional): ``(exit_price,
    reason)`` to force-exit at market on this candle, regardless of
    price action. Used by ``chandelier_time``'s time-stop.
"""


_TICK = 0.05  # NSE option tick. Used for the sma19 SL <= last close - 1 tick clamp.
HARD_SQUAREOFF_DEFAULT = time(15, 0)


def _prepare_session_candles(
    candles_df: pd.DataFrame, atr_period: int
) -> pd.DataFrame:
    """Copy, sort, fill volume, attach session VWAP + Wilder ATR columns."""
    df = candles_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
    df = df.sort_values("timestamp").reset_index(drop=True)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["session_vwap"] = compute_session_vwap(df)
    df["atr"] = compute_atr_wilder(df, period=int(atr_period))
    return df


def _is_full_red_below_vwap(c: pd.Series) -> bool:
    """Hard-exit rule: full red candle entirely below option session VWAP."""
    vwap = c.get("session_vwap")
    if vwap is None or pd.isna(vwap):
        return False
    o = float(c["open"])
    h = float(c["high"])
    low = float(c["low"])
    cl = float(c["close"])
    if cl >= o:
        return False  # not red
    return o < vwap and h < vwap and low < vwap and cl < vwap


def walk_candles(
    *,
    candles_df: pd.DataFrame,
    entry: float,
    initial_sl: float,
    tp1: float,
    tp2: float,
    entry_timestamp: datetime,
    state_updater: StateUpdater,
    params: dict[str, Any] | None = None,
    atr_period: int = 14,
    hard_squareoff_time: time = HARD_SQUAREOFF_DEFAULT,
    hard_exit_red_below_vwap: bool = True,
) -> dict[str, Any]:
    """Walk the post-entry portion of ``candles_df`` and return the outcome.

    Args:
        candles_df:       FULL session option candles (oldest first).
                          Must contain ``timestamp, open, high, low,
                          close``. ``volume`` is optional (defaults to
                          0). Timestamps are timezone-aware IST.
        entry:            Entry price.
        initial_sl:       Original SL (i.e. R-defining stop).
        tp1, tp2:         Target prices.
        entry_timestamp:  Timezone-aware IST datetime of the entry
                          candle. Candles with ``timestamp <= entry_ts``
                          are treated as history; the walk starts at the
                          next candle.
        state_updater:    Callback invoked before each candle's price
                          action — see :data:`StateUpdater`.
        params:           Forwarded into the ``WalkState`` as-is.
        atr_period:       Wilder period for the ATR column.
        hard_squareoff_time: Daily hard square-off (default 15:00).
        hard_exit_red_below_vwap: When True, exit on a complete red
                          candle entirely below the option's session
                          VWAP. Matches the live strategy rule.

    Returns:
        Outcome dict (see module docstring). ``r_multiple`` /
        ``max_unrealized_r`` / ``gave_back_r`` are 0.0 and
        ``exit_reason == "NO_DATA"`` when there are no post-entry
        candles to walk.
    """
    if candles_df is None or candles_df.empty:
        return _empty_result("NO_DATA: empty candle frame")

    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(candles_df.columns)
    if missing:
        raise ValueError(f"candles_df missing columns: {sorted(missing)}")

    df = _prepare_session_candles(candles_df, atr_period=atr_period)

    walk_mask = (df["timestamp"] > entry_timestamp) & (
        df["timestamp"].dt.time < hard_squareoff_time
    )
    walk = df[walk_mask].reset_index(drop=True)
    if walk.empty:
        return _empty_result("NO_DATA: no post-entry candles")

    risk = float(entry) - float(initial_sl)
    # Guard against degenerate risk (entry <= SL). Treat as 1.0 so the
    # ratio is still computable; callers see r_multiple = pnl_per_unit.
    R = risk if risk > 1e-9 else 1.0

    current_sl = float(initial_sl)
    tp1_hit = False
    max_unrealized_r = 0.0
    highest_high = float(entry)
    pnl_per_unit = 0.0
    exit_price: float | None = None
    exit_time: str | None = None
    exit_reason: str | None = None
    intrabar_ambiguous = False

    # Build history view: everything up to and including the entry
    # candle (i.e. ``timestamp <= entry_timestamp``). We DO NOT include
    # the live walk-candle in history when the updater is called for
    # that candle — that matches how a live trader sees the world.
    history_full = df[df["timestamp"] <= entry_timestamp].reset_index(drop=True)

    for i, candle in walk.iterrows():
        # Roll the history forward: at candle i, history = entry + walked[0..i-1].
        if i == 0:
            history_view = history_full
        else:
            history_view = pd.concat(
                [history_full, walk.iloc[:i]], ignore_index=True
            )

        state = WalkState(
            entry=float(entry),
            initial_sl=float(initial_sl),
            tp1=float(tp1),
            tp2=float(tp2),
            entry_ts=entry_timestamp,
            current_sl=current_sl,
            history=history_view,
            candle=candle,
            candle_index=int(i),
            tp1_hit=tp1_hit,
            max_unrealized_r=max_unrealized_r,
            highest_high_since_entry=highest_high,
            params=params or {},
        )

        decision = state_updater(state) or {}
        if "new_sl" in decision and decision["new_sl"] is not None:
            current_sl = float(decision["new_sl"])

        # Force-exit hook (e.g. time-stop). Fires before price action.
        force_exit = decision.get("force_exit")
        if force_exit is not None:
            fx_price, fx_reason = force_exit
            if tp1_hit:
                pnl_per_unit += 0.5 * (float(fx_price) - float(entry))
            else:
                pnl_per_unit += 1.0 * (float(fx_price) - float(entry))
            exit_price = float(fx_price)
            exit_time = pd.Timestamp(candle["timestamp"]).isoformat()
            exit_reason = str(fx_reason)
            break

        o = float(candle["open"])
        h = float(candle["high"])
        low = float(candle["low"])
        cl = float(candle["close"])

        highest_high = max(highest_high, h)
        # MFE tracking on the upside.
        unrealized_r_this_candle = (h - float(entry)) / R
        if unrealized_r_this_candle > max_unrealized_r:
            max_unrealized_r = unrealized_r_this_candle

        # ---------- Hard exit (red candle entirely below VWAP) ----------
        if hard_exit_red_below_vwap and _is_full_red_below_vwap(candle):
            vwap_val = float(candle["session_vwap"])
            if tp1_hit:
                pnl_per_unit += 0.5 * (cl - float(entry))
                exit_reason = (
                    f"TP1 banked then HARD_EXIT @ {cl:.2f} "
                    f"(red candle below VWAP {vwap_val:.2f})"
                )
            else:
                pnl_per_unit += 1.0 * (cl - float(entry))
                exit_reason = (
                    f"HARD_EXIT @ {cl:.2f} "
                    f"(red candle below VWAP {vwap_val:.2f})"
                )
            exit_price = cl
            exit_time = pd.Timestamp(candle["timestamp"]).isoformat()
            break

        sl_touched = low <= current_sl

        if not tp1_hit:
            tp1_touched = h >= float(tp1)
            tp2_touched = h >= float(tp2)

            if sl_touched and (tp1_touched or tp2_touched):
                # Intrabar ambiguity — stop fires first, full position.
                intrabar_ambiguous = True
                pnl_per_unit += 1.0 * (current_sl - float(entry))
                exit_price = current_sl
                exit_time = pd.Timestamp(candle["timestamp"]).isoformat()
                exit_reason = (
                    f"SL_HIT @ {current_sl:.2f} (intrabar SL+TP "
                    f"ambiguity — assumed SL first)"
                )
                break

            if sl_touched:
                pnl_per_unit += 1.0 * (current_sl - float(entry))
                exit_price = current_sl
                exit_time = pd.Timestamp(candle["timestamp"]).isoformat()
                exit_reason = f"SL_HIT @ {current_sl:.2f}"
                break

            if tp2_touched:
                pnl_per_unit += 0.5 * (float(tp1) - float(entry)) + 0.5 * (
                    float(tp2) - float(entry)
                )
                exit_price = float(tp2)
                exit_time = pd.Timestamp(candle["timestamp"]).isoformat()
                exit_reason = (
                    f"TP1 {float(tp1):.2f} and TP2 {float(tp2):.2f} "
                    f"both touched in same candle"
                )
                break

            if tp1_touched:
                pnl_per_unit += 0.5 * (float(tp1) - float(entry))
                tp1_hit = True
                # No breakeven step — the SL is owned by the method.
                continue

        else:
            tp2_touched = h >= float(tp2)
            if sl_touched and tp2_touched:
                intrabar_ambiguous = True
                pnl_per_unit += 0.5 * (current_sl - float(entry))
                exit_price = current_sl
                exit_time = pd.Timestamp(candle["timestamp"]).isoformat()
                exit_reason = (
                    f"TP1 banked then SL_HIT @ {current_sl:.2f} "
                    f"(intrabar SL+TP2 ambiguity — assumed SL first)"
                )
                break

            if sl_touched:
                pnl_per_unit += 0.5 * (current_sl - float(entry))
                exit_price = current_sl
                exit_time = pd.Timestamp(candle["timestamp"]).isoformat()
                exit_reason = (
                    f"TP1 banked then second leg hit SL @ {current_sl:.2f}"
                )
                break

            if tp2_touched:
                pnl_per_unit += 0.5 * (float(tp2) - float(entry))
                exit_price = float(tp2)
                exit_time = pd.Timestamp(candle["timestamp"]).isoformat()
                exit_reason = f"TP1 then TP2_HIT @ {float(tp2):.2f}"
                break

    if exit_price is None:
        # Walk completed without an exit -> force-close at last candle close.
        last = walk.iloc[-1]
        last_close = float(last["close"])
        last_ts = pd.Timestamp(last["timestamp"]).isoformat()
        if tp1_hit:
            pnl_per_unit += 0.5 * (last_close - float(entry))
            exit_reason = (
                f"TP1 banked, second leg force-closed at hard cut "
                f"@ {last_close:.2f}"
            )
        else:
            pnl_per_unit += 1.0 * (last_close - float(entry))
            exit_reason = f"EOD_FLAT — force-closed at hard cut @ {last_close:.2f}"
        exit_price = last_close
        exit_time = last_ts

    assert exit_price is not None and exit_time is not None and exit_reason is not None
    r_multiple = float(pnl_per_unit) / R
    # max_unrealized_r is in 100%-position R terms (a bird's-eye MFE).
    # Cap gave_back_r at 0 floor so a trade that never moved against
    # us beyond the trough still reports gave_back_r >= 0.
    gave_back_r = float(max_unrealized_r) - float(r_multiple)

    annotated_reason = exit_reason
    if intrabar_ambiguous and "intrabar" not in annotated_reason:
        annotated_reason += " [intrabar_ambiguous]"

    return {
        "exit_price": float(exit_price),
        "exit_time": str(exit_time),
        "exit_reason": str(annotated_reason),
        "r_multiple": float(r_multiple),
        "max_unrealized_r": float(max_unrealized_r),
        "gave_back_r": float(gave_back_r),
    }


def _empty_result(reason: str) -> dict[str, Any]:
    return {
        "exit_price": float("nan"),
        "exit_time": "",
        "exit_reason": reason,
        "r_multiple": 0.0,
        "max_unrealized_r": 0.0,
        "gave_back_r": 0.0,
    }


# Convenience accessors -----------------------------------------------------


def list_methods() -> list[str]:
    """Return registered method names in insertion order."""
    return list(REGISTRY.keys())


def get_method(name: str) -> Callable[..., dict[str, Any]]:
    """Look up a registered method by name. Raises KeyError if unknown."""
    return REGISTRY[name]


# Re-export tick size so methods can clamp consistently.
TICK = _TICK
