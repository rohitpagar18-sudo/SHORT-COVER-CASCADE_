"""GET /api/overview — single aggregated payload for the Overview page.

Every read is wrapped in try/except in the underlying service; this
router just composes the response. Partial / locked files must NOT
500 — empty fields and zero counts are the correct degraded answer.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..models.overview import (
    Overview, Feed, Modes, Instruments, Position, Today,
    CircuitBreakers, NextEvents, BotStatus, RecentAlert,
)
from ..services import config_service, paper_service, signals_service, botstatus_service
from ..services.config_service import get, get_bool
from ..time_utils import now_ist, today_ist, is_market_open, fmt_ist


router = APIRouter()


@router.get("/overview", response_model=Overview)
def get_overview() -> Overview:
    # touch config cache (mtime check) once per request
    config_service.load_config()

    bot_status, last_activity = botstatus_service.status()

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
    pnl = paper_service.pnl_today()
    sl_hits = paper_service.sl_hits_today()

    today = Today(
        date_ist=today_ist().isoformat(),
        market_status="OPEN" if is_market_open(now) else "CLOSED",
        current_time_ist=now.strftime("%H:%M:%S"),
        gap_day=False,  # phase-1 placeholder; real gap_day comes from logs/gap_log.jsonl later
        signals_today=len(signals_service.signals_today()),
        positions_open=paper_service.open_positions_today(),
        sl_hit_today=sl_hits,
        paper_pnl_today=pnl,
    )

    cb_max_sl = _as_int(get("circuit_breakers.max_sl_per_day")) or 0
    cb_max_loss = _as_float(get("circuit_breakers.max_loss_per_day_rupees")) or 0.0
    circuit_breakers = CircuitBreakers(
        sl_count=sl_hits,
        max_sl_per_day=cb_max_sl,
        daily_loss=abs(min(0.0, pnl)),  # loss = negative pnl as positive number
        max_loss_per_day=cb_max_loss,
    )

    next_events = NextEvents(
        last_entry_time=str(get("time_rules.last_entry_time", "")) or None,
        soft_squareoff_time=str(get("time_rules.soft_squareoff_time", "")) or None,
        hard_squareoff_time=str(get("time_rules.hard_squareoff_time", "")) or None,
        eod_summary_time="15:30",
        dashboard_sync_time="15:35" if get_bool("dashboard.auto_trigger_at_1535", False) else None,
    )

    recent = [RecentAlert(**r) for r in signals_service.recent_alerts(5)]

    return Overview(
        feed=feed,
        modes=modes,
        instruments=instruments,
        position=position,
        today=today,
        circuit_breakers=circuit_breakers,
        next_events=next_events,
        recent_alerts=recent,
        bot=BotStatus(status=bot_status, last_activity_ist=last_activity),
        last_synced_ist=fmt_ist(now) or "",
    )


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
