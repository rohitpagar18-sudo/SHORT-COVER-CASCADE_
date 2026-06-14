"""Read-only service: trades, KPIs, daily series, history grouping.

Builds /api/trades and /api/trades/history payloads. Filters on:
  date_from, date_to       (IST YYYY-MM-DD, inclusive; default = today IST)
  symbol                   ("NIFTY"|"BANKNIFTY"|None)
  option_type              ("CE"|"PE"|None)
  status                   trade row 'decision': "TAKEN"|"SKIPPED"|None
  outcome                  trade row 'outcome': "TP2_HIT"|"TP1_HIT"|"SL_HIT"|
                                              "NO_DATA"|"PARTIAL"|"WOULD_SKIP"|None

A REALIZED trade = paper_trades row with finalized outcome
(anything other than NO_DATA). Open positions contribute unrealized P&L
via positions_service.unrealized_pnl_sum().
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..paths import PAPER_TRADES_JSONL
from ..time_utils import today_ist
from .jsonl_reader import read_jsonl
from . import positions_service


_FINAL_OUTCOMES = {"TP2_HIT", "TP1_HIT", "SL_HIT", "PARTIAL", "WOULD_SKIP"}


def _parse_date(s: Optional[str]) -> Optional[date_cls]:
    if not s:
        return None
    try:
        return date_cls.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _row_date(row: Dict[str, Any]) -> Optional[date_cls]:
    """Prefer 'date' (YYYY-MM-DD), else derive from candle_timestamp."""
    d = row.get("date")
    if isinstance(d, str):
        parsed = _parse_date(d)
        if parsed:
            return parsed
    ts = row.get("candle_timestamp")
    if isinstance(ts, str) and "T" in ts:
        return _parse_date(ts.split("T", 1)[0])
    return None


def _hhmm(ts: Any) -> str:
    if isinstance(ts, str) and "T" in ts:
        return ts.split("T", 1)[1][:5]
    return ""


def _project_trade(row: Dict[str, Any]) -> Dict[str, Any]:
    """Project a paper_trades.jsonl row into the API trade shape."""
    return {
        "alert_id": row.get("alert_id"),
        "episode_id": row.get("episode_id"),
        "date": row.get("date"),
        "time": _hhmm(row.get("candle_timestamp")),
        "candle_timestamp": row.get("candle_timestamp"),
        "symbol": row.get("symbol"),
        "option_type": row.get("option_type"),
        "strike": row.get("strike"),
        "relation": row.get("relation"),
        "expiry": row.get("expiry"),
        "qty_lots": row.get("lots"),
        "lot_size": row.get("lot_size"),
        "buy_price": row.get("entry"),
        "sell_price": row.get("exit_price"),
        "sl": row.get("sl"),
        "tp1": row.get("tp1"),
        "tp2": row.get("tp2"),
        "pnl": row.get("paper_pnl"),
        "realized_R": row.get("realized_R"),
        "status": row.get("decision"),
        "outcome": row.get("outcome"),
        "exit_time": row.get("exit_time"),
        "exit_reason": row.get("exit_reason"),
        "bot_remark": row.get("bot_remark"),
    }


def _passes_filters(
    row: Dict[str, Any],
    df: Optional[date_cls],
    dt: Optional[date_cls],
    symbol: Optional[str],
    option_type: Optional[str],
    status: Optional[str],
    outcome: Optional[str],
) -> bool:
    d = _row_date(row)
    if df is not None and (d is None or d < df):
        return False
    if dt is not None and (d is None or d > dt):
        return False
    if symbol and row.get("symbol") != symbol:
        return False
    if option_type and row.get("option_type") != option_type:
        return False
    if status and row.get("decision") != status:
        return False
    if outcome and row.get("outcome") != outcome:
        return False
    return True


def _kpis(
    filtered: List[Dict[str, Any]],
    unrealized: float,
) -> Dict[str, Any]:
    realized_total = 0.0
    win_count = 0
    loss_count = 0
    daily_totals: Dict[str, float] = defaultdict(float)
    final_trade_count = 0

    for r in filtered:
        outcome = r.get("outcome")
        pnl = r.get("paper_pnl")
        if outcome in _FINAL_OUTCOMES and isinstance(pnl, (int, float)):
            realized_total += float(pnl)
            final_trade_count += 1
            d = r.get("date")
            if isinstance(d, str):
                daily_totals[d] += float(pnl)
            if outcome in ("TP2_HIT", "TP1_HIT") and pnl > 0:
                win_count += 1
            elif outcome == "SL_HIT" or (outcome in ("PARTIAL",) and pnl < 0):
                loss_count += 1

    max_daily_profit = max(daily_totals.values(), default=0.0)
    max_daily_loss = min(daily_totals.values(), default=0.0)

    total = final_trade_count
    win_pct = round((win_count / total) * 100.0, 1) if total else 0.0
    loss_pct = round((loss_count / total) * 100.0, 1) if total else 0.0

    return {
        "total_trades": total,
        "winning_trades": win_count,
        "winning_pct": win_pct,
        "losing_trades": loss_count,
        "losing_pct": loss_pct,
        "total_pnl": round(realized_total + unrealized, 2),
        "realized_pnl": round(realized_total, 2),
        "unrealized_pnl": round(unrealized, 2),
        "max_daily_profit": round(max_daily_profit, 2),
        "max_daily_loss": round(max_daily_loss, 2),
    }


def _daily_series(
    filtered: List[Dict[str, Any]],
    df: Optional[date_cls],
    dt: Optional[date_cls],
) -> List[Dict[str, Any]]:
    by_date: Dict[str, float] = defaultdict(float)
    for r in filtered:
        if r.get("outcome") not in _FINAL_OUTCOMES:
            continue
        d = r.get("date")
        v = r.get("paper_pnl")
        if isinstance(d, str) and isinstance(v, (int, float)):
            by_date[d] += float(v)

    if df is None or dt is None or df > dt:
        # Fall back to the dates we actually saw — sorted.
        days = sorted(by_date.keys())
        out = []
        net = 0.0
        for d in days:
            v = round(by_date[d], 2)
            net += v
            out.append({"date": d, "realized_pnl": v, "is_profit": v >= 0, "net": round(net, 2)})
        return out

    out: List[Dict[str, Any]] = []
    net = 0.0
    cur = df
    while cur <= dt:
        ds = cur.isoformat()
        v = round(by_date.get(ds, 0.0), 2)
        net += v
        out.append({"date": ds, "realized_pnl": v, "is_profit": v >= 0, "net": round(net, 2)})
        cur += timedelta(days=1)
    return out


def list_trades(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    symbol: Optional[str] = None,
    option_type: Optional[str] = None,
    status: Optional[str] = None,
    outcome: Optional[str] = None,
) -> Dict[str, Any]:
    """Build /api/trades payload."""
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df is None and dt is None:
        # default to today IST
        today = today_ist()
        df = dt = today
    elif df is None:
        df = dt
    elif dt is None:
        dt = df

    try:
        rows = read_jsonl(PAPER_TRADES_JSONL, max_lines=5000)
    except Exception:
        rows = []

    filtered_rows = [
        r for r in rows
        if _passes_filters(r, df, dt, symbol, option_type, status, outcome)
    ]

    try:
        unrealized = positions_service.unrealized_pnl_sum()
    except Exception:
        unrealized = 0.0

    kpis = _kpis(filtered_rows, unrealized)
    trades = [_project_trade(r) for r in filtered_rows]
    # Newest first within the table.
    trades.sort(key=lambda t: t.get("candle_timestamp") or "", reverse=True)

    return {
        "filters": {
            "date_from": df.isoformat() if df else None,
            "date_to": dt.isoformat() if dt else None,
            "symbol": symbol,
            "option_type": option_type,
            "status": status,
            "outcome": outcome,
        },
        "kpis": kpis,
        "trades": trades,
        "daily_series": _daily_series(filtered_rows, df, dt),
    }


# ---------------------------------------------------------------------------
# History grouping (day / week / month)
# ---------------------------------------------------------------------------

def _period_key(d: date_cls, group_by: str) -> Tuple[str, str]:
    """Return (period_label, period_start_iso) for the given date."""
    if group_by == "month":
        start = d.replace(day=1)
        label = start.strftime("%b %Y")
        return label, start.isoformat()
    if group_by == "week":
        # ISO week start = Monday
        start = d - timedelta(days=d.weekday())
        end = start + timedelta(days=6)
        label = f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
        return label, start.isoformat()
    # day (default)
    return d.strftime("%a %d %b %Y"), d.isoformat()


def history(
    group_by: str = "day",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    symbol: Optional[str] = None,
    option_type: Optional[str] = None,
    status: Optional[str] = None,
    outcome: Optional[str] = None,
) -> Dict[str, Any]:
    """Build /api/trades/history payload."""
    gb = group_by.lower().strip()
    if gb not in ("day", "week", "month"):
        gb = "day"

    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    # If neither is supplied, default to the last 30 days IST ending today.
    if df is None and dt is None:
        dt = today_ist()
        df = dt - timedelta(days=29)
    elif df is None:
        df = dt
    elif dt is None:
        dt = df

    try:
        rows = read_jsonl(PAPER_TRADES_JSONL, max_lines=5000)
    except Exception:
        rows = []

    filtered_rows = [
        r for r in rows
        if _passes_filters(r, df, dt, symbol, option_type, status, outcome)
    ]

    # Bucket by period key
    buckets: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in filtered_rows:
        d = _row_date(r)
        if d is None:
            continue
        key = _period_key(d, gb)
        buckets[key].append(r)

    try:
        unrealized = positions_service.unrealized_pnl_sum()
    except Exception:
        unrealized = 0.0

    groups: List[Dict[str, Any]] = []
    for (label, start_iso), rows_in_bucket in buckets.items():
        finals = [r for r in rows_in_bucket if r.get("outcome") in _FINAL_OUTCOMES]
        wins = sum(
            1 for r in finals
            if r.get("outcome") in ("TP2_HIT", "TP1_HIT")
            and isinstance(r.get("paper_pnl"), (int, float))
            and float(r["paper_pnl"]) > 0
        )
        total_trades = len(finals)
        win_rate = round((wins / total_trades) * 100.0, 1) if total_trades else 0.0
        realized = 0.0
        for r in finals:
            v = r.get("paper_pnl")
            if isinstance(v, (int, float)):
                realized += float(v)
        # Per-day max profit / loss inside the period
        per_day: Dict[str, float] = defaultdict(float)
        for r in finals:
            d = r.get("date")
            v = r.get("paper_pnl")
            if isinstance(d, str) and isinstance(v, (int, float)):
                per_day[d] += float(v)
        max_profit = max(per_day.values(), default=0.0)
        max_loss = min(per_day.values(), default=0.0)

        # Unrealized is a portfolio-wide value; we attribute it only to
        # the period containing TODAY IST so totals don't double-count.
        today_iso = today_ist().isoformat()
        period_unrealized = 0.0
        if any(
            r.get("date") == today_iso for r in rows_in_bucket
        ):
            period_unrealized = unrealized

        groups.append({
            "period_label": label,
            "period_start": start_iso,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl": round(realized + period_unrealized, 2),
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(period_unrealized, 2),
            "max_profit": round(max_profit, 2),
            "max_loss": round(max_loss, 2),
            "trades": sorted(
                (_project_trade(r) for r in rows_in_bucket),
                key=lambda t: t.get("candle_timestamp") or "",
                reverse=True,
            ),
        })

    groups.sort(key=lambda g: g["period_start"], reverse=True)

    return {
        "group_by": gb,
        "filters": {
            "date_from": df.isoformat() if df else None,
            "date_to": dt.isoformat() if dt else None,
            "symbol": symbol,
            "option_type": option_type,
            "status": status,
            "outcome": outcome,
        },
        "groups": groups,
    }
