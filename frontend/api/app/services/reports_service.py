"""reports_service.py — Performance analytics for Dashboard & Reports (Phase F7a).

Reads logs/paper_trades.jsonl and computes KPIs, cumulative series,
breakdowns by underlying / weekday, top winners / losers, outcome
distribution, trade duration, and monthly summary.

All datetimes: IST (Asia/Kolkata). Never UTC naive. Python 3.11+ guaranteed.
All file I/O wrapped in try/except — missing file / parse errors degrade
gracefully (empty or zero values, never a 500).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_cls, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ..paths import PAPER_TRADES_JSONL
from .jsonl_reader import read_jsonl

IST = ZoneInfo("Asia/Kolkata")

_WINNER_OUTCOMES = {"TP2_HIT", "TP1_HIT", "PARTIAL"}
_LOSER_OUTCOMES = {"SL_HIT"}
_FINAL_OUTCOMES = _WINNER_OUTCOMES | _LOSER_OUTCOMES | {"WOULD_SKIP"}

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
_WEEKDAY_IDX = {n: i for i, n in enumerate(_WEEKDAYS)}

_DURATION_BUCKETS = ["0-15 min", "15-30 min", "30-60 min", "60-120 min", ">120 min"]


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
        return date_cls.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse ISO-8601 string with optional tz into an IST datetime."""
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (ValueError, TypeError):
        return None


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


def _hhmm(ts: Any) -> str:
    if isinstance(ts, str) and "T" in ts:
        return ts.split("T", 1)[1][:5]
    return ""


def _duration_minutes(row: Dict[str, Any]) -> Optional[float]:
    t_start = _parse_dt(row.get("candle_timestamp"))
    t_exit = _parse_dt(row.get("exit_time"))
    if t_start is None or t_exit is None:
        return None
    delta = (t_exit - t_start).total_seconds() / 60.0
    if delta < 0:
        return None
    return delta


def _duration_bucket(mins: float) -> str:
    if mins < 15:
        return "0-15 min"
    if mins < 30:
        return "15-30 min"
    if mins < 60:
        return "30-60 min"
    if mins < 120:
        return "60-120 min"
    return ">120 min"


def _is_representative_taken(row: Dict[str, Any]) -> bool:
    return (
        row.get("decision") == "TAKEN"
        and row.get("paper_role") == "representative"
    )


def _pnl(row: Dict[str, Any]) -> float:
    v = row.get("paper_pnl")
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


def _is_finalized(row: Dict[str, Any]) -> bool:
    return row.get("outcome") not in (None, "NO_DATA")


def _is_open(row: Dict[str, Any]) -> bool:
    return row.get("outcome") == "NO_DATA"


# ---------------------------------------------------------------------------
# Default date range: current IST month
# ---------------------------------------------------------------------------

def _default_range() -> Tuple[date_cls, date_cls]:
    today = _today_ist()
    start = today.replace(day=1)
    return start, today


# ---------------------------------------------------------------------------
# Load and classify rows
# ---------------------------------------------------------------------------

def _load_rows() -> List[Dict[str, Any]]:
    try:
        return read_jsonl(PAPER_TRADES_JSONL, max_lines=20_000)
    except Exception:
        return []


def _filter_range(rows: List[Dict[str, Any]], df: date_cls, dt: date_cls) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        d = _row_date(r)
        if d is None:
            continue
        if df <= d <= dt:
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# KPI helpers
# ---------------------------------------------------------------------------

def _build_kpis(finalized: List[Dict[str, Any]], prev_finalized: Optional[List[Dict[str, Any]]], spark_series: List[float]) -> Dict[str, Any]:
    def _compute(rows: List[Dict[str, Any]]) -> Dict[str, float]:
        total = len(rows)
        winners = [r for r in rows if r.get("outcome") in _WINNER_OUTCOMES]
        losers = [r for r in rows if r.get("outcome") in _LOSER_OUTCOMES]
        win_pnls = [_pnl(r) for r in winners]
        loss_pnls = [_pnl(r) for r in losers]
        total_pnl = sum(_pnl(r) for r in rows)
        gross_profit = sum(p for p in win_pnls if p > 0)
        gross_loss = sum(abs(p) for p in loss_pnls if p < 0)
        win_rate = (len(winners) / total * 100.0) if total else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
        avg_win = (sum(win_pnls) / len(win_pnls)) if win_pnls else 0.0
        avg_loss = (sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0.0
        win_rate_frac = win_rate / 100.0
        expectancy = win_rate_frac * avg_win + (1 - win_rate_frac) * avg_loss
        return {
            "total_pnl": round(total_pnl, 2),
            "total_trades": float(total),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 2),
        }

    cur = _compute(finalized)
    prev = _compute(prev_finalized) if prev_finalized is not None else None

    def _delta(cv: Optional[float], pv: Optional[float]) -> Optional[float]:
        if cv is None or pv is None:
            return None
        if pv == 0:
            return None
        return round((cv - pv) / abs(pv) * 100.0, 1)

    kpi_keys = ["total_pnl", "total_trades", "win_rate", "profit_factor", "avg_win", "avg_loss", "expectancy"]
    kpis: Dict[str, Any] = {}
    for k in kpi_keys:
        cv = cur.get(k)
        pv = prev.get(k) if prev else None
        kpis[k] = {
            "value": cv,
            "prev_value": pv,
            "delta_pct": _delta(cv, pv) if not (cv is None or pv is None) else None,
            "spark": spark_series,
        }
    return kpis


