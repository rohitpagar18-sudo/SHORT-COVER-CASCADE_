"""Phase 5D — Paper-trade selection gate (D2).

Deterministic ``TAKEN`` / ``SKIPPED`` / ``ECHO`` gate that decides, for
each episode representative, whether a disciplined trader following
the strategy rules would have taken the trade. It does NOT place
orders and NEVER overwrites a manual override (Phase 5D-D4).

The selector REUSES the §13 / §14 semantics:
  - ``max_trades_per_day`` daily slot cap
  - 2-SL day-stop circuit breaker (§14)
  - cooldown window after each SL (§13)
  - same-strike kill after 2 SLs on that strike (§13)

To apply the SL-driven caps the selector needs each TAKEN trade's
outcome before deciding the next row. The caller passes an
``outcome_resolver(rep_row) -> dict | None`` that returns
``{"outcome": str | None, "exit_time": datetime | None}`` for a
TAKEN candidate — typically a small adapter around
``compute_paper_outcome``. The ``outcome`` slot drives the SL-based
caps (circuit breaker, same-strike kill, cooldown). The
``exit_time`` slot drives the position-open gate: a new alert on
the same ``(symbol, option_type)`` is SKIPPED while the prior
TAKEN trade is still live. ``exit_time=None`` (e.g. NO_DATA) is
conservative — it keeps the position open and blocks subsequent
same-key entries for the rest of the day.

The resolver itself may return ``None`` when outcomes cannot be
determined at all (legacy lambdas); in that case the position-open
tracking is skipped for that rep and the SL caps treat it as a
non-SL (best-effort).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

IST = ZoneInfo("Asia/Kolkata")

# Decision constants — re-used as string labels in paper_trades.jsonl
# and the Paper Trades sheet.
DECISION_TAKEN = "TAKEN"
DECISION_SKIPPED = "SKIPPED"
DECISION_ECHO = "ECHO"  # only used for non-representatives in the dashboard


SL_OUTCOMES = {"SL_HIT", "HARD_EXIT"}  # both count as an SL hit for §13/§14


@dataclass
class SelectionResult:
    """One row's selection-gate verdict + the outcome (if any) used."""

    alert_id: str
    decision: str  # TAKEN / SKIPPED
    decision_reason: str
    slot: int | None = None         # 1-based when TAKEN, else None
    triggered_caps: list[str] = field(default_factory=list)


@dataclass
class _DayState:
    """Per-day rolling state used by the cap engine."""

    taken_count: int = 0
    sl_count: int = 0
    sl_count_by_strike: dict[tuple, int] = field(default_factory=dict)
    killed_strikes: set[tuple] = field(default_factory=set)
    last_sl_time: datetime | None = None


def _strike_key(rep: pd.Series) -> tuple:
    """Strike-identity key for §13's same-strike kill.

    Per CLAUDE.md: 'Killed-strike state keys off strike NUMBER, not
    relation label.' Symbol + option_type + strike number identifies
    one tradable strike.
    """
    return (
        str(rep.get("symbol", "")).upper(),
        str(rep.get("option_type", "")).upper(),
        int(rep.get("strike")) if pd.notna(rep.get("strike")) else None,
    )


def _date_of(ts: datetime) -> str:
    return ts.date().isoformat()


# ---------------------------------------------------------------------------
# Public — selection gate
# ---------------------------------------------------------------------------


def _position_key(rep: pd.Series) -> tuple:
    """Position-tracking key for the open-position gate.

    Matches the default episode key in ``paper_trading.episode_key``:
    ``(symbol, option_type)``. The strike is INTENTIONALLY excluded —
    a live PE position on NIFTY blocks a new PE alert on the same
    symbol regardless of strike, because both bets are the same
    directional exposure.
    """
    return (
        str(rep.get("symbol", "")).upper(),
        str(rep.get("option_type", "")).upper(),
    )


