"""Read-only service over logs/paper_trades.jsonl.

Real field shape (observed):
  alert_id, episode_id, paper_role, date (YYYY-MM-DD), candle_timestamp,
  symbol, strike, relation, option_type, expiry,
  entry, sl, tp1, tp2, lots, lot_size, is_expiry_day,
  decision ("TAKEN"|"SKIPPED"), decision_reason, slot,
  outcome ("TP2_HIT"|"TP1_HIT"|"SL_HIT"|"NO_DATA"|"PARTIAL"|"WOULD_SKIP"),
  exit_price, exit_time, exit_reason,
  realized_R, paper_pnl, paper_pnl_per_unit,
  mfe, mae, mfe_R, mae_R, max_drawdown_R, bot_remark, bot_tags,
  triggered_caps[]
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_cls, timedelta
from typing import Any, Dict, List, Optional

from ..paths import PAPER_TRADES_JSONL
from ..time_utils import today_ist
from .jsonl_reader import read_jsonl


def all_trades(max_lines: int = 2000) -> List[Dict[str, Any]]:
    return read_jsonl(PAPER_TRADES_JSONL, max_lines=max_lines)


def trades_on_date(date_iso: str) -> List[Dict[str, Any]]:
    return [r for r in all_trades() if r.get("date") == date_iso]


def trades_today() -> List[Dict[str, Any]]:
    return trades_on_date(today_ist().isoformat())


def pnl_on_date(date_iso: str) -> float:
    total = 0.0
    for r in trades_on_date(date_iso):
        v = r.get("paper_pnl")
        if isinstance(v, (int, float)):
            total += float(v)
    return round(total, 2)


def pnl_today() -> float:
    return pnl_on_date(today_ist().isoformat())


def sl_hits_on_date(date_iso: str) -> int:
    return sum(1 for r in trades_on_date(date_iso) if r.get("outcome") == "SL_HIT")


def sl_hits_today() -> int:
    return sl_hits_on_date(today_ist().isoformat())


def open_positions_on_date(date_iso: str) -> int:
    """Heuristic: TAKEN trades whose outcome is still NO_DATA = in-flight."""
    n = 0
    for r in trades_on_date(date_iso):
        if r.get("decision") == "TAKEN" and r.get("outcome") == "NO_DATA":
            n += 1
    return n


def open_positions_today() -> int:
    return open_positions_on_date(today_ist().isoformat())


def trades_taken_on_date(date_iso: str) -> int:
    return sum(1 for r in trades_on_date(date_iso) if r.get("decision") == "TAKEN")


def same_strike_sl_count_today() -> int:
    """Max SL count on any single strike today."""
    counts: Dict[int, int] = defaultdict(int)
    for r in trades_today():
        if r.get("outcome") == "SL_HIT" and isinstance(r.get("strike"), int):
            counts[r["strike"]] += 1
    return max(counts.values()) if counts else 0


def strikes_locked_today(threshold: int = 2) -> List[int]:
    """Strikes that hit `threshold` or more SLs today."""
    counts: Dict[int, int] = defaultdict(int)
    for r in trades_today():
        if r.get("outcome") == "SL_HIT" and isinstance(r.get("strike"), int):
            counts[r["strike"]] += 1
    return sorted([s for s, c in counts.items() if c >= threshold])


def minutes_since_last_sl_today() -> Optional[int]:
    """Minutes since the latest SL_HIT today (None if none)."""
    from ..time_utils import parse_ist, now_ist
    latest = None
    for r in trades_today():
        if r.get("outcome") != "SL_HIT":
            continue
        ts = parse_ist(r.get("exit_time") or r.get("candle_timestamp"))
        if ts and (latest is None or ts > latest):
            latest = ts
    if latest is None:
        return None
    delta = now_ist() - latest
    return max(0, int(delta.total_seconds() // 60))


def latest_open_position() -> Optional[Dict[str, Any]]:
    """Return the most-recent TAKEN paper trade whose outcome is still
    NO_DATA. ltp/pnl/price_series are intentionally NOT fabricated — the
    JSONL is post-hoc, so live values are unavailable. Returns None when
    no open trade exists.
    """
    open_rows = [
        r for r in all_trades()
        if r.get("decision") == "TAKEN" and r.get("outcome") == "NO_DATA"
    ]
    if not open_rows:
        return None
    # newest by candle_timestamp string compare is safe for IST ISO-8601
    open_rows.sort(key=lambda r: r.get("candle_timestamp") or "", reverse=True)
    r = open_rows[0]
    return {
        "symbol": r.get("symbol"),
        "option_type": r.get("option_type"),
        "strike": r.get("strike"),
        "relation": r.get("relation"),
        "status": "OPEN",
        "entry_time": r.get("candle_timestamp"),
        "qty_lots": r.get("lots"),
        "buy_price": r.get("entry"),
        "ltp": None,                # not in JSONL — DO NOT fabricate
        "sl": r.get("sl"),
        "tp1": r.get("tp1"),
        "tp2": r.get("tp2"),
        "pnl": None,                # not derivable without ltp
        "price_series": [],         # empty — would need a live broker tap
    }


def pnl_series(window_days: int = 15, end_date: Optional[date_cls] = None) -> Dict[str, Any]:
    """Aggregate paper_pnl by IST date over the trailing `window_days`
    days ending at `end_date` (inclusive). Days with no trades show as 0.
    """
    end = end_date or today_ist()
    by_date: Dict[str, float] = defaultdict(float)
    for r in all_trades():
        d = r.get("date")
        v = r.get("paper_pnl")
        if isinstance(d, str) and isinstance(v, (int, float)):
            by_date[d] += float(v)

    days_list: List[Dict[str, Any]] = []
    cumulative_list: List[Dict[str, Any]] = []
    running = 0.0
    max_profit = 0.0
    max_loss = 0.0
    total = 0.0
    for i in range(window_days - 1, -1, -1):
        d = end - timedelta(days=i)
        ds = d.isoformat()
        v = round(by_date.get(ds, 0.0), 2)
        days_list.append({"date": ds, "realized_pnl": v, "is_profit": v >= 0})
        running += v
        cumulative_list.append({"date": ds, "net": round(running, 2)})
        total += v
        if v > max_profit:
            max_profit = v
        if v < max_loss:
            max_loss = v

    return {
        "window_days": window_days,
        "days": days_list,
        "cumulative": cumulative_list,
        "totals": {
            "total_pnl": round(total, 2),
            "realized_pnl": round(total, 2),
            "unrealized_pnl": 0.0,  # paper layer doesn't track unrealized
            "max_daily_profit": round(max_profit, 2),
            "max_daily_loss": round(max_loss, 2),
        },
    }
