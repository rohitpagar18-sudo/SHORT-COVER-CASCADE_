"""Response models for /api/overview and /api/bot/status.

Real field names observed from production data files (snapshot
2026-06-13). New fields added here are aggregated by the router from
the same files; no schema is invented, every value falls back to
None/0/[] when its source data is missing.

  signals.jsonl  -> timestamp_ist, event_type, symbol, strike, relation,
                    option_type, conditions_passed[], conditions_failed[],
                    all_passed, summary, spot_price, opt_above_vwap_pct ...
  alerts.jsonl   -> + entry, sl, tp1, tp2, lots, total_risk, lot_size,
                    time, date, day_type, vix_regime, bot_remark
  paper_trades.jsonl -> alert_id, episode_id, paper_role, date,
                    candle_timestamp, symbol, strike, relation,
                    option_type, entry, sl, tp1, tp2, lots, lot_size,
                    decision, outcome, exit_price, exit_time,
                    realized_R, paper_pnl, mfe, mae, mfe_R, mae_R ...
  state.json     -> {} (absent today; bot will start writing this once
                    state-persistence runs daily — handled gracefully)
"""
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
    paper_pnl_pct_today: float
    open_positions_count: int


class CircuitBreakers(BaseModel):
    sl_count: int
    max_sl_per_day: int
    daily_loss: float
    max_loss_per_day: float
    status: str  # OK | WARN | TRIPPED


class NextEvents(BaseModel):
    last_entry_time: Optional[str] = None
    soft_squareoff_time: Optional[str] = None
    hard_squareoff_time: Optional[str] = None
    eod_summary_time: Optional[str] = None
    dashboard_sync_time: Optional[str] = None


class ConditionFlag(BaseModel):
    name: str
    passed: bool


class RecentAlert(BaseModel):
    time: Optional[str] = None
    timestamp_ist: Optional[str] = None
    symbol: Optional[str] = None
    strike: Optional[int] = None
    option_type: Optional[str] = None
    relation: Optional[str] = None
    conditions: List[ConditionFlag] = []
    conditions_passed_count: int = 0
    conditions_total: int = 0
    status: Optional[str] = None
    risk: Optional[float] = None
    entry: Optional[float] = None
    lots: Optional[int] = None
    notes: Optional[str] = None


class PnlDay(BaseModel):
    date: str
    realized_pnl: float
    is_profit: bool


class CumulativePoint(BaseModel):
    date: str
    net: float


class PnlTotals(BaseModel):
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    max_daily_profit: float
    max_daily_loss: float


class PnlSeries(BaseModel):
    window_days: int
    days: List[PnlDay]
    cumulative: List[CumulativePoint]
    totals: PnlTotals


class PricePoint(BaseModel):
    t: str
    price: float


class OpenPosition(BaseModel):
    symbol: Optional[str] = None
    option_type: Optional[str] = None
    strike: Optional[int] = None
    relation: Optional[str] = None
    status: Optional[str] = None
    entry_time: Optional[str] = None
    qty_lots: Optional[int] = None
    buy_price: Optional[float] = None
    ltp: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    pnl: Optional[float] = None
    price_series: List[PricePoint] = []


class ConditionBucket(BaseModel):
    label: str
    count: int
    pct: float


class ConditionSummary(BaseModel):
    total_scans: int
    buckets: List[ConditionBucket]


class TradePlan(BaseModel):
    max_trades_per_day: int
    trades_taken: int
    trades_remaining: int
    daily_sl_hit: int
    max_sl_per_day: int
    cooldown_active: bool
    same_strike_sl_count: int


class ReentryStatus(BaseModel):
    cooldown_minutes: int
    minutes_since_last_sl: Optional[int] = None
    same_strike_kill_enabled: bool
    strikes_locked_today: List[int] = []


class BotStatus(BaseModel):
    status: str
    last_activity_ist: Optional[str] = None
    uptime_seconds: Optional[int] = None
    next_health_check_ist: Optional[str] = None
    last_config_reload_ist: Optional[str] = None


class Overview(BaseModel):
    feed: Feed
    modes: Modes
    instruments: Instruments
    position: Position
    today: Today
    circuit_breakers: CircuitBreakers
    next_events: NextEvents
    recent_alerts: List[RecentAlert]
    pnl_series: PnlSeries
    open_position: Optional[OpenPosition] = None
    condition_summary: ConditionSummary
    trade_plan: TradePlan
    reentry_status: ReentryStatus
    bot: BotStatus
    last_synced_ist: str
    date_ist: str
