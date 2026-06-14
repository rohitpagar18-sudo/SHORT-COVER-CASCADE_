"""GET /api/reports/risk — Risk Analysis tab."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from ..services import risk_service

router = APIRouter()


@router.get("/reports/risk")
def get_risk(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return risk analysis report (R-distribution, equity curve, streaks, payoff, etc)."""
    try:
        return risk_service.get_risk_report(date_from=date_from, date_to=date_to)
    except Exception:
        return {
            "r_distribution": [],
            "equity_curve": [],
            "max_drawdown": {"rupees": 0.0, "r": 0.0},
            "streaks": {"current": 0, "max_win": 0, "max_loss": 0},
            "mfe_mae": None,
            "risk_adherence": {
                "target": 3000,
                "range_min": 2500,
                "range_max": 3500,
                "within_range_pct": 0.0,
                "distribution": [],
            },
            "payoff": {"avg_win_r": 0.0, "avg_loss_r": 0.0, "ratio": None},
        }
