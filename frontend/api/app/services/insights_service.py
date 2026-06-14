"""insights_service.py — Strategy-level win/loss breakdowns for the Insights tab.

Reads logs/paper_trades.jsonl (max 20k lines).
Filters: paper_role == "representative" AND decision == "TAKEN"
         AND date within the given date range.

Default date range = current IST month (start of month → today).

All file I/O wrapped in try/except — missing file / parse errors degrade
gracefully (empty lists, never a 500).
All times: IST (Asia/Kolkata).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_cls, datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ..paths import PAPER_TRADES_JSONL
from .jsonl_reader import read_jsonl

IST = ZoneInfo("Asia/Kolkata")

MIN_SAMPLE = 10

_WINNER_OUTCOMES = {"TP2_HIT", "TP1_HIT", "PARTIAL"}
_LOSER_OUTCOMES = {"SL_HIT"}

_RELATION_ORDER = ["ITM3", "ITM2", "ITM1", "ATM", "OTM1", "OTM2", "OTM3"]
_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# 30-min bucket labels: "09:00", "09:30", ..., "14:30"
_TIME_BUCKETS: List[str] = []
_h, _m = 9, 0
while (_h, _m) <= (14, 30):
    _TIME_BUCKETS.append(f"{_h:02d}:{_m:02d}")
    _m += 30
    if _m >= 60:
        _m = 0
        _h += 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ist() -> datetime:
    return datetime.now(IST)


def _today_ist() -> date_cls:
    return _now_ist().date()


def _parse_date(s: Optional[str]) -> Optional[date_cls]:
    if not s or not isinstance(s, str):
        return None
    try:
        return date_cls.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (ValueError, TypeError):
        return None


def _default_range() -> Tuple[date_cls, date_cls]:
    today = _today_ist()
    return today.replace(day=1), today


def _row_date(row: Dict[str, Any]) -> Optional[date_cls]:
    d = row.get("date")
    if isinstance(d, str):
        p = _parse_date(d)
        if p:
            return p
    ts = row.get("candle_timestamp")
    if isinstance(ts, str) and "T" in ts:
        return _parse_date(ts.split("T", 1)[0])
    return None


def _realized_r(row: Dict[str, Any]) -> float:
    v = row.get("realized_R")
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


def _pnl(row: Dict[str, Any]) -> float:
    v = row.get("paper_pnl")
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


def _is_winner(row: Dict[str, Any]) -> bool:
    return row.get("outcome") in _WINNER_OUTCOMES


def _is_loser(row: Dict[str, Any]) -> bool:
    return row.get("outcome") in _LOSER_OUTCOMES


def _time_bucket(ts: Any) -> Optional[str]:
    """Map candle_timestamp to 30-min bucket label, or None."""
    if not isinstance(ts, str) or "T" not in ts:
        return None
    try:
        time_part = ts.split("T", 1)[1][:5]  # "HH:MM"
        h, m = int(time_part[:2]), int(time_part[3:5])
        # Floor to 30-min boundary
        bucket_m = (m // 30) * 30
        return f"{h:02d}:{bucket_m:02d}"
    except (ValueError, IndexError):
        return None


def _weekday_name(ts: Any) -> Optional[str]:
    dt = _parse_dt(ts)
    if dt is None:
        return None
    idx = dt.weekday()   # 0=Mon..4=Fri
    if 0 <= idx <= 4:
        return _WEEKDAY_NAMES[idx]
    return None


# ---------------------------------------------------------------------------
# Breakdown builder
# ---------------------------------------------------------------------------

def _build_breakdown(groups: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Given groups keyed by label, produce breakdown rows sorted by key."""
    result = []
    for key, rows in groups.items():
        n = len(rows)
        wins = sum(1 for r in rows if _is_winner(r))
        win_rate = round(wins / n * 100.0, 1) if n else 0.0
        avg_r = round(sum(_realized_r(r) for r in rows) / n, 3) if n else 0.0
        total_pnl = round(sum(_pnl(r) for r in rows), 2)
        result.append({
            "key": key,
            "n": n,
            "win_rate": win_rate,
            "avg_r": avg_r,
            "total_pnl": total_pnl,
        })
    return result


# ---------------------------------------------------------------------------
# Load + filter rows
# ---------------------------------------------------------------------------

def _load_filtered(df: date_cls, dt: date_cls) -> List[Dict[str, Any]]:
    try:
        rows = read_jsonl(PAPER_TRADES_JSONL, max_lines=20_000)
    except Exception:
        return []
    out = []
    for r in rows:
        if r.get("paper_role") != "representative":
            continue
        if r.get("decision") != "TAKEN":
            continue
        d = _row_date(r)
        if d is None or not (df <= d <= dt):
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Key insights (rule-based)
# ---------------------------------------------------------------------------

