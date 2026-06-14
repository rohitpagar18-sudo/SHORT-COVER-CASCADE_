"""GET /api/overview?date=YYYY-MM-DD — single aggregated payload.

Every read is wrapped in try/except in the underlying services; this
router composes the response. Partial / locked files must NOT 500 —
empty fields and zero counts are the correct degraded answer.
"""
from __future__ import annotations

from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, Query

from ..models.overview import (
    Overview, Feed, Modes, Instruments, Position, Today,
    CircuitBreakers, NextEvents, BotStatus,
    RecentAlert, ConditionFlag, PnlSeries, PnlDay, CumulativePoint,
    PnlTotals, OpenPosition, PricePoint, ConditionSummary, ConditionBucket,
    TradePlan, ReentryStatus,
)
from ..services import (
    config_service, paper_service, signals_service, botstatus_service,
    state_service,
)
from ..services.config_service import get, get_bool
from ..time_utils import now_ist, today_ist, is_market_open, fmt_ist


router = APIRouter()


@router.get("/overview", response_model=Overview)
def get_overview(
    date: Optional[str] = Query(default=None, description="IST date YYYY-MM-DD; defaults to today"),
) -> Overview:
    # touch config cache (mtime check) once per request
    config_service.load_config()

    sel_date = _parse_date_or_today(date)
    sel_iso = sel_date.isoformat()

    bot_status, last_activity = botstatus_service.status()
    state = state_service.load_state()

    feed = Feed(
        active_feed=str(get("feeds.active_feed", "kite")),
        status=bot_status,
    )
    modes = Modes(
        alert_mode=get_bool("mode.alert_mode", False),
        order_place_mode=get_bool("mode.order_place_mode", False),
        paper_trade_mode=get_bool("mode.paper_trade_mode", False),
    )
    instruments = Instruments(
        nifty_enabled=get_bool("instruments.nifty_enabled", False),
        banknifty_enabled=get_bool("instruments.banknifty_enabled", False),
        nifty_lot_size=_as_int(get("instruments.nifty_lot_size")),
        banknifty_lot_size=_as_int(get("instruments.banknifty_lot_size")),
    )
    position = Position(
        nifty_max_lots=_as_int(get("position_sizing.nifty_max_lots")),
        banknifty_max_lots=_as_int(get("position_sizing.banknifty_max_lots")),
        lot_cap_enabled=get_bool("position_sizing.lot_cap_enabled", False),
    )

    now = now_ist()
    pnl = paper_service.pnl_on_date(sel_iso)
    sl_hits = paper_service.sl_hits_on_date(sel_iso)
    open_count = paper_service.open_positions_on_date(sel_iso)

    # Naive paper-pnl %: total / target_risk_per_trade × trades_taken.
    # If neither side has a meaningful base, fall back to 0.0 — never fabricate.
    target_risk = _as_float(get("risk_reward.target_risk_per_trade")) or 0.0
    trades_taken = paper_service.trades_taken_on_date(sel_iso)
    base = target_risk * max(trades_taken, 1) if target_risk else 0.0
    pnl_pct = round((pnl / base) * 100.0, 2) if base else 0.0

    today = Today(
        date_ist=sel_iso,
        market_status="OPEN" if (sel_iso == today_ist().isoformat() and is_market_open(now)) else "CLOSED",
        current_time_ist=now.strftime("%H:%M:%S"),
        gap_day=bool(state.get("gap_day", False)),
        signals_today=len(signals_service.signals_on_date(sel_iso)),
        positions_open=open_count,
        sl_hit_today=sl_hits,
        paper_pnl_today=pnl,
        paper_pnl_pct_today=pnl_pct,
        open_positions_count=open_count,
    )

    cb_max_sl = _as_int(get("circuit_breakers.max_sl_per_day")) or 0
    cb_max_loss = _as_float(get("circuit_breakers.max_loss_per_day_rupees")) or 0.0
    daily_loss = abs(min(0.0, pnl))
    cb_status = "OK"
    if (cb_max_sl and sl_hits >= cb_max_sl) or (cb_max_loss and daily_loss >= cb_max_loss):
        cb_status = "TRIPPED"
    elif (cb_max_sl and sl_hits >= max(1, cb_max_sl - 1)) or (cb_max_loss and daily_loss >= cb_max_loss * 0.66):
        cb_status = "WARN"
    circuit_breakers = CircuitBreakers(
        sl_count=sl_hits,
        max_sl_per_day=cb_max_sl,
        daily_loss=daily_loss,
        max_loss_per_day=cb_max_loss,
        status=cb_status,
    )

    next_events = NextEvents(
        last_entry_time=str(get("time_rules.last_entry_time", "")) or None,
        soft_squareoff_time=str(get("time_rules.soft_squareoff_time", "")) or None,
        hard_squareoff_time=str(get("time_rules.hard_squareoff_time", "")) or None,
        eod_summary_time="15:30",
        dashboard_sync_time="15:35" if get_bool("dashboard.auto_trigger_at_1535", False) else None,
    )

    recent = [
        RecentAlert(
            time=r["time"],
            timestamp_ist=r["timestamp_ist"],
            symbol=r["symbol"],
            strike=r["strike"],
            option_type=r["option_type"],
            relation=r["relation"],
            conditions=[ConditionFlag(**c) for c in r["conditions"]],
            conditions_passed_count=r["conditions_passed_count"],
            conditions_total=r["conditions_total"],
            status=r["status"],
            risk=r["risk"],
            entry=r["entry"],
            lots=r["lots"],
            notes=r["notes"],
        )
        for r in signals_service.recent_alerts_on_date(sel_iso, 5)
    ]

    pnl_blob = paper_service.pnl_series(window_days=15, end_date=sel_date)
    pnl_series = PnlSeries(
        window_days=pnl_blob["window_days"],
        days=[PnlDay(**d) for d in pnl_blob["days"]],
        cumulative=[CumulativePoint(**c) for c in pnl_blob["cumulative"]],
        totals=PnlTotals(**pnl_blob["totals"]),
    )

    op = paper_service.latest_open_position()
    open_position = None
    if op is not None:
        open_position = OpenPosition(
            **{k: v for k, v in op.items() if k != "price_series"},
            price_series=[PricePoint(**p) for p in op.get("price_series", [])],
        )

    cs = signals_service.condition_summary_on_date(sel_iso)
    condition_summary = ConditionSummary(
        total_scans=cs["total_scans"],
        buckets=[ConditionBucket(**b) for b in cs["buckets"]],
    )

    # NEW — call service functions, no duplicated logic
    _tp = paper_service.get_trade_plan_dict(sel_iso)
    trade_plan = TradePlan(**_tp)

    _rs = paper_service.get_reentry_status_dict(sel_iso)
    reentry_status = ReentryStatus(**_rs)

    return Overview(
        feed=feed,
        modes=modes,
        instruments=instruments,
        position=position,
        today=today,
        circuit_breakers=circuit_breakers,
        next_events=next_events,
        recent_alerts=recent,
        pnl_series=pnl_series,
        open_position=open_position,
        condition_summary=condition_summary,
        trade_plan=trade_plan,
        reentry_status=reentry_status,
        bot=BotStatus(
            status=bot_status,
            last_activity_ist=last_activity,
            uptime_seconds=botstatus_service.uptime_seconds(),
            next_health_check_ist=botstatus_service.next_health_check_ist(),
            last_config_reload_ist=botstatus_service.last_config_reload_ist(),
        ),
        last_synced_ist=fmt_ist(now) or "",
        date_ist=sel_iso,
    )


def _parse_date_or_today(s: Optional[str]) -> date_cls:
    if not s:
        return today_ist()
    try:
        return date_cls.fromisoformat(s)
    except ValueError:
        return today_ist()


def _as_int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
