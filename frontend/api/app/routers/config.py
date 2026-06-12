"""GET /api/config + PUT /api/config — read and write config.yaml."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from ..services.config_write_service import _WRITE_LOCK, safe_write, get_config_json

router = APIRouter()


@router.get("/config")
def get_config() -> Dict[str, Any]:
    """Return full config.yaml as a plain JSON dict."""
    try:
        return get_config_json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
async def put_config(request: Request) -> Dict[str, Any]:
    """Apply a partial nested change dict to config.yaml atomically.

    Body: any nested subset of config.yaml keys with their new values.
    Returns: {ok, updated, restart_required: [dotted.key,...], message}
    """
    try:
        changes: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    if not isinstance(changes, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object.")

    with _WRITE_LOCK:
        try:
            result = safe_write(changes)
        except ValueError as e:
            # Validation errors — do NOT write the file
            raise HTTPException(status_code=422, detail={"errors": list(e.args[0])})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Write failed: {e}")

    return result