def _key_insights(
    by_relation: List[Dict[str, Any]],
    by_weekday: List[Dict[str, Any]],
    by_time_of_day: List[Dict[str, Any]],
    by_option_type: List[Dict[str, Any]],
) -> List[str]:
    insights: List[str] = []

    # Best relation by win_rate (n >= MIN_SAMPLE)
    eligible = [r for r in by_relation if r["n"] >= MIN_SAMPLE]
    if eligible:
        best = max(eligible, key=lambda r: r["win_rate"])
        insights.append(
            f"Best strike depth by win rate: {best['key']} "
            f"({best['win_rate']:.1f}% win rate, n={best['n']})"
        )

    # Best weekday by avg_r (n >= MIN_SAMPLE)
    eligible = [r for r in by_weekday if r["n"] >= MIN_SAMPLE]
    if eligible:
        best = max(eligible, key=lambda r: r["avg_r"])
        insights.append(
            f"Best weekday by avg R: {best['key']} "
            f"({best['avg_r']:+.2f}R, n={best['n']})"
        )

    # Best time bucket by win_rate (n >= MIN_SAMPLE)
    eligible = [r for r in by_time_of_day if r["n"] >= MIN_SAMPLE]
    if eligible:
        best = max(eligible, key=lambda r: r["win_rate"])
        insights.append(
            f"Best entry time by win rate: {best['key']} "
            f"({best['win_rate']:.1f}% win rate, n={best['n']})"
        )

    # Best option_type by win_rate (n >= MIN_SAMPLE)
    eligible = [r for r in by_option_type if r["n"] >= MIN_SAMPLE]
    if eligible:
        best = max(eligible, key=lambda r: r["win_rate"])
        insights.append(
            f"Best option type by win rate: {best['key']} "
            f"({best['win_rate']:.1f}% win rate, n={best['n']})"
        )

    return insights


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_insights(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the full Insights payload."""
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df is None and dt is None:
        df, dt = _default_range()
    elif df is None:
        df = dt
    elif dt is None:
        dt = df

    # Satisfy type checker — both are set at this point
    assert df is not None and dt is not None

    rows = _load_filtered(df, dt)
    total_n = len(rows)

    # --- by_time_of_day ---
    tod_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        bk = _time_bucket(r.get("candle_timestamp"))
        if bk is not None:
            tod_groups[bk].append(r)
    tod_list = _build_breakdown(tod_groups)
    # Sort by bucket label ascending (string compare works for HH:MM)
    tod_list.sort(key=lambda x: x["key"])

    # --- by_weekday ---
    wd_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        wdn = _weekday_name(r.get("candle_timestamp"))
        if wdn is not None:
            wd_groups[wdn].append(r)
    wd_list_raw = _build_breakdown(wd_groups)
    # Sort Mon..Fri
    wd_order = {n: i for i, n in enumerate(_WEEKDAY_NAMES)}
    wd_list = sorted(wd_list_raw, key=lambda x: wd_order.get(x["key"], 99))

    # --- by_symbol ---
    sym_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sym = (r.get("symbol") or "UNKNOWN").upper()
        sym_groups[sym].append(r)
    sym_list = sorted(_build_breakdown(sym_groups), key=lambda x: x["key"])

    # --- by_relation ---
    rel_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        rel = (r.get("relation") or "").upper()
        if rel:
            rel_groups[rel].append(r)
    rel_list_raw = _build_breakdown(rel_groups)
    rel_order = {k: i for i, k in enumerate(_RELATION_ORDER)}
    rel_list = sorted(rel_list_raw, key=lambda x: rel_order.get(x["key"], 99))

    # --- by_option_type ---
    ot_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        ot = (r.get("option_type") or "").upper()
        if ot:
            ot_groups[ot].append(r)
    ot_list = sorted(_build_breakdown(ot_groups), key=lambda x: x["key"])

    # --- by_day_type ---
    has_expiry_data = any(r.get("is_expiry_day") is not None for r in rows)
    breakdowns: Dict[str, Any] = {
        "by_time_of_day": tod_list,
        "by_weekday": wd_list,
        "by_symbol": sym_list,
        "by_relation": rel_list,
        "by_option_type": ot_list,
    }
    if has_expiry_data:
        dt_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            ied = r.get("is_expiry_day")
            if ied is None:
                continue
            label = "Expiry" if bool(ied) else "Normal"
            dt_groups[label].append(r)
        breakdowns["by_day_type"] = sorted(_build_breakdown(dt_groups), key=lambda x: x["key"])

    # --- key_insights ---
    key_insights = _key_insights(rel_list, wd_list, tod_list, ot_list)

    # --- note ---
    note: Optional[str] = None
    if 0 < total_n < MIN_SAMPLE:
        note = (
            f"Not enough data to generate insights — "
            f"{total_n} trade(s) in range, minimum {MIN_SAMPLE} required."
        )

    return {
        "breakdowns": breakdowns,
        "key_insights": key_insights,
        "total_n": total_n,
        "min_sample": MIN_SAMPLE,
        "note": note,
        "meta": {
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
        },
    }
