"""Read-only service over logs/paper_trades.jsonl.

Real field shape (observed):
  alert_id, episode_id, paper_role, date (YYYY-MM-DD), candle_timestamp,
  symbol, strike, relation, option_type, expiry,
  entry, sl, tp1, tp2, lots, lot_size, is_expiry_day,
  decision ("TAKEN"|"SKIPPED"), decision_reason, slot,
  outcome ("TP2_HIT"|"TP1_HIT"|"SL_HIT"|"NO_DATA"|"PARTIAL"|"WOULD_SKIP"),
  exit_price, exit_time, exit_reason,
  realized_R, paper_pnl, paper_pnl_per_unit,
  mfe, mae, mfe_R, mae_R, max_drawdown_R
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..paths import PAPER_TRADES_JSONL
from ..time_utils import today_ist
from .jsonl_reader import read_jsonl


def all_trades(max_lines: int = 1000) -> List[Dict[str, Any]]:
    return read_jsonl(PAPER_TRADES_JSONL, max_lines=max_lines)


def trades_today() -> List[Dict[str, Any]]:
    today = today_ist().isoformat()
    return [r for r in all_trades() if r.get("date") == today]


def pnl_today() -> float:
    total = 0.0
    for r in trades_today():
        v = r.get("paper_pnl")
        if isinstance(v, (int, float)):
            total += float(v)
    return round(total, 2)


def sl_hits_today() -> int:
    return sum(1 for r in trades_today() if r.get("outcome") == "SL_HIT")


def open_positions_today() -> int:
    """Heuristic: TAKEN trades whose outcome is still NO_DATA = treated as
    in-flight. Once a real broker integration exists this will be replaced.
    """
    n = 0
    for r in trades_today():
        if r.get("decision") == "TAKEN" and r.get("outcome") == "NO_DATA":
            n += 1
    return n
