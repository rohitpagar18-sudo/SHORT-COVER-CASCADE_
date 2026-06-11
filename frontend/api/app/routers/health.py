"""GET /api/health — liveness probe for the API itself (not the bot)."""
from __future__ import annotations

from fastapi import APIRouter

from ..paths import PROJECT_ROOT, CONFIG_PATH
from ..time_utils import fmt_ist, now_ist


router = APIRouter()


@router.get("/health")
def health():
    return {
        "ok": True,
        "now_ist": fmt_ist(now_ist()),
        "project_root": str(PROJECT_ROOT),
        "config_present": CONFIG_PATH.exists(),
    }
