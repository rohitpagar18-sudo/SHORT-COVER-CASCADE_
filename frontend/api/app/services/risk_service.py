"""Read-only service over logs/paper_trades.jsonl for risk analysis.

Analyzes:
  - R-multiple distribution
  - Equity curve and drawdown
  - Win/loss streaks
  - MFE/MAE metrics
  - Risk adherence vs config target
  - Payoff ratios
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, date as date_cls
from typing import Any, Dict, List, Optional

from ..paths import PAPER_TRADES_JSONL
from ..time_utils import IST
from .jsonl_reader import read_jsonl


def _parse_date(date_str: Optional[str]) -> Optional[date_cls]:
    """Parse YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        return None


def get_risk_report(date_from: Optional[str], date_to: Optional[str]) -> Dict[str, Any]:
    """
    Returns:
    {
        "r_distribution": [
            {"r_bucket": "<-1.0", "count": int},
            ...
        ],
        "equity_curve": [
            {"date": "YYYY-MM-DD", "equity": float, "drawdown": float},
            ...
        ],
        "max_drawdown": {"rupees": float, "r": float},
        "streaks": {
            "current": int,  # positive=wins, negative=losses, 0=none
            "max_win": int,
            "max_loss": int,
        },
        "mfe_mae": {
            "avg_mfe_r": float,
            "avg_mae_r": float,
        } (optional)
        "risk_adherence": {
            "target": 3000,
            "range_min": 2500,
            "range_max": 3500,
            "within_range_pct": float,
            "distribution": [
                {"risk_bucket": "<2500", "count": int},
                ...
            ]
        },
        "payoff": {
            "avg_win_r": float,
            "avg_loss_r": float,
            "ratio": float | null,
        }
    }
    """
    try:
        paper_trades = read_jsonl(PAPER_TRADES_JSONL, max_lines=20_000)
    except Exception:
        paper_trades = []

    # Filter by date range (inclusive)
    from_date = _parse_date(date_from)
    to_date = _parse_date(date_to)

    filtered_trades = []
    for trade in paper_trades:
        trade_date_str = trade.get("date")
        if trade_date_str:
            try:
                trade_date = _parse_date(trade_date_str)
                if trade_date:
                    if from_date and trade_date < from_date:
                        continue
                    if to_date and trade_date > to_date:
                        continue
                    filtered_trades.append(trade)
            except (ValueError, TypeError):
                filtered_trades.append(trade)
        else:
            filtered_trades.append(trade)

    paper_trades = filtered_trades

    # Filter to TAKEN trades only for most metrics
    taken_trades = [t for t in paper_trades if t.get("decision") == "TAKEN"]

    # ---- R-distribution ----
    r_distribution_counts = {
        "<-1.0": 0,
        "-1.0 to 0": 0,
        "0 to 1.0": 0,
        "1.0 to 1.5": 0,
        "1.5 to 2.5": 0,
        ">2.5": 0,
    }

    for trade in taken_trades:
        outcome = trade.get("outcome")
        # Only count finalized trades (not NO_DATA)
        if outcome in ("TP2_HIT", "TP1_HIT", "SL_HIT", "PARTIAL", "WOULD_SKIP"):
            r = trade.get("realized_R")
            if r is not None:
                if r < -1.0:
                    r_distribution_counts["<-1.0"] += 1
                elif r < 0:
                    r_distribution_counts["-1.0 to 0"] += 1
                elif r < 1.0:
                    r_distribution_counts["0 to 1.0"] += 1
                elif r < 1.5:
                    r_distribution_counts["1.0 to 1.5"] += 1
                elif r < 2.5:
                    r_distribution_counts["1.5 to 2.5"] += 1
                else:
                    r_distribution_counts[">2.5"] += 1

    r_distribution = [
        {"r_bucket": bucket, "count": count}
        for bucket, count in r_distribution_counts.items()
    ]

    # ---- Equity Curve ----
    equity_by_date: Dict[str, float] = defaultdict(float)
    all_by_date: List[tuple[str, Dict[str, Any]]] = []

    for trade in taken_trades:
        date_str = trade.get("date")
        pnl = trade.get("paper_pnl")
        if date_str and pnl is not None:
            equity_by_date[date_str] += pnl
            all_by_date.append((date_str, trade))

    # Compute cumulative and running max drawdown
    cumulative = 0.0
    max_peak = 0.0
    equity_curve = []
    sorted_dates = sorted(set(d for d, _ in all_by_date))

    for date_str in sorted_dates:
        daily_pnl = equity_by_date[date_str]
        cumulative += daily_pnl
        max_peak = max(max_peak, cumulative)
        drawdown = max_peak - cumulative

        equity_curve.append(
            {
                "date": date_str,
                "equity": round(cumulative, 2),
                "drawdown": round(drawdown, 2),
            }
        )

    # Max drawdown
    max_drawdown_rupees = max(
        (pt["drawdown"] for pt in equity_curve),
        default=0.0,
    )

    # For max drawdown in R, we need to estimate per-trade
    # Simplified: average R per trade
    finalized = [
        t for t in taken_trades
        if t.get("outcome") in ("TP2_HIT", "TP1_HIT", "SL_HIT", "PARTIAL", "WOULD_SKIP")
    ]
    avg_trade_r = (
        sum(t.get("realized_R", 0) for t in finalized) / len(finalized)
        if finalized
        else 0.0
    )
    max_drawdown_r = max_drawdown_rupees / (1000.0) if avg_trade_r > 0 else 0.0  # rough estimate

    # ---- Streaks ----
    current_streak = 0
    max_win_streak = 0
    max_loss_streak = 0

    for trade in finalized:
        outcome = trade.get("outcome")
        is_winner = outcome in ("TP2_HIT", "TP1_HIT", "PARTIAL")

        if is_winner:
            if current_streak < 0:
                max_loss_streak = max(max_loss_streak, -current_streak)
                current_streak = 1
            else:
                current_streak += 1
        else:
            if current_streak > 0:
                max_win_streak = max(max_win_streak, current_streak)
                current_streak = -1
            else:
                current_streak -= 1

    # Finalize streaks
    if current_streak > 0:
        max_win_streak = max(max_win_streak, current_streak)
    elif current_streak < 0:
        max_loss_streak = max(max_loss_streak, -current_streak)

    streaks = {
        "current": current_streak,
        "max_win": max_win_streak,
        "max_loss": max_loss_streak,
    }

    # ---- MFE/MAE ----
    mfe_mae = None
    has_mfe_mae = any("mfe_R" in t and "mae_R" in t for t in finalized)
    if has_mfe_mae:
        mfes = [t.get("mfe_R", 0) for t in finalized if t.get("mfe_R") is not None]
        maes = [t.get("mae_R", 0) for t in finalized if t.get("mae_R") is not None]

        avg_mfe_r = sum(mfes) / len(mfes) if mfes else 0.0
        avg_mae_r = sum(maes) / len(maes) if maes else 0.0

        mfe_mae = {
            "avg_mfe_r": round(avg_mfe_r, 2),
            "avg_mae_r": round(avg_mae_r, 2),
        }

    # ---- Risk Adherence ----
    # Target and range from config (hardcoded defaults; ideally from config_service)
    risk_target = 3000
    risk_range_min = 2500
    risk_range_max = 3500

    risk_buckets = {
        "<2500": 0,
        "2500-3000": 0,
        "3000-3500": 0,
        ">3500": 0,
    }

    actual_risks = []
    for trade in taken_trades:
        entry = trade.get("entry")
        sl = trade.get("sl")
        lots = trade.get("lots")
        lot_size = trade.get("lot_size")

        if all(v is not None for v in [entry, sl, lots, lot_size]):
            # Actual risk = abs(entry - sl) * lots * lot_size
            actual_risk = abs(entry - sl) * lots * lot_size
            actual_risks.append(actual_risk)

            if actual_risk < risk_range_min:
                risk_buckets["<2500"] += 1
            elif actual_risk < 3000:
                risk_buckets["2500-3000"] += 1
            elif actual_risk < risk_range_max:
                risk_buckets["3000-3500"] += 1
            else:
                risk_buckets[">3500"] += 1

    within_range = sum(
        1 for r in actual_risks
        if risk_range_min <= r <= risk_range_max
    )
    within_range_pct = (
        (within_range / len(actual_risks) * 100)
        if actual_risks
        else 0.0
    )

    risk_adherence = {
        "target": risk_target,
        "range_min": risk_range_min,
        "range_max": risk_range_max,
        "within_range_pct": round(within_range_pct, 1),
        "distribution": [
            {"risk_bucket": bucket, "count": count}
            for bucket, count in risk_buckets.items()
        ],
    }

    # ---- Payoff ----
    winners = [t for t in finalized if t.get("outcome") in ("TP2_HIT", "TP1_HIT", "PARTIAL")]
    losers = [t for t in finalized if t.get("outcome") == "SL_HIT"]

    avg_win_r = (
        sum(t.get("realized_R", 0) for t in winners) / len(winners)
        if winners
        else 0.0
    )
    avg_loss_r = (
        sum(t.get("realized_R", 0) for t in losers) / len(losers)
        if losers
        else 0.0
    )

    payoff_ratio = None
    if losers and avg_loss_r != 0:
        payoff_ratio = avg_win_r / abs(avg_loss_r)

    payoff = {
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "ratio": round(payoff_ratio, 2) if payoff_ratio else None,
    }

    return {
        "r_distribution": r_distribution,
        "equity_curve": equity_curve,
        "max_drawdown": {
            "rupees": round(max_drawdown_rupees, 2),
            "r": round(max_drawdown_r, 2),
        },
        "streaks": streaks,
        **({"mfe_mae": mfe_mae} if mfe_mae else {}),
        "risk_adherence": risk_adherence,
        "payoff": payoff,
    }
