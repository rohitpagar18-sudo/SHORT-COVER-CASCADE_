"""GET /api/trades + /api/trades/history — read-only paper-trade analytics.

Both endpoints read from logs/paper_trades.jsonl (and from
positions_service for unrealized P&L). Filters: date_from, date_to,
symbol, option_type, status (decision), outcome.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from ..services import trades_service


router = APIRouter()


@router.get("/trades")
def get_trades(
    date_from: Optional[str] = Query(default=None, description="IST YYYY-MM-DD inclusive"),
    date_to: Optional[str] = Query(default=None, description="IST YYYY-MM-DD inclusive"),
    symbol: Optional[str] = Query(default=None),
    option_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, description="TAKEN | SKIPPED"),
    outcome: Optional[str] = Query(
        default=None,
        description="TP2_HIT | TP1_HIT | SL_HIT | NO_DATA | PARTIAL | WOULD_SKIP",
    ),
) -> Dict[str, Any]:
    try:
        return trades_service.list_trades(
            date_from=date_from,
            date_to=date_to,
            symbol=symbol,
            option_type=option_type,
            status=status,
            outcome=outcome,
        )
    except Exception:
        return {
            "filters": {
                "date_from": date_from, "date_to": date_to,
                "symbol": symbol, "option_type": option_type,
                "status": status, "outcome": outcome,
            },
            "kpis": {
                "total_trades": 0, "winning_trades": 0, "winning_pct": 0.0,
                "losing_trades": 0, "losing_pct": 0.0, "total_pnl": 0.0,
                "realized_pnl": 0.0, "unrealized_pnl": 0.0,
                "max_daily_profit": 0.0, "max_daily_loss": 0.0,
            },
            "trades": [],
            "daily_series": [],
        }


@router.get("/trades/history")
def get_trades_history(
    group_by: str = Query(default="day", description="day | week | month"),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    symbol: Optional[str] = Query(default=None),
    option_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    outcome: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    try:
        return trades_service.history(
            group_by=group_by,
            date_from=date_from,
            date_to=date_to,
            symbol=symbol,
            option_type=option_type,
            status=status,
            outcome=outcome,
        )
    except Exception:
        return {
            "group_by": group_by,
            "filters": {
                "date_from": date_from, "date_to": date_to,
                "symbol": symbol, "option_type": option_type,
                "status": status, "outcome": outcome,
            },
            "groups": [],
        }
