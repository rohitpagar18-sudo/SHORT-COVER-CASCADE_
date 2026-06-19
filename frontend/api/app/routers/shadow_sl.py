"""GET /api/shadow-sl — read-only view over logs/shadow_sl.jsonl.

The shadow lab is experimental: it never affects real or paper P&L.
This endpoint exposes the per-method comparison + the per-day pivoted
trade list rendered by the Stop-Loss Lab page. All file I/O is wrapped
in try/except — failures degrade to an empty payload, never a 500.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from ..services import shadow_sl_service

router = APIRouter()


@router.get("/shadow-sl")
def shadow_sl(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    try:
        return shadow_sl_service.get_shadow_sl(date_from=date_from, date_to=date_to)
    except Exception:
        return {
            "date_from": date_from,
            "date_to": date_to,
            "methods": [],
            "days": [],
        }
