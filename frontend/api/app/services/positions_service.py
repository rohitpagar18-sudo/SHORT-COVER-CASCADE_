"""Read-only service: open paper positions + their latest scan-derived LTP.

Data sources (read-only, never modified):
  logs/paper_trades.jsonl  — paper episode rows
  logs/signals.jsonl       — every 5-min scan row, carries option_close

REAL FIELD NAMES (verified against the actual logs on disk):

  paper_trades.jsonl per-row:
    alert_id, episode_id, paper_role, date, candle_timestamp, symbol,
    strike, relation, option_type, expiry, entry, sl, tp1, tp2, lots,
    lot_size, is_expiry_day, decision ("TAKEN"|"SKIPPED"), decision_reason,
    slot, outcome ("TP2_HIT"|"TP1_HIT"|"SL_HIT"|"NO_DATA"|"PARTIAL"|"WOULD_SKIP"),
    exit_price, exit_time, exit_reason, realized_R, paper_pnl,
    paper_pnl_per_unit, mfe, mae, mfe_R, mae_R, max_drawdown_R,
    intrabar_ambiguous, fidelity, bot_remark, bot_tags, triggered_caps[]

  signals.jsonl per-row:
    timestamp_ist, event_type, symbol, strike, relation, option_type,
    expiry, trading_symbol, spot_price, spot_vwap, option_close,
    option_vwap, rsi, rsi_ma, oi, oi_ma, volume, volume_ma, is_green,
    vix, vix_regime, conditions_passed[], conditions_failed[], all_passed,
    summary, reasons{}, opt_above_vwap_pct

OPEN-POSITION HEURISTIC
A paper episode is "open" when decision=="TAKEN" AND outcome=="NO_DATA".
That's the same definition `paper_service.open_positions_today()` uses.

LTP DERIVATION
For each open episode we scan signals.jsonl for the latest row matching
(symbol, strike, option_type) on the episode date or later, regardless of
event_type. `option_close` is the most current option price the bot has
recorded. If no scan exists for that key, last_ltp/running_pnl are null
— we never fabricate.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..paths import PAPER_TRADES_JSONL, SIGNALS_JSONL
from ..time_utils import fmt_ist, now_ist, parse_ist
from .jsonl_reader import read_jsonl

# Earliest entry_time eligible for the live Open Positions panel.
# SL/TP tracking data only exists from this point onwards; episodes logged
# before this timestamp have no exit-level data and must not appear as RUNNING.
TRACKING_START = "2026-06-05T13:25:00+05:30"


def _has_value(v: Any) -> bool:
    """Return True when v is a real numeric/string value (not None/NA/NaN)."""
    if v is None:
        return False
    if isinstance(v, float):
        return not math.isnan(v)
    if isinstance(v, str):
        return v.upper() not in ("NA", "NAN", "NULL", "NONE", "")
    return True


def _matches(row: Dict[str, Any], symbol: Any, strike: Any, option_type: Any) -> bool:
    return (
        row.get("symbol") == symbol
        and row.get("strike") == strike
        and row.get("option_type") == option_type
    )


def _latest_scan_price(
    signals: List[Dict[str, Any]],
    symbol: Any,
    strike: Any,
    option_type: Any,
    entry_iso: Optional[str],
) -> Dict[str, Any]:
    """Return {last_ltp, last_ltp_time, price_series} from the latest
    matching scan and ALL same-day matching scans. Nulls when absent.
    """
    latest_price: Optional[float] = None
    latest_ts: Optional[str] = None
    series: List[Dict[str, Any]] = []

    entry_dt = parse_ist(entry_iso) if entry_iso else None
    entry_date = entry_dt.date().isoformat() if entry_dt else None

    for r in signals:
        if not _matches(r, symbol, strike, option_type):
            continue
        ts = r.get("timestamp_ist")
        price = r.get("option_close")
        if not isinstance(ts, str) or not isinstance(price, (int, float)):
            continue
        # On entry-date scans, build the price series for the sparkline.
        if entry_date and ts.startswith(entry_date):
            series.append({"time": ts, "price": float(price)})
        # Track newest scan (string compare on ISO-8601 with same offset is safe).
        if latest_ts is None or ts > latest_ts:
            latest_ts = ts
            latest_price = float(price)

    # Sort series chronologically
    series.sort(key=lambda d: d["time"])
    return {
        "last_ltp": latest_price,
        "last_ltp_time": latest_ts,
        "price_series": series,
    }


def _running_pnl(
    entry: Optional[float],
    sl: Optional[float],
    last_ltp: Optional[float],
    lots: Optional[int],
    lot_size: Optional[int],
) -> Dict[str, Any]:
    """Return {running_pnl, running_pnl_r}. Any null input → null outputs.
    Bot is always BUYING options, so P&L = (LTP - entry) for both CE & PE.
    """
    if (
        not isinstance(entry, (int, float))
        or not isinstance(last_ltp, (int, float))
        or not isinstance(lots, int)
        or not isinstance(lot_size, int)
    ):
        return {"running_pnl": None, "running_pnl_r": None}
    qty = lots * lot_size
    pnl = round((float(last_ltp) - float(entry)) * qty, 2)
    r_val: Optional[float] = None
    if isinstance(sl, (int, float)) and float(entry) != float(sl):
        risk_per_unit = abs(float(entry) - float(sl))
        if risk_per_unit > 0:
            r_val = round((float(last_ltp) - float(entry)) / risk_per_unit, 3)
    return {"running_pnl": pnl, "running_pnl_r": r_val}


def open_positions() -> Dict[str, Any]:
    """Build the /api/positions/open payload. All reads tolerate missing
    / locked / partial files (degrade to empty positions list).
    """
    try:
        trades = read_jsonl(PAPER_TRADES_JSONL, max_lines=2000)
    except Exception:
        trades = []
    try:
        signals = read_jsonl(SIGNALS_JSONL, max_lines=5000)
    except Exception:
        signals = []

    positions: List[Dict[str, Any]] = []
    untracked_count = 0
    for t in trades:
        if t.get("decision") != "TAKEN" or t.get("outcome") != "NO_DATA":
            continue
        symbol = t.get("symbol")
        strike = t.get("strike")
        option_type = t.get("option_type")
        entry_iso = t.get("candle_timestamp")
        entry = t.get("entry")
        sl = t.get("sl")
        tp1 = t.get("tp1")
        tp2 = t.get("tp2")
        lots = t.get("lots")
        lot_size = t.get("lot_size")

        # Eligibility: must have real SL/TP data AND entry after tracking started.
        if not (_has_value(sl) and _has_value(tp1) and _has_value(tp2)):
            untracked_count += 1
            continue
        if entry_iso and entry_iso < TRACKING_START:
            untracked_count += 1
            continue

        scan = _latest_scan_price(signals, symbol, strike, option_type, entry_iso)
        pnl_block = _running_pnl(entry, sl, scan["last_ltp"], lots, lot_size)

        positions.append({
            "episode_id": t.get("episode_id"),
            "alert_id": t.get("alert_id"),
            "symbol": symbol,
            "option_type": option_type,
            "strike": strike,
            "relation": t.get("relation"),
            "expiry": t.get("expiry"),
            "entry_time": entry_iso,
            "qty_lots": lots,
            "lot_size": lot_size,
            "buy_price": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "last_ltp": scan["last_ltp"],
            "last_ltp_time": scan["last_ltp_time"],
            "running_pnl": pnl_block["running_pnl"],
            "running_pnl_r": pnl_block["running_pnl_r"],
            "status": "RUNNING",
            "price_series": scan["price_series"],
            "bot_remark": t.get("bot_remark"),
        })

    # Newest open positions first
    positions.sort(key=lambda p: p.get("entry_time") or "", reverse=True)
    return {
        "as_of": fmt_ist(now_ist()),
        "positions": positions,
        "untracked_count": untracked_count,
    }


def unrealized_pnl_sum() -> float:
    """Sum of running_pnl across all currently-open positions. Used by
    the Trades & Performance KPI block. Nulls treated as 0.
    """
    total = 0.0
    for p in open_positions()["positions"]:
        v = p.get("running_pnl")
        if isinstance(v, (int, float)):
            total += float(v)
    return round(total, 2)