# ---------------------------------------------------------------------------
# Cumulative series
# ---------------------------------------------------------------------------

def _build_cumulative(finalized: List[Dict[str, Any]], df: date_cls, dt: date_cls, agg: str) -> Tuple[List[Dict[str, Any]], List[float]]:
    by_date: Dict[str, float] = defaultdict(float)
    for r in finalized:
        d = _row_date(r)
        if d is not None:
            by_date[d.isoformat()] += _pnl(r)

    # Build a complete day series first
    daily_points: List[Tuple[str, float]] = []
    cur = df
    while cur <= dt:
        ds = cur.isoformat()
        daily_points.append((ds, round(by_date.get(ds, 0.0), 2)))
        cur += timedelta(days=1)

    spark = [v for _, v in daily_points]

    if agg == "weekly":
        buckets: Dict[str, List[float]] = defaultdict(list)
        for ds, v in daily_points:
            d = date_cls.fromisoformat(ds)
            week_start = (d - timedelta(days=d.weekday())).isoformat()
            buckets[week_start].append(v)
        agg_points = [(k, sum(vs)) for k, vs in sorted(buckets.items())]
    elif agg == "monthly":
        buckets2: Dict[str, List[float]] = defaultdict(list)
        for ds, v in daily_points:
            month_key = ds[:7]  # YYYY-MM
            buckets2[month_key].append(v)
        agg_points = [(k, sum(vs)) for k, vs in sorted(buckets2.items())]
    else:
        agg_points = daily_points

    result = []
    net = 0.0
    for period, daily_pnl in agg_points:
        daily_pnl = round(daily_pnl, 2)
        net = round(net + daily_pnl, 2)
        result.append({
            "period": period,
            "daily_pnl": daily_pnl,
            "cumulative_pnl": net,
        })
    return result, spark


# ---------------------------------------------------------------------------
# P&L by underlying
# ---------------------------------------------------------------------------

