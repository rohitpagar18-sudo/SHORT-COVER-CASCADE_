"""GET /api/system/health — System Health tab (shared with F8 Bot Status)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from ..services import health_service

router = APIRouter()


@router.get("/system/health")
def get_system_health() -> Dict[str, Any]:
    try:
        return health_service.get_health()
    except Exception:
        return {
            "feed": {"active_feed": None, "status": "disconnected"},
            "bot": {"status": "STOPPED", "last_activity_ist": None, "uptime_seconds": None},
            "scan_cadence": {
                "expected_interval_min": 5,
                "recent_gaps": [],
                "healthy": True,
                "note": None,
            },
            "files": [],
            "data_issues": {"count": 0, "recent": []},
            "last_config_reload_ist": None,
            "last_dashboard_sync_ist": None,
        }
