"""GET /api/paper/today, /api/paper/episodes, /api/paper/overrides.

All reads are wrapped in try/except — locked/partial files degrade to
empty payloads, never 500. No writes; no broker calls.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from ..paths import PAPER_TRADES_JSONL, PAPER_OVERRIDES_CSV
from ..services import paper_service, config_service
from ..services.jsonl_reader import read_jsonl
from ..time_utils import today_ist

router = APIRouter()


def _as_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# GET /api/paper/today
# ---------------------------------------------------------------------------

@router.get("/paper/today")
def paper_today() -> Dict[str, Any]:
    config_service.load_config()
    try:
        tp = paper_service.get_trade_plan_dict()
    except Exception:
        tp = {
            "max_trades_per_day": 0, "trades_taken": 0, "trades_remaining": 0,
            "daily_sl_hit": 0, "max_sl_per_day": 0, "cooldown_active": False,
            "same_strike_sl_count": 0,
        }
    try:
        rs = paper_service.get_reentry_status_dict()
    except Exception:
        rs = {
            "cooldown_minutes": 0, "minutes_since_last_sl": None,
            "same_strike_kill_enabled": False, "strikes_locked_today": [],
        }
    return {"selection": tp, "reentry": rs}


# ---------------------------------------------------------------------------
# GET /api/paper/episodes
# ---------------------------------------------------------------------------

@router.get("/paper/episodes")
def paper_episodes(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),   # "TAKEN" | "SKIPPED" | null → All
    symbol: Optional[str] = Query(default=None),
    option_type: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    today_iso = today_ist().isoformat()
    df = date_from or today_iso
    dt = date_to or today_iso

    # Load overrides for is_overridden check
    overridden_ids: set = set()
    try:
        if PAPER_OVERRIDES_CSV.exists():
            with PAPER_OVERRIDES_CSV.open("r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    aid = (row.get("alert_id") or "").strip()
                    # A row with any manual field set counts as an override
                    has_override = any(
                        (row.get(col) or "").strip()
                        for col in ("manual_decision", "manual_outcome", "manual_exit")
                    )
                    if aid and has_override:
                        overridden_ids.add(aid)
    except Exception:
        pass

    # Load paper trades
    try:
        rows = read_jsonl(PAPER_TRADES_JSONL, max_lines=5000)
    except Exception:
        rows = []

    # Filter by date range
    filtered = [
        r for r in rows
        if isinstance(r.get("date"), str) and df <= r["date"] <= dt
    ]

    # Apply optional filters
    if symbol:
        filtered = [r for r in filtered if r.get("symbol") == symbol.upper()]
    if option_type:
        filtered = [r for r in filtered if r.get("option_type") == option_type.upper()]
    if status:
        filtered = [r for r in filtered if r.get("decision") == status.upper()]

    # Group by episode_id
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in filtered:
        eid = r.get("episode_id") or r.get("alert_id") or ""
        groups[eid].append(r)

    episodes = []
    for eid, group in groups.items():
        # Representative row first, then echoes
        rep_rows = [r for r in group if r.get("paper_role") == "representative"]
        echo_rows = [r for r in group if r.get("paper_role") != "representative"]

        # Fall back: if no representative tag, use earliest by candle_timestamp
        if not rep_rows:
            sorted_group = sorted(group, key=lambda r: r.get("candle_timestamp") or "")
            rep_rows = sorted_group[:1]
            echo_rows = sorted_group[1:]

        rep = rep_rows[0] if rep_rows else group[0]

        echoes = [
            {
                "time": e.get("candle_timestamp"),
                "relation": e.get("relation"),
                "price": e.get("entry"),
            }
            for e in echo_rows
        ]

        # Time from candle_timestamp (HH:MM)
        ts = rep.get("candle_timestamp") or ""
        time_str = ts[11:16] if len(ts) >= 16 else None

        # R-metrics: only include if truly present and non-zero or meaningful
        mfe_r = rep.get("mfe_R")
        mae_r = rep.get("mae_R")
        max_dd_r = rep.get("max_drawdown_R")

        episodes.append({
            "episode_id": eid or None,
            "date": rep.get("date"),
            "time": time_str,
            "symbol": rep.get("symbol"),
            "option_type": rep.get("option_type"),
            "strike": rep.get("strike"),
            "relation": rep.get("relation"),
            "selection": rep.get("decision"),
            "skip_reason": rep.get("decision_reason") if rep.get("decision") == "SKIPPED" else None,
            "entry_price": rep.get("entry"),
            "sl": rep.get("sl"),
            "tp1": rep.get("tp1"),
            "tp2": rep.get("tp2"),
            "qty_lots": rep.get("lots"),
            "outcome": rep.get("outcome"),
            "r_multiple": rep.get("realized_R"),
            "paper_pnl": rep.get("paper_pnl"),
            "mfe_r": mfe_r if isinstance(mfe_r, (int, float)) else None,
            "mae_r": mae_r if isinstance(mae_r, (int, float)) else None,
            "max_drawdown_r": max_dd_r if isinstance(max_dd_r, (int, float)) else None,
            "echo_count": len(echo_rows),
            "echoes": echoes,
            "is_overridden": (rep.get("alert_id") or "") in overridden_ids,
        })

    # Sort by date desc, then time desc
    episodes.sort(key=lambda e: (e.get("date") or "", e.get("time") or ""), reverse=True)
    return {"episodes": episodes}


# ---------------------------------------------------------------------------
# GET /api/paper/overrides
# ---------------------------------------------------------------------------

@router.get("/paper/overrides")
def paper_overrides() -> Dict[str, Any]:
    try:
        if not PAPER_OVERRIDES_CSV.exists():
            return {"rows": [], "columns": []}
        with PAPER_OVERRIDES_CSV.open("r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        reader = csv.DictReader(io.StringIO(content))
        columns = reader.fieldnames or []
        rows = [dict(row) for row in reader]
        return {"rows": rows, "columns": list(columns)}
    except Exception:
        return {"rows": [], "columns": []}
