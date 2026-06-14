"""GET /api/reports/monthly — Monthly Summary tab."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from ..services import monthly_service

router = APIRouter()


@router.get("/reports/monthly")
def get_monthly(
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD start (default: first of current IST month)"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD end (default: today IST)"),
) -> Dict[str, Any]:
    try:
        return monthly_service.get_monthly(date_from=date_from, date_to=date_to)
    except Exception:
        _meta = {"date_from": date_from, "date_to": date_to}
        return {
            "months": [],
            "calendar": [],
            "meta": _meta,
        }
