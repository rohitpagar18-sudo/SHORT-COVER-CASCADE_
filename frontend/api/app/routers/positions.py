"""GET /api/positions/open — live read-only view of open paper episodes.

Pulls open positions from logs/paper_trades.jsonl and overlays the most
recent matching scan from logs/signals.jsonl to derive LTP / running
P&L. Never fabricates a price.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from ..services import positions_service
from ..time_utils import fmt_ist, now_ist


router = APIRouter()


@router.get("/positions/open")
def get_open_positions() -> Dict[str, Any]:
    try:
        return positions_service.open_positions()
    except Exception:
        # Defensive: never 500 on locked/partial files.
        return {"as_of": fmt_ist(now_ist()), "positions": []}
