"""Read-only services over signals.jsonl + alerts.jsonl.

Field names observed (real lines, 2026-05-27 sample):
  signals.jsonl   timestamp_ist, event_type ("scan"|"rejection"|"would_alert_extended"),
                  symbol, strike, relation, option_type, expiry, trading_symbol,
                  conditions_passed[], conditions_failed[], all_passed, summary
  alerts.jsonl    same + entry, sl, tp1, tp2, lots, total_risk, bot_remark,
                  telegram_short_remark, day_type, vix_regime
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..paths import SIGNALS_JSONL, ALERTS_JSONL
from ..time_utils import today_ist
from .jsonl_reader import read_jsonl, filter_by_date


def all_signals(max_lines: int = 1000) -> List[Dict[str, Any]]:
    return read_jsonl(SIGNALS_JSONL, max_lines=max_lines)


def all_alerts(max_lines: int = 1000) -> List[Dict[str, Any]]:
    return read_jsonl(ALERTS_JSONL, max_lines=max_lines)


def alerts_today() -> List[Dict[str, Any]]:
    return filter_by_date(all_alerts(), today_ist().isoformat(), "timestamp_ist")


def signals_today() -> List[Dict[str, Any]]:
    """Today's scan/alert events from signals.jsonl (not rejections)."""
    today = today_ist().isoformat()
    return [
        r for r in all_signals()
        if isinstance(r.get("timestamp_ist"), str)
        and r["timestamp_ist"].startswith(today)
        and r.get("event_type") in ("scan", "alert")
        and r.get("all_passed") is True
    ]


def recent_alerts(n: int = 5) -> List[Dict[str, Any]]:
    """Last N alerts from alerts.jsonl, newest first, projected to a
    compact UI shape."""
    rows = all_alerts(max_lines=max(50, n * 4))
    rows = rows[-n:]
    rows.reverse()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "time": r.get("time") or _hhmm(r.get("timestamp_ist")),
            "timestamp_ist": r.get("timestamp_ist"),
            "symbol": r.get("symbol"),
            "strike": r.get("strike"),
            "option_type": r.get("option_type"),
            "relation": r.get("relation"),
            "conditions_passed": r.get("conditions_passed") or [],
            "status": "ALERT" if r.get("all_passed") else "PARTIAL",
            "risk": r.get("total_risk"),
            "entry": r.get("entry"),
            "lots": r.get("lots"),
        })
    return out


def _hhmm(ts: Any) -> str:
    if not isinstance(ts, str) or "T" not in ts:
        return ""
    try:
        return ts.split("T", 1)[1][:5]
    except Exception:
        return ""
