"""GET /api/reports/insights — Strategy Insights tab."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from ..services import insights_service

router = APIRouter()


@router.get("/reports/insights")
def get_insights(
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD start (default: first of current IST month)"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD end (default: today IST)"),
) -> Dict[str, Any]:
    try:
        return insights_service.get_insights(date_from=date_from, date_to=date_to)
    except Exception:
        _meta = {"date_from": date_from, "date_to": date_to}
        return {
            "breakdowns": {},
            "key_insights": [],
            "total_n": 0,
            "min_sample": insights_service.MIN_SAMPLE,
            "note": None,
            "meta": _meta,
        }
