"""Response models for /api/overview and /api/bot/status."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class Feed(BaseModel):
    active_feed: str
    status: str  # RUNNING | STOPPED


class Modes(BaseModel):
    alert_mode: bool
    order_place_mode: bool
    paper_trade_mode: bool


class Instruments(BaseModel):
    nifty_enabled: bool
    banknifty_enabled: bool
    nifty_lot_size: Optional[int] = None
    banknifty_lot_size: Optional[int] = None


class Position(BaseModel):
    nifty_max_lots: Optional[int] = None
    banknifty_max_lots: Optional[int] = None
    lot_cap_enabled: bool


class Today(BaseModel):
    date_ist: str
    market_status: str  # OPEN | CLOSED
    current_time_ist: str
    gap_day: bool
    signals_today: int
    positions_open: int
    sl_hit_today: int
    paper_pnl_today: float


class CircuitBreakers(BaseModel):
    sl_count: int
    max_sl_per_day: int
    daily_loss: float
    max_loss_per_day: float


class NextEvents(BaseModel):
    last_entry_time: Optional[str] = None
    soft_squareoff_time: Optional[str] = None
    hard_squareoff_time: Optional[str] = None
    eod_summary_time: Optional[str] = None
    dashboard_sync_time: Optional[str] = None


class RecentAlert(BaseModel):
    time: Optional[str] = None
    timestamp_ist: Optional[str] = None
    symbol: Optional[str] = None
    strike: Optional[int] = None
    option_type: Optional[str] = None
    relation: Optional[str] = None
    conditions_passed: List[str] = []
    status: Optional[str] = None
    risk: Optional[float] = None
    entry: Optional[float] = None
    lots: Optional[int] = None


class BotStatus(BaseModel):
    status: str
    last_activity_ist: Optional[str] = None


class Overview(BaseModel):
    feed: Feed
    modes: Modes
    instruments: Instruments
    position: Position
    today: Today
    circuit_breakers: CircuitBreakers
    next_events: NextEvents
    recent_alerts: List[RecentAlert]
    bot: BotStatus
    last_synced_ist: str
