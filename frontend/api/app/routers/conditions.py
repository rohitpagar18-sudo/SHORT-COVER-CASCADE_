"""GET /api/reports/conditions — Condition Analysis tab."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from ..services import conditions_service

router = APIRouter()


@router.get("/reports/conditions")
def get_conditions(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return condition analysis report (pass rates, funnel, bottleneck, C5 shadow, DI alignment)."""
    try:
        return conditions_service.get_conditions_report(date_from=date_from, date_to=date_to)
    except Exception:
        return {
            "pass_rates": [],
            "funnel": [],
            "bottleneck": [],
            "c5_shadow": {
                "alerts_total": 0,
                "c5_passed": 0,
                "c5_failed": 0,
                "c5_pass_rate": 0.0,
                "when_c5_passed": {"n": 0, "win_rate": 0.0, "avg_r": 0.0},
                "when_c5_failed": {"n": 0, "win_rate": 0.0, "avg_r": 0.0},
            },
            "di_alignment": None,
        }
