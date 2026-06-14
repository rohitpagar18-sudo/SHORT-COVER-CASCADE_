"""GET /api/reports/performance — Dashboard & Reports, Performance Overview tab."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from ..services import reports_service

router = APIRouter()


@router.get("/reports/performance")
def get_performance(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    agg: str = Query(default="daily", description="daily | weekly | monthly"),
) -> Dict[str, Any]:
    try:
        return reports_service.get_performance(date_from=date_from, date_to=date_to, agg=agg)
    except Exception:
        empty_kpi: Dict[str, Any] = {"value": None, "prev_value": None, "delta_pct": None, "spark": []}
        return {
            "kpis": {k: dict(empty_kpi) for k in ["total_pnl", "total_trades", "win_rate", "profit_factor", "avg_win", "avg_loss", "expectancy"]},
            "cumulative": [],
            "pnl_by_underlying": [],
            "pnl_by_weekday": [],
            "top_winners": [],
            "top_losers": [],
            "outcome_distribution": [],
            "trade_duration": None,
            "monthly": [],
            "meta": {"date_from": date_from, "date_to": date_to, "prev_from": None, "prev_to": None, "agg": agg},
        }
