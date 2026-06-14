"""GET /api/logs/files, GET /api/logs/tail — read-only log viewer.

The `file` query is validated against `logs_service.ALLOWED_FILES`. Any
other value is rejected with 422 — we never tail arbitrary paths.

Both endpoints wrap reads in try/except. Missing or locked files degrade
to empty payloads, never 500.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from ..services import logs_service


router = APIRouter()


@router.get("/logs/files")
def list_log_files() -> Dict[str, List[Dict[str, Any]]]:
    """Stat each allowlisted log file. Missing files have null mtime/size."""
    try:
        files = logs_service.list_files()
    except Exception:
        files = []
    return {"files": files}


@router.get("/logs/tail")
def tail_log_file(
    file: str = Query(..., description="One of the allowlisted log files."),
    lines: int = Query(200, ge=1, le=2000),
    level: str = Query("all"),
    search: str = Query("", description="Free-text filter (case-insensitive)."),
) -> Dict[str, Any]:
    if file not in logs_service.ALLOWED_FILES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_file",
                "allowed": sorted(logs_service.ALLOWED_FILES.keys()),
            },
        )
    try:
        return logs_service.tail(
            file_name=file,
            lines=lines,
            level=level,
            search=search,
        )
    except Exception:
        return {
            "file": file,
            "type": "error",
            "rows": [],
            "filtered_count": 0,
            "total_read": 0,
        }
