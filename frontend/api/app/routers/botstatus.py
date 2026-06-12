"""GET /api/bot/status — lightweight pill endpoint polled by the sidebar."""
from __future__ import annotations

from fastapi import APIRouter

from ..models.overview import BotStatus
from ..services import botstatus_service


router = APIRouter()


@router.get("/bot/status", response_model=BotStatus)
def bot_status() -> BotStatus:
    s, ts = botstatus_service.status()
    return BotStatus(
        status=s,
        last_activity_ist=ts,
        uptime_seconds=botstatus_service.uptime_seconds(),
        next_health_check_ist=botstatus_service.next_health_check_ist(),
        last_config_reload_ist=botstatus_service.last_config_reload_ist(),
    )
