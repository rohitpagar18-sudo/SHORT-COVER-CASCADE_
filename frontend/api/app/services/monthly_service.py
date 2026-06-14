"""monthly_service.py — Monthly summary and per-day calendar for the Monthly Summary tab.

Reads logs/paper_trades.jsonl (max 20k lines).
Filters: paper_role == "representative" AND decision == "TAKEN".

`months` = ALL-TIME aggregation (ignores date range), newest-first.
`calendar` = filtered to date_from..date_to, per-day rows sorted date asc.

All file I/O wrapped in try/except. Missing file = empty result, never 500.
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

_WINNER_OUTCOMES = {"TP2_HIT", "TP1_HIT", "PARTIAL"}
_LOSER_OUTCOMES = {"SL_HIT"}


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


def _pnl(row: Dict[str, Any]) -> float:
    v = row.get("paper_pnl")
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


def _is_finalized(row: Dict[str, Any]) -> bool:
    return row.get("outcome") not in (None, "NO_DATA")


def _is_open(row: Dict[str, Any]) -> bool:
    return row.get("outcome") == "NO_DATA"


def _is_representative_taken(row: Dict[str, Any]) -> bool:
    return (
        row.get("paper_role") == "representative"
        and row.get("decision") == "TAKEN"
    )


# ---------------------------------------------------------------------------
# Load rows
# ---------------------------------------------------------------------------

def _load_rows() -> List[Dict[str, Any]]:
    try:
        return read_jsonl(PAPER_TRADES_JSONL, max_lines=20_000)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Months builder (ALL-TIME, ignores date range)
# ---------------------------------------------------------------------------

def _build_months(all_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rep_taken = [r for r in all_rows if _is_representative_taken(r)]

    by_month: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rep_taken:
        d = _row_date(r)
        if d is not None:
            by_month[d.strftime("%Y-%m")].append(r)

    result: List[Dict[str, Any]] = []
    for month_key in sorted(by_month.keys(), reverse=True):
        rows = by_month[month_key]
        finalized = [r for r in rows if _is_finalized(r)]
        open_rows = [r for r in rows if _is_open(r)]

        total_trades = len(rows)  # all TAKEN reps, including open/running
        winners = [r for r in finalized if r.get("outcome") in _WINNER_OUTCOMES]
        losers = [r for r in finalized if r.get("outcome") in _LOSER_OUTCOMES]

        n_finalized = len(finalized)
        win_rate = round(len(winners) / n_finalized * 100.0, 1) if n_finalized else 0.0
        realized_pnl = round(sum(_pnl(r) for r in finalized), 2)
        unrealized_pnl = round(sum(_pnl(r) for r in open_rows), 2)
        total_pnl = round(realized_pnl + unrealized_pnl, 2)

        gross_profit = sum(_pnl(r) for r in winners if _pnl(r) > 0)
        gross_loss = sum(abs(_pnl(r)) for r in losers if _pnl(r) < 0)
        profit_factor: Optional[float] = (
            round(gross_profit / gross_loss, 3) if gross_loss > 0 else None
        )

        # Per-day aggregation for max_profit / max_loss / best_day / worst_day
        daily_pnl: Dict[str, float] = defaultdict(float)
        for r in finalized:
            d = _row_date(r)
            if d:
                daily_pnl[d.isoformat()] += _pnl(r)

        max_profit = round(max(daily_pnl.values(), default=0.0), 2)
        max_loss = round(min(daily_pnl.values(), default=0.0), 2)

        best_day: Optional[Dict[str, Any]] = None
        worst_day: Optional[Dict[str, Any]] = None
        if daily_pnl:
            best_date = max(daily_pnl, key=lambda d: daily_pnl[d])
            worst_date = min(daily_pnl, key=lambda d: daily_pnl[d])
            best_day = {"date": best_date, "pnl": round(daily_pnl[best_date], 2)}
            worst_day = {"date": worst_date, "pnl": round(daily_pnl[worst_date], 2)}

        # Month display label: "May 2026"
        try:
            d0 = date_cls.fromisoformat(month_key + "-01")
            month_display = d0.strftime("%B %Y")  # e.g. "May 2026"
        except ValueError:
            month_display = month_key

        result.append({
            "month": month_display,
            "month_key": month_key,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "profit_factor": profit_factor,
            "max_profit": max_profit,
            "max_loss": max_loss,
            "best_day": best_day,
            "worst_day": worst_day,
        })

    return result


# ---------------------------------------------------------------------------
# Calendar builder (filtered to date range)
# ---------------------------------------------------------------------------

def _build_calendar(all_rows: List[Dict[str, Any]], df: date_cls, dt: date_cls) -> List[Dict[str, Any]]:
    rep_taken = [r for r in all_rows if _is_representative_taken(r)]

    daily_pnl: Dict[str, float] = defaultdict(float)
    daily_trades: Dict[str, int] = defaultdict(int)

    for r in rep_taken:
        d = _row_date(r)
        if d is None or not (df <= d <= dt):
            continue
        ds = d.isoformat()
        daily_pnl[ds] += _pnl(r)
        daily_trades[ds] += 1

    all_dates = sorted(set(daily_pnl) | set(daily_trades))
    result: List[Dict[str, Any]] = []
    for ds in all_dates:
        result.append({
            "date": ds,
            "pnl": round(daily_pnl.get(ds, 0.0), 2),
            "trades": daily_trades.get(ds, 0),
        })
    return result  # already sorted date asc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_monthly(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Return months (all-time) + calendar (date-range filtered)."""
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df is None and dt is None:
        df, dt = _default_range()
    elif df is None:
        df = dt
    elif dt is None:
        dt = df

    assert df is not None and dt is not None  # type checker

    all_rows = _load_rows()

    months = _build_months(all_rows)
    calendar = _build_calendar(all_rows, df, dt)

    return {
        "months": months,
        "calendar": calendar,
        "meta": {
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
        },
    }