def _build_pnl_by_underlying(finalized: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_sym: Dict[str, float] = defaultdict(float)
    for r in finalized:
        sym = r.get("symbol") or "UNKNOWN"
        by_sym[sym] += _pnl(r)
    total_abs = sum(abs(v) for v in by_sym.values()) or 1.0
    return sorted(
        [{"symbol": k, "pnl": round(v, 2), "pct": round(abs(v) / total_abs * 100.0, 1)}
         for k, v in by_sym.items()],
        key=lambda x: abs(x["pnl"]),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# P&L by weekday
# ---------------------------------------------------------------------------

def _build_pnl_by_weekday(finalized: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_wd: Dict[int, float] = defaultdict(float)
    for r in finalized:
        d = _row_date(r)
        if d is not None:
            by_wd[d.weekday()] += _pnl(r)
    return [
        {"weekday": _WEEKDAYS[i], "pnl": round(by_wd.get(i, 0.0), 2)}
        for i in range(5)
    ]


# ---------------------------------------------------------------------------
# Top winners / losers
# ---------------------------------------------------------------------------

def _top_trade_row(r: Dict[str, Any]) -> Dict[str, Any]:
    d = _row_date(r)
    return {
        "date": d.isoformat() if d else "",
        "time": _hhmm(r.get("candle_timestamp")),
        "symbol": r.get("symbol"),
        "option_type": r.get("option_type"),
        "strike": r.get("strike"),
        "relation": r.get("relation"),
        "pnl": round(_pnl(r), 2),
        "outcome": r.get("outcome"),
    }


def _build_top_trades(finalized: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    sorted_pnl = sorted(finalized, key=_pnl, reverse=True)
    top_winners = [_top_trade_row(r) for r in sorted_pnl[:5] if _pnl(r) > 0]
    top_losers = [_top_trade_row(r) for r in sorted_pnl[:-6:-1] if _pnl(r) < 0]
    return top_winners, top_losers


# ---------------------------------------------------------------------------
# Outcome distribution
# ---------------------------------------------------------------------------

def _build_outcome_distribution(finalized: List[Dict[str, Any]], open_count: int) -> List[Dict[str, Any]]:
    counts: Dict[str, int] = defaultdict(int)
    for r in finalized:
        outcome = r.get("outcome") or "UNKNOWN"
        counts[outcome] += 1
    if open_count > 0:
        counts["Running"] = open_count

    total = sum(counts.values()) or 1
    return sorted(
        [{"outcome": k, "count": v, "pct": round(v / total * 100.0, 1)}
         for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Trade duration
# ---------------------------------------------------------------------------

def _build_duration(finalized: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    duration_rows = []
    for r in finalized:
        m = _duration_minutes(r)
        if m is not None:
            duration_rows.append((m, r.get("outcome")))

    if not duration_rows:
        return None

    bucket_counts: Dict[str, int] = defaultdict(int)
    bucket_wins: Dict[str, int] = defaultdict(int)
    for mins, outcome in duration_rows:
        bk = _duration_bucket(mins)
        bucket_counts[bk] += 1
        if outcome in _WINNER_OUTCOMES:
            bucket_wins[bk] += 1

    return [
        {
            "bucket": bk,
            "trades": bucket_counts[bk],
            "win_rate": round(bucket_wins[bk] / bucket_counts[bk] * 100.0, 1) if bucket_counts[bk] else 0.0,
        }
        for bk in _DURATION_BUCKETS
        if bucket_counts[bk] > 0
    ]


# ---------------------------------------------------------------------------
# Monthly summary (all-time, not filtered by date range)
# ---------------------------------------------------------------------------

def _build_monthly(all_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Only TAKEN+representative rows
    rep_taken = [r for r in all_rows if _is_representative_taken(r)]

    by_month: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rep_taken:
        d = _row_date(r)
        if d is not None:
            by_month[d.strftime("%Y-%m")].append(r)

    result = []
    for month_key in sorted(by_month.keys(), reverse=True):
        rows = by_month[month_key]
        finalized = [r for r in rows if _is_finalized(r)]
        open_rows = [r for r in rows if _is_open(r)]
        total_trades = len(finalized)
        winners = [r for r in finalized if r.get("outcome") in _WINNER_OUTCOMES]
        losers = [r for r in finalized if r.get("outcome") in _LOSER_OUTCOMES]
        win_rate = round(len(winners) / total_trades * 100.0, 1) if total_trades else 0.0
        realized_pnl = sum(_pnl(r) for r in finalized)
        unrealized_pnl = sum(_pnl(r) for r in open_rows)
        total_pnl = realized_pnl + unrealized_pnl

        gross_profit = sum(_pnl(r) for r in winners if _pnl(r) > 0)
        gross_loss = sum(abs(_pnl(r)) for r in losers if _pnl(r) < 0)
        profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

        # Per-day max/min for this month
        daily: Dict[str, float] = defaultdict(float)
        for r in finalized:
            d = _row_date(r)
            if d:
                daily[d.isoformat()] += _pnl(r)
        max_profit = max(daily.values(), default=0.0)
        max_loss = min(daily.values(), default=0.0)

        # Month label: "Jun 2026"
        try:
            d0 = date_cls.fromisoformat(month_key + "-01")
            label = d0.strftime("%b %Y")
        except ValueError:
            label = month_key

        result.append({
            "month": label,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 2),
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "profit_factor": profit_factor,
            "max_profit": round(max_profit, 2),
            "max_loss": round(max_loss, 2),
        })
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_performance(
    date_from: Optional[str],
    date_to: Optional[str],
    agg: str = "daily",
) -> Dict[str, Any]:
    """Compute and return the full performance report payload."""
    agg = agg.lower().strip()
    if agg not in ("daily", "weekly", "monthly"):
        agg = "daily"

    # Resolve date range
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    if df is None and dt is None:
        df, dt = _default_range()
    elif df is None:
        df = dt
    elif dt is None:
        dt = df

    assert df is not None and dt is not None  # for type checker

    # Compute prev period
    period_len = (dt - df).days + 1
    prev_to = df - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_len - 1)

    # Load all rows (no line limit — we need all-time for monthly table)
    all_rows = _load_rows()

    # Filter to current period, TAKEN+representative only
    cur_period = _filter_range(all_rows, df, dt)
    cur_rep_taken = [r for r in cur_period if _is_representative_taken(r)]

    finalized = [r for r in cur_rep_taken if _is_finalized(r)]
    open_rows = [r for r in cur_rep_taken if _is_open(r)]

    # Prev period finalized
    prev_period = _filter_range(all_rows, prev_from, prev_to)
    prev_rep_taken = [r for r in prev_period if _is_representative_taken(r)]
    prev_finalized = [r for r in prev_rep_taken if _is_finalized(r)]

    # Cumulative series + spark
    cumulative, spark = _build_cumulative(finalized, df, dt, agg)

    # KPIs
    kpis = _build_kpis(finalized, prev_finalized, spark)

    # Breakdowns
    pnl_by_underlying = _build_pnl_by_underlying(finalized)
    pnl_by_weekday = _build_pnl_by_weekday(finalized)
    top_winners, top_losers = _build_top_trades(finalized)
    outcome_distribution = _build_outcome_distribution(finalized, len(open_rows))
    trade_duration = _build_duration(finalized)
    monthly = _build_monthly(all_rows)

    return {
        "kpis": kpis,
        "cumulative": cumulative,
        "pnl_by_underlying": pnl_by_underlying,
        "pnl_by_weekday": pnl_by_weekday,
        "top_winners": top_winners,
        "top_losers": top_losers,
        "outcome_distribution": outcome_distribution,
        "trade_duration": trade_duration,
        "monthly": monthly,
        "meta": {
            "date_from": df.isoformat(),
            "date_to": dt.isoformat(),
            "prev_from": prev_from.isoformat(),
            "prev_to": prev_to.isoformat(),
            "agg": agg,
        },
    }