def _coerce_exit_time(value: Any) -> datetime | None:
    """Best-effort coerce a kernel exit_time payload into a datetime.

    Accepts: ``datetime``, ISO string, ``None``. ISO strings without
    tz info are localized to IST. Any parse failure → ``None``
    (which conservatively treats the position as still open).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=IST)
    try:
        ts = pd.to_datetime(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize(IST)
    return ts.to_pydatetime()


def select_paper_trades(
    reps: pd.DataFrame,
    *,
    max_trades_per_day: int,
    circuit_breaker_sl_count: int,
    cooldown_minutes_after_sl: int,
    same_strike_kill_after_2_sl: bool,
    outcome_resolver: Callable[[pd.Series], dict | None] | None = None,
    relation_filter: Callable[[str | None], bool] | None = None,
) -> list[SelectionResult]:
    """Replay caps in chronological order and emit decisions.

    Args:
        reps: episode-representative rows (one paper-trade candidate
            each). MUST contain ``alert_id`` and ``candle_ts``. The
            frame is treated as immutable — decisions go in the
            returned list.
        max_trades_per_day: daily slot cap.
        circuit_breaker_sl_count: number of SLs in a day that stops
            further trades (default 2 per §14).
        cooldown_minutes_after_sl: §13 cooldown window after any SL.
        same_strike_kill_after_2_sl: §13 — once a strike has two SLs
            on the day, it is dead for the rest of the day.
        outcome_resolver: callable returning
            ``{"outcome": str | None, "exit_time": datetime | None}``
            for a TAKEN candidate. ``outcome`` drives the SL-based
            caps; ``exit_time`` drives the open-position gate. The
            resolver itself may return ``None`` for the legacy
            "outcome unknown, don't track position" mode.
        relation_filter: optional ``relation -> bool`` predicate. When
            it returns False the rep is SKIPPED before any §13/§14 cap
            runs. Wired to
            ``PaperOrderStrikesConfig.allows_relation`` in production.
            ``None`` disables the gate entirely.

    Returns:
        list of ``SelectionResult`` in input-row order (one per rep).
    """
    if reps is None or reps.empty:
        return []

    if "alert_id" not in reps.columns or "candle_ts" not in reps.columns:
        raise ValueError(
            "selector: reps must include 'alert_id' and 'candle_ts' "
            "(use episodes.collapse_into_episodes first)"
        )

    rep_df = reps.copy().reset_index(drop=True)
    rep_df["_orig_idx"] = range(len(rep_df))
    rep_df = rep_df.sort_values(by=["candle_ts"], kind="stable")

    cooldown = timedelta(minutes=int(cooldown_minutes_after_sl))
    day_states: dict[str, _DayState] = {}
    results_by_orig: dict[int, SelectionResult] = {}
    # (date, symbol, option_type) -> exit datetime. None = position still
    # open / unknown -> block future entries on the same key for the day.
    # Keyed by date so cross-day state never bleeds.
    position_exit_times: dict[tuple, datetime | None] = {}

    for _, rep in rep_df.iterrows():
        orig_idx = int(rep["_orig_idx"])
        ts: datetime = rep["candle_ts"]
        day = _date_of(ts)
        state = day_states.setdefault(day, _DayState())
        strike_key = _strike_key(rep)
        pos_key = (day,) + _position_key(rep)
        triggered: list[str] = []

        # ---------------- caps (order matters) ----------------
        # 0. position-open gate — block while a prior TAKEN trade
        #    on the same (symbol, option_type) for this day is still
        #    live. Runs first because if there's already an open
        #    paper position on this side, no other gate matters.
        if pos_key in position_exit_times:
            prior_exit = position_exit_times[pos_key]
            if prior_exit is None or ts < prior_exit:
                triggered.append("prior_episode_open")
                results_by_orig[orig_idx] = SelectionResult(
                    alert_id=str(rep["alert_id"]),
                    decision=DECISION_SKIPPED,
                    decision_reason="skipped: prior episode still open",
                    triggered_caps=triggered,
                )
                continue
            # Prior position closed before this rep -> clear & fall through.
            del position_exit_times[pos_key]

        # 1. paper_order_strikes relation gate — runs before §13/§14
        #    caps so a disabled-bucket rep never consumes a slot or
        #    triggers cooldown state.
        if relation_filter is not None:
            relation = rep.get("relation")
            if not relation_filter(relation):
                triggered.append("paper_order_strike_disabled")
                rel_label = str(relation) if relation is not None else "?"
                results_by_orig[orig_idx] = SelectionResult(
                    alert_id=str(rep["alert_id"]),
                    decision=DECISION_SKIPPED,
                    decision_reason=(
                        f"skipped: paper_order_strike not enabled ({rel_label})"
                    ),
                    triggered_caps=triggered,
                )
                continue

        # 2. circuit breaker (§14)
        if state.sl_count >= int(circuit_breaker_sl_count):
            triggered.append("circuit_breaker_2sl")
            results_by_orig[orig_idx] = SelectionResult(
                alert_id=str(rep["alert_id"]),
                decision=DECISION_SKIPPED,
                decision_reason=(
                    f"skipped: circuit breaker "
                    f"({state.sl_count} paper SL)"
                ),
                triggered_caps=triggered,
            )
            continue

        # 3. same-strike kill (§13)
        if same_strike_kill_after_2_sl and strike_key in state.killed_strikes:
            triggered.append("same_strike_killed")
            results_by_orig[orig_idx] = SelectionResult(
                alert_id=str(rep["alert_id"]),
                decision=DECISION_SKIPPED,
                decision_reason="skipped: same-strike killed (2 paper SL)",
                triggered_caps=triggered,
            )
            continue

        # 4. cooldown after SL (§13)
        if state.last_sl_time is not None and ts < state.last_sl_time + cooldown:
            triggered.append("cooldown_after_sl")
            mins = int(cooldown_minutes_after_sl)
            results_by_orig[orig_idx] = SelectionResult(
                alert_id=str(rep["alert_id"]),
                decision=DECISION_SKIPPED,
                decision_reason=f"skipped: cooldown {mins}m after SL",
                triggered_caps=triggered,
            )
            continue

        # 5. daily slot cap
        if state.taken_count >= int(max_trades_per_day):
            triggered.append("daily_cap")
            results_by_orig[orig_idx] = SelectionResult(
                alert_id=str(rep["alert_id"]),
                decision=DECISION_SKIPPED,
                decision_reason=(
                    f"skipped: daily cap ({max_trades_per_day}) reached"
                ),
                triggered_caps=triggered,
            )
            continue

        # ---------------- TAKEN ----------------
        state.taken_count += 1
        slot = state.taken_count
        results_by_orig[orig_idx] = SelectionResult(
            alert_id=str(rep["alert_id"]),
            decision=DECISION_TAKEN,
            decision_reason=f"taken (slot {slot}/{int(max_trades_per_day)})",
            slot=slot,
            triggered_caps=triggered,
        )

        # Resolve outcome (drives SL caps + position-open tracking).
        outcome_info: dict | None = None
        if outcome_resolver is not None:
            try:
                outcome_info = outcome_resolver(rep)
            except Exception as e:
                logger.warning(
                    f"selector: outcome_resolver failed for "
                    f"{rep.get('alert_id')}: {e}"
                )
                outcome_info = None

        outcome: str | None = None
        if outcome_info is not None:
            outcome = outcome_info.get("outcome")
            # Track the position's exit so the gate can clear later
            # entries. ``None`` is conservative -> blocks remainder
            # of the day for this (symbol, option_type).
            position_exit_times[pos_key] = _coerce_exit_time(
                outcome_info.get("exit_time")
            )

        if outcome and str(outcome).upper() in SL_OUTCOMES:
            state.sl_count += 1
            state.last_sl_time = ts
            count = state.sl_count_by_strike.get(strike_key, 0) + 1
            state.sl_count_by_strike[strike_key] = count
            if count >= 2 and same_strike_kill_after_2_sl:
                state.killed_strikes.add(strike_key)

    # Return in original row order.
    return [results_by_orig[i] for i in sorted(results_by_orig.keys())]
