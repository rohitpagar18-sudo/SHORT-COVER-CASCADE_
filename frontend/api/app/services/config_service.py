"""Read-only loader for config/config.yaml.

This phase reads but never writes config. ruamel.yaml is used in
round-trip mode so future write-back keeps comments and formatting
intact (config writes will arrive in a later phase).

Real config field shapes observed (verbatim from config.yaml):
  feeds.active_feed                -> "kite" | "upstox"
  mode.alert_mode / order_place_mode / paper_trade_mode  -> "ON"|"OFF" (yaml truthy)
  instruments.nifty_enabled / banknifty_enabled  -> ON|OFF
  instruments.nifty_lot_size / banknifty_lot_size  -> int
  position_sizing.nifty_max_lots / banknifty_max_lots / lot_cap_enabled
  circuit_breakers.max_sl_per_day / max_loss_per_day_rupees / daily_sl_count_breaker / daily_loss_breaker
  time_rules.normal_start_time / last_entry_time / soft_squareoff_time / hard_squareoff_time
  dashboard.auto_trigger_at_1535 (15:35 EOD)
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional

from ruamel.yaml import YAML

from ..paths import CONFIG_PATH


_yaml = YAML(typ="rt")
_lock = threading.Lock()
_cache: Dict[str, Any] = {"mtime": 0.0, "data": None}


def _coerce_bool(v: Any) -> Optional[bool]:
    """ruamel parses ON/OFF as True/False already; this is a safety net for
    string forms in case anyone hand-edits the file."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("on", "true", "yes", "1"):
            return True
        if s in ("off", "false", "no", "0"):
            return False
    return None


def load_config(force: bool = False) -> Dict[str, Any]:
    """Return parsed config.yaml as a plain dict. Re-reads only when the
    file mtime changes (or force=True). Returns {} if missing/unreadable."""
    path: Path = CONFIG_PATH
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if not force and _cache["data"] is not None and _cache["mtime"] == mtime:
            return _cache["data"]
        try:
            with path.open("r", encoding="utf-8") as f:
                data = _yaml.load(f)
            # ruamel returns CommentedMap; normalize to plain dict tree for JSON
            data = _to_plain(data) if data is not None else {}
        except Exception:
            data = {}
        _cache["mtime"] = mtime
        _cache["data"] = data
        return data


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


def get(path: str, default: Any = None) -> Any:
    """Dotted-path lookup, e.g. get('mode.alert_mode')."""
    cur: Any = load_config()
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def get_bool(path: str, default: bool = False) -> bool:
    val = get(path, None)
    coerced = _coerce_bool(val)
    return default if coerced is None else coerced
