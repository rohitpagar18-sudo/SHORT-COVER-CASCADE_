"""GET /api/bot/status — lightweight pill endpoint polled by the sidebar."""
from __future__ import annotations

from fastapi import APIRouter

from ..models.overview import BotStatus
from ..services import botstatus_service


router = APIRouter()


@router.get("/bot/status", response_model=BotStatus)
def bot_status() -> BotStatus:
    s, ts = botstatus_service.status()
    return BotStatus(status=s, last_activity_ist=ts)
