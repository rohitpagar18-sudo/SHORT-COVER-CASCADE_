"""Read-only loader for logs/state.json (daily counters)."""
from __future__ import annotations

import json
from typing import Any, Dict

from ..paths import STATE_JSON


def load_state() -> Dict[str, Any]:
    """Return parsed state.json or {} if file is missing/locked/malformed."""
    try:
        with STATE_JSON.open("r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        return {}
