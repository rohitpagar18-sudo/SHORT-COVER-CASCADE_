"""Phase 5D — Paper-trade engine.

End-to-end pipeline that stitches the four pure-function modules
together. Used by both the backfill CLI and the dashboard generator
so there is exactly one place where the order is defined:

    alerts.jsonl  →  collapse_into_episodes  (D1)
                  →  select_paper_trades     (D2)
                  →  compute_paper_outcome   (D3, reuses 5B-A kernel)
                  →  write_paper_trades      (D4 — auto)
                  →  merge_overrides         (D4 — manual wins)

This module deliberately does no broker I/O. The caller passes a
``candle_source`` callable so tests can stub it; production callers
hand in ``src.dashboard.candle_cache.get_or_fetch_candles``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import pandas as pd
from loguru import logger

from src.paper.episodes import (
    Episode,
    collapse_into_episodes,
    collapse_ratio,
    episode_representatives,
    load_alerts_jsonl,
)
from src.paper.outcome import (
    OUTCOME_NO_DATA,
    PaperOutcome,
    compute_paper_outcome,
    resolve_candles,
    CandleSource,
)
from src.paper.persistence import (
    PaperTradeRecord,
    ensure_overrides_file,
    read_overrides,
    write_paper_trades,
)
from src.paper.selector import (
    DECISION_TAKEN,
    SelectionResult,
    select_paper_trades,
)


@dataclass
class PaperRunResult:
    """Summary of one end-to-end paper-engine run."""

    annotated_alerts: pd.DataFrame
    episodes: list[Episode]
    representatives: pd.DataFrame
    selection_results: list[SelectionResult]
    outcomes_taken: dict[str, PaperOutcome]
    outcomes_all_alerts: dict[str, PaperOutcome]
    records: list[PaperTradeRecord]
    paper_trades_path: str
    overrides_path: str
    collapse_summary: str


def _is_expiry_day(rep_row: pd.Series) -> bool:
    return str(rep_row.get("day_type") or "").strip().lower() == "expiry"


def _build_record(
    rep_row: pd.Series,
    selection: SelectionResult,
    outcome: PaperOutcome,
) -> PaperTradeRecord:
    candle_ts = rep_row.get("candle_ts")
    candle_ts_str = (
        candle_ts.isoformat() if hasattr(candle_ts, "isoformat") else str(candle_ts)
    )
    return PaperTradeRecord(
        alert_id=str(rep_row["alert_id"]),
        episode_id=str(rep_row.get("episode_id") or ""),
        paper_role="representative",
        date=str(rep_row.get("date") or candle_ts_str[:10]),
        candle_timestamp=candle_ts_str,
        symbol=str(rep_row.get("symbol") or ""),
        strike=int(rep_row.get("strike") or 0),
        relation=str(rep_row.get("relation") or ""),
        option_type=str(rep_row.get("option_type") or ""),
        expiry=str(rep_row.get("expiry") or ""),
        entry=float(rep_row.get("entry") or 0.0),
        sl=float(rep_row.get("sl") or 0.0),
        tp1=float(rep_row.get("tp1") or 0.0),
        tp2=float(rep_row.get("tp2") or 0.0),
        lots=int(rep_row.get("lots") or 0),
        lot_size=int(outcome.lot_size),
        is_expiry_day=bool(outcome.is_expiry_day),
        decision=selection.decision,
        decision_reason=selection.decision_reason,
        slot=selection.slot,
        outcome=outcome.outcome,
        exit_price=outcome.exit_price,
        exit_time=outcome.exit_time,
        exit_reason=outcome.exit_reason,
        realized_R=outcome.realized_R,
        paper_pnl=outcome.paper_pnl,
        paper_pnl_per_unit=outcome.paper_pnl_per_unit,
        mfe=outcome.mfe,
        mae=outcome.mae,
        mfe_R=outcome.mfe_R,
        mae_R=outcome.mae_R,
        max_drawdown_R=outcome.max_drawdown_R,
        intrabar_ambiguous=outcome.intrabar_ambiguous,
        fidelity=outcome.fidelity,
        fidelity_note=(rep_row.get("fidelity_note") or None),
        bot_remark=(str(rep_row.get("bot_remark")) if rep_row.get("bot_remark") else None),
        bot_tags=(str(rep_row.get("bot_tags")) if rep_row.get("bot_tags") else None),
        triggered_caps=list(selection.triggered_caps) if selection.triggered_caps else [],
    )


def run_paper_engine(
    *,
    alerts_path: str,
    app_config: Any,
    candle_source: CandleSource | None,
    paper_trades_path: str | None = None,
    overrides_path: str | None = None,
    write: bool = True,
    compute_all_alerts: bool = True,
) -> PaperRunResult:
    """End-to-end paper-trade engine run.

    Args:
        alerts_path: usually ``"logs/alerts.jsonl"``.
        app_config: live ``AppConfig`` — Phase 5D config block is read
            from ``app_config.paper_trading``.
        candle_source: callable returning candles per
            ``(symbol, strike, option_type, expiry, trading_date)``.
            ``None`` → every outcome is recorded as ``NO_DATA``.
        paper_trades_path / overrides_path: override the config paths
            (test convenience).
        write: when False, build records in memory but do NOT touch
            disk. The overrides file is also NOT created.
        compute_all_alerts: also compute the diagnostic outcomes for
            EVERY alert (echoes included). Defaults to True; tests may
            disable to keep mocks lean.

    Returns:
        ``PaperRunResult`` aggregating every intermediate state.
    """
    pt_cfg = app_config.paper_trading
    if paper_trades_path is None:
        paper_trades_path = pt_cfg.paper_trades_path
    if overrides_path is None:
        overrides_path = pt_cfg.paper_overrides_path

    # --- D1 ---
    alerts = load_alerts_jsonl(alerts_path)
    if alerts.empty:
        logger.info(f"paper.engine: no alerts found at {alerts_path}")
        if write:
            ensure_overrides_file(overrides_path)
            write_paper_trades(paper_trades_path, [])
        return PaperRunResult(
            annotated_alerts=alerts,
            episodes=[],
            representatives=pd.DataFrame(),
            selection_results=[],
            outcomes_taken={},
            outcomes_all_alerts={},
            records=[],
            paper_trades_path=str(paper_trades_path),
            overrides_path=str(overrides_path),
            collapse_summary="0 raw alerts → 0 episodes",
        )

    annotated, episodes = collapse_into_episodes(
        alerts,
        episode_key=pt_cfg.episode_key,
        dedup_window_minutes=pt_cfg.dedup_window_minutes,
        relation_priority=pt_cfg.relation_priority,
    )
    reps = episode_representatives(annotated)

    # --- D2 + D3 interleaved ---
    # The selector needs each TAKEN trade's outcome before deciding the
    # next row's caps. We pre-fetch candles ONCE per representative
    # (so we never hit the same cache file twice) and memoize outcomes.
    outcomes_taken: dict[str, PaperOutcome] = {}

    def _resolve_outcome(rep_row: pd.Series) -> str | None:
        aid = str(rep_row["alert_id"])
        if aid in outcomes_taken:
            return outcomes_taken[aid].outcome
        candles = (
            resolve_candles(rep_row, source=candle_source) if candle_source else None
        )
        po = compute_paper_outcome(
            rep_row,
            candles=candles,
            app_config=app_config,
            is_expiry_day=_is_expiry_day(rep_row),
        )
        outcomes_taken[aid] = po
        return po.outcome

    selection_results = select_paper_trades(
        reps,
        max_trades_per_day=pt_cfg.max_trades_per_day,
        circuit_breaker_sl_count=pt_cfg.circuit_breaker_sl_count,
        cooldown_minutes_after_sl=pt_cfg.cooldown_minutes_after_sl,
        same_strike_kill_after_2_sl=pt_cfg.same_strike_kill_after_2_sl,
        outcome_resolver=_resolve_outcome,
    )

    # Compute outcomes for SKIPPED reps too — the dashboard shows the
    # what-would-have-happened column for context.
    for _, rep in reps.iterrows():
        aid = str(rep["alert_id"])
        if aid in outcomes_taken:
            continue
        candles = (
            resolve_candles(rep, source=candle_source) if candle_source else None
        )
        outcomes_taken[aid] = compute_paper_outcome(
            rep,
            candles=candles,
            app_config=app_config,
            is_expiry_day=_is_expiry_day(rep),
        )

    # Diagnostic outcomes for ALL alerts (representatives + echoes).
    outcomes_all_alerts: dict[str, PaperOutcome] = dict(outcomes_taken)
    if compute_all_alerts:
        for _, row in annotated.iterrows():
            aid = str(row["alert_id"])
            if aid in outcomes_all_alerts:
                continue
            candles = (
                resolve_candles(row, source=candle_source) if candle_source else None
            )
            outcomes_all_alerts[aid] = compute_paper_outcome(
                row,
                candles=candles,
                app_config=app_config,
                is_expiry_day=_is_expiry_day(row),
            )

    # --- D4: records + persistence ---
    sel_by_aid = {s.alert_id: s for s in selection_results}
    records: list[PaperTradeRecord] = []
    for _, rep in reps.iterrows():
        aid = str(rep["alert_id"])
        sel = sel_by_aid.get(aid)
        if sel is None:
            continue
        outcome = outcomes_taken[aid]
        records.append(_build_record(rep, sel, outcome))

    if write:
        ensure_overrides_file(overrides_path)
        write_paper_trades(paper_trades_path, records)

    summary = collapse_ratio(annotated, episodes)
    return PaperRunResult(
        annotated_alerts=annotated,
        episodes=episodes,
        representatives=reps,
        selection_results=selection_results,
        outcomes_taken=outcomes_taken,
        outcomes_all_alerts=outcomes_all_alerts,
        records=records,
        paper_trades_path=str(paper_trades_path),
        overrides_path=str(overrides_path),
        collapse_summary=summary,
    )


def outcome_distribution(
    outcomes: dict[str, PaperOutcome] | list[PaperOutcome],
) -> dict[str, int]:
    """Return a label → count distribution."""
    if isinstance(outcomes, dict):
        labels = [o.outcome for o in outcomes.values()]
    else:
        labels = [o.outcome for o in outcomes]
    return dict(Counter(labels))
