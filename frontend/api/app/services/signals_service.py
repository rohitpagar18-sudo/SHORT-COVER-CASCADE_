"""Read-only services over signals.jsonl + alerts.jsonl.

Field names observed (real lines, 2026-05-27 / 2026-06 samples):
  signals.jsonl   timestamp_ist, event_type ("scan"|"rejection"|"would_alert_extended"|"alert"),
                  symbol, strike, relation, option_type, expiry, trading_symbol,
                  conditions_passed[], conditions_failed[], all_passed, summary,
                  reasons{C0..C4}, opt_above_vwap_pct, spot_price, spot_vwap,
                  option_close, option_vwap, rsi, rsi_ma, oi, oi_ma, volume,
                  volume_ma, is_green, vix, vix_regime
  alerts.jsonl    same + entry, sl, sl_method, tp1, tp2, tp1_r, tp2_r,
                  risk_per_unit, lots, total_risk, lot_size, time, date,
                  day_type, vix_multiplier, spot, spot_position,
                  bot_remark, bot_tags, telegram_short_remark
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..paths import SIGNALS_JSONL, ALERTS_JSONL
from ..time_utils import today_ist
from .jsonl_reader import read_jsonl, filter_by_date


def all_signals(max_lines: int = 2000) -> List[Dict[str, Any]]:
    return read_jsonl(SIGNALS_JSONL, max_lines=max_lines)


def all_alerts(max_lines: int = 2000) -> List[Dict[str, Any]]:
    return read_jsonl(ALERTS_JSONL, max_lines=max_lines)


def alerts_on_date(date_iso: str) -> List[Dict[str, Any]]:
    return filter_by_date(all_alerts(), date_iso, "timestamp_ist")


def alerts_today() -> List[Dict[str, Any]]:
    return alerts_on_date(today_ist().isoformat())


def signals_on_date(date_iso: str) -> List[Dict[str, Any]]:
    """Today's scan/alert events from signals.jsonl whose all_passed is True."""
    return [
        r for r in all_signals()
        if isinstance(r.get("timestamp_ist"), str)
        and r["timestamp_ist"].startswith(date_iso)
        and r.get("event_type") in ("scan", "alert")
        and r.get("all_passed") is True
    ]


def signals_today() -> List[Dict[str, Any]]:
    return signals_on_date(today_ist().isoformat())


def all_condition_names(rows: List[Dict[str, Any]]) -> List[str]:
    """Union of condition names that appear in conditions_passed/failed."""
    names: List[str] = []
    seen = set()
    for r in rows:
        for k in ("conditions_passed", "conditions_failed"):
            v = r.get(k)
            if isinstance(v, list):
                for n in v:
                    if isinstance(n, str) and n not in seen:
                        seen.add(n)
                        names.append(n)
    # Sort C0..Cn naturally
    return sorted(names, key=lambda s: (s[0], int(s[1:]) if s[1:].isdigit() else 0))


def recent_alerts_on_date(date_iso: str, n: int = 5) -> List[Dict[str, Any]]:
    """Last N alerts on date, newest first, projected to a compact UI shape
    with per-condition pass/fail flags derived from the REAL signals.jsonl
    field names (conditions_passed[] + conditions_failed[]).
    """
    rows = [r for r in all_alerts() if isinstance(r.get("timestamp_ist"), str)
            and r["timestamp_ist"].startswith(date_iso)]
    rows = rows[-n:]
    rows.reverse()
    cond_names = all_condition_names(rows) or _legacy_condition_names()
    out: List[Dict[str, Any]] = []
    for r in rows:
        passed = set(r.get("conditions_passed") or [])
        failed = set(r.get("conditions_failed") or [])
        flags = [{"name": c, "passed": c in passed} for c in cond_names
                 if c in passed or c in failed]
        # Fall back: if neither passed/failed list mentions a name, omit it
        # rather than guessing.
        if not flags:
            flags = [{"name": c, "passed": True} for c in (r.get("conditions_passed") or [])]
        notes = ""
        if failed:
            notes = "Failed: " + ", ".join(sorted(failed))
        out.append({
            "time": r.get("time") or _hhmm(r.get("timestamp_ist")),
            "timestamp_ist": r.get("timestamp_ist"),
            "symbol": r.get("symbol"),
            "strike": r.get("strike"),
            "option_type": r.get("option_type"),
            "relation": r.get("relation"),
            "conditions": flags,
            "conditions_passed_count": len(passed),
            "conditions_total": len(flags) if flags else len(cond_names),
            "status": "ALERT" if r.get("all_passed") else "PARTIAL",
            "risk": r.get("total_risk"),
            "entry": r.get("entry"),
            "lots": r.get("lots"),
            "notes": notes or r.get("telegram_short_remark") or r.get("bot_remark") or "",
        })
    return out


def recent_alerts(n: int = 5) -> List[Dict[str, Any]]:
    return recent_alerts_on_date(today_ist().isoformat(), n)


def condition_summary_on_date(date_iso: str) -> Dict[str, Any]:
    """Bucket today's scan/alert events by conditions-passed count.
    Returns {total_scans, buckets:[{label,count,pct}]} with labels
    "5/5","4/5","3/5","2/5","1/5". 0/5 is intentionally omitted to match
    the reference UI.
    """
    # Pull ALL scan/alert events on this date (regardless of all_passed)
    rows = [
        r for r in all_signals()
        if isinstance(r.get("timestamp_ist"), str)
        and r["timestamp_ist"].startswith(date_iso)
        and r.get("event_type") in ("scan", "alert")
    ]
    # Total condition slots = max length seen in either passed+failed
    total_slots = 0
    for r in rows:
        l = len(r.get("conditions_passed") or []) + len(r.get("conditions_failed") or [])
        if l > total_slots:
            total_slots = l
    total_slots = total_slots or 5  # fallback

    counts: Dict[int, int] = {i: 0 for i in range(1, total_slots + 1)}
    total_scans = 0
    for r in rows:
        passed = len(r.get("conditions_passed") or [])
        if passed >= 1:
            counts[passed] = counts.get(passed, 0) + 1
            total_scans += 1
    buckets: List[Dict[str, Any]] = []
    for k in range(total_slots, 0, -1):
        c = counts.get(k, 0)
        buckets.append({
            "label": f"{k}/{total_slots}",
            "count": c,
            "pct": round((c / total_scans * 100) if total_scans else 0.0, 1),
        })
    return {"total_scans": total_scans, "buckets": buckets}


def condition_summary_today() -> Dict[str, Any]:
    return condition_summary_on_date(today_ist().isoformat())


def _legacy_condition_names() -> List[str]:
    """Fallback names used only when no rows are available. The router will
    overwrite this with the real names from the JSONL whenever any data
    exists.
    """
    return ["C0", "C1", "C2", "C3", "C4"]


def _hhmm(ts: Any) -> str:
    if not isinstance(ts, str) or "T" not in ts:
        return ""
    try:
        return ts.split("T", 1)[1][:5]
    except Exception:
        return ""
