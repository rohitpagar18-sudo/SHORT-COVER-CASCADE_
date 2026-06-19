"""Read-only service over ``logs/shadow_sl.jsonl``.

Produces the payload for ``GET /api/shadow-sl``: a per-method summary
table and a per-day list of trades with each method's outcome pivoted
side-by-side. The shadow JSONL is written ONLY by
``scripts/update_shadow_sl.py``; this service never touches it.

All file I/O is wrapped in try/except — a missing or partially-written
file degrades to an empty payload, never a 500.

All times are IST (Asia/Kolkata).
"""
from __future__ import annotations

import math
import statistics
from collections import OrderedDict, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ..paths import SHADOW_SL_JSONL
from ..time_utils import today_ist
from .jsonl_reader import read_jsonl


# Lower bound on max_unrealized_r for a row to count toward
# "capture efficiency" (median r_multiple of trades that had a real
# move). Lifted out as a constant so the UI/footer can stay in sync.
CAPTURE_EFFICIENCY_MIN_R = 1.5


# Trade-level key: identifies a single (alert × per-method-fanout) row,
# whose `method` field is then pivoted into the per_method dict.
def _trade_key(row: Dict[str, Any]) -> Tuple[str, str, int, str]:
    return (
        str(row.get("entry_time") or ""),
        str(row.get("symbol") or ""),
        int(row.get("strike") or 0),
        str(row.get("option_type") or ""),
    )


def _classify_outcome(reason: str | None) -> str:
    """Bucket the exit_reason into a coarse outcome (for win-rate / counts)."""
    r = (reason or "").upper()
    if "TP2_HIT" in r:
        return "TP2_HIT"
    if "TP1" in r and "HARD_EXIT" in r:
        return "PARTIAL"
    if "TP1" in r and "SL" in r:
        return "PARTIAL"
    if "HARD_EXIT" in r:
        return "HARD_EXIT"
    if "TIME_STOP" in r:
        return "TIME_STOP"
    if "SL_HIT" in r:
        return "SL_HIT"
    if "EOD_FLAT" in r:
        return "EOD_FLAT"
    if "NO_DATA" in r:
        return "NO_DATA"
    return "OTHER"


def _is_win(reason: str | None, r_multiple: Any) -> bool:
    """A win is r_multiple > 0 (any positive close). Used for the table."""
    try:
        return float(r_multiple) > 0
    except (TypeError, ValueError):
        return False


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _empty_payload() -> Dict[str, Any]:
    return {
        "date_from": None,
        "date_to": None,
        "methods": [],
        "days": [],
    }


def get_shadow_sl(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the API payload.

    Defaults date_from = date_to = today (IST). Reads the entire
    ``shadow_sl.jsonl`` then filters by ``date`` field. Skipping
    malformed rows is the reader's job.
    """
    today_iso = today_ist().isoformat()
    df = (date_from or today_iso).strip()
    dt = (date_to or today_iso).strip()
    # Guard against accidental inversion.
    if df > dt:
        df, dt = dt, df

    try:
        rows = read_jsonl(SHADOW_SL_JSONL, max_lines=20000)
    except Exception:
        rows = []

    # Filter to the requested window.
    rows = [
        r for r in rows
        if isinstance(r.get("date"), str) and df <= r["date"] <= dt
    ]

    if not rows:
        return {"date_from": df, "date_to": dt, "methods": [], "days": []}

    # ---- Per-method summary ----
    by_method: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        m = str(r.get("method") or "").strip()
        if not m:
            continue
        by_method[m].append(r)

    methods_summary: List[Dict[str, Any]] = []
    for method_name, method_rows in by_method.items():
        r_values: List[float] = []
        time_stop_exits = 0
        capture_pool: List[float] = []
        for mr in method_rows:
            rm = _safe_float(mr.get("r_multiple"))
            if rm is not None:
                r_values.append(rm)
            if _classify_outcome(mr.get("exit_reason")) == "TIME_STOP":
                time_stop_exits += 1
            mu = _safe_float(mr.get("max_unrealized_r"))
            if mu is not None and mu >= CAPTURE_EFFICIENCY_MIN_R and rm is not None:
                capture_pool.append(rm)

        trades = len(method_rows)
        wins = sum(1 for v in r_values if v > 0)
        total_r = sum(r_values) if r_values else 0.0
        avg_r = (total_r / len(r_values)) if r_values else 0.0
        win_rate = (wins / trades * 100.0) if trades else 0.0
        capture_efficiency = (
            statistics.median(capture_pool) if capture_pool else None
        )
        methods_summary.append({
            "method": method_name,
            "trades": trades,
            "win_rate": round(win_rate, 1),
            "total_r": round(total_r, 3),
            "avg_r": round(avg_r, 3),
            "capture_efficiency": (
                round(capture_efficiency, 3) if capture_efficiency is not None else None
            ),
            "time_stop_exits": time_stop_exits,
        })
    # Stable order for the UI: by method name asc.
    methods_summary.sort(key=lambda m: m["method"])

    # ---- Days × trades pivot ----
    # Group first by date, then by trade key, pivoting per_method.
    days_map: "OrderedDict[str, Dict[Tuple[str, str, int, str], Dict[str, Any]]]" = OrderedDict()
    for r in rows:
        date_str = str(r.get("date") or "")
        if not date_str:
            continue
        day_bucket = days_map.setdefault(date_str, {})
        key = _trade_key(r)
        trade_entry = day_bucket.get(key)
        if trade_entry is None:
            trade_entry = {
                "entry_time": r.get("entry_time"),
                "symbol": r.get("symbol"),
                "strike": r.get("strike"),
                "option_type": r.get("option_type"),
                "relation": r.get("relation"),
                "is_expiry": bool(r.get("is_expiry")),
                "per_method": {},
            }
            day_bucket[key] = trade_entry
        method_name = str(r.get("method") or "").strip()
        if not method_name:
            continue
        trade_entry["per_method"][method_name] = {
            "exit_price": _safe_float(r.get("exit_price")),
            "exit_time": r.get("exit_time"),
            "exit_reason": r.get("exit_reason"),
            "r_multiple": _safe_float(r.get("r_multiple")),
            "max_unrealized_r": _safe_float(r.get("max_unrealized_r")),
            "gave_back_r": _safe_float(r.get("gave_back_r")),
            "initial_sl": _safe_float(r.get("initial_sl")),
            "tp1": _safe_float(r.get("tp1")),
            "tp2": _safe_float(r.get("tp2")),
            "entry": _safe_float(r.get("entry")),
            "outcome_bucket": _classify_outcome(r.get("exit_reason")),
            "win": _is_win(r.get("exit_reason"), r.get("r_multiple")),
        }

    days_list: List[Dict[str, Any]] = []
    for date_str, day_bucket in days_map.items():
        trades_list = list(day_bucket.values())
        # Sort trades within the day by entry_time.
        trades_list.sort(key=lambda t: (t.get("entry_time") or ""))
        days_list.append({"date": date_str, "trades": trades_list})
    # Sort days desc — newest first matches the dashboard convention.
    days_list.sort(key=lambda d: d["date"], reverse=True)

    return {
        "date_from": df,
        "date_to": dt,
        "methods": methods_summary,
        "days": days_list,
    }
