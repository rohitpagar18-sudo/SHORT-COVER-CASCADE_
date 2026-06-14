"""Read-only service over logs/signals.jsonl for condition analysis.

Analyzes:
  - Pass rates for each condition (C0–C5)
  - Funnel (how many conditions passed per scan)
  - Bottleneck (which condition blocks the most near-misses)
  - C5 ADX shadow mode comparison vs paper trade outcomes
  - DI alignment (informational only)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, date as date_cls
from typing import Any, Dict, List, Optional

from ..paths import SIGNALS_JSONL, PAPER_TRADES_JSONL
from ..time_utils import IST, parse_ist
from .jsonl_reader import read_jsonl


def _parse_date(date_str: Optional[str]) -> Optional[date_cls]:
    """Parse YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        return None


def _extract_date_from_ts(ts: Optional[str]) -> Optional[date_cls]:
    """Extract date from ISO timestamp."""
    if not ts:
        return None
    try:
        return ts[:10]  # YYYY-MM-DD prefix
    except (ValueError, TypeError, IndexError):
        return None


def get_conditions_report(date_from: Optional[str], date_to: Optional[str]) -> Dict[str, Any]:
    """
    Returns:
    {
        "pass_rates": [
            {"condition": "C0", "label": "Spot vs VWAP", "status": "off"|"active"|"shadow",
             "scans": int, "passes": int, "pass_rate": float},
            ...  # C0–C5
        ],
        "funnel": [
            {"bucket": "0/5", "count": int},
            ...
            {"bucket": "5/5", "count": int},
            {"bucket": "Alerted", "count": int},
        ],
        "bottleneck": [
            {"condition": "C4", "blocked_count": 250},
            ...
        ],
        "c5_shadow": {
            "alerts_total": int,
            "c5_passed": int,
            "c5_failed": int,
            "c5_pass_rate": float,
            "when_c5_passed": {"n": int, "win_rate": float, "avg_r": float},
            "when_c5_failed": {"n": int, "win_rate": float, "avg_r": float},
            "join_note": "..." (optional)
        },
        "di_alignment": {
            "spot_aligned_pct": float,
            "option_aligned_pct": float,
            "note": "DI alignment is informational only..."
        }  # optional
    }
    """
    try:
        signals = read_jsonl(SIGNALS_JSONL, max_lines=20_000)
    except Exception:
        signals = []

    # Filter by date range (inclusive)
    from_date = _parse_date(date_from)
    to_date = _parse_date(date_to)

    filtered_signals = []
    for sig in signals:
        ts = sig.get("timestamp_ist")
        if ts:
            try:
                sig_date = _extract_date_from_ts(ts)[:10] if _extract_date_from_ts(ts) else None
                if sig_date:
                    if from_date and sig_date < from_date.isoformat():
                        continue
                    if to_date and sig_date > to_date.isoformat():
                        continue
                    filtered_signals.append(sig)
            except (ValueError, TypeError, IndexError):
                filtered_signals.append(sig)
        else:
            filtered_signals.append(sig)

    signals = filtered_signals

    # ---- Pass rates ----
    pass_rates = []
    condition_labels = {
        "C0": "Spot vs VWAP",
        "C1": "Option vs VWAP",
        "C2": "OI Filter",
        "C3": "RSI Filter",
        "C4": "Volume Filter",
        "C5": "ADX Trend",
    }

    # Count scans (all rows where event_type == "scan")
    scans = [s for s in signals if s.get("event_type") == "scan"]
    total_scans = len(scans)

    for cond in ["C0", "C1", "C2", "C3", "C4", "C5"]:
        # Count passes
        passes = sum(
            1
            for s in scans
            if cond in (s.get("conditions_passed") or [])
        )

        # Determine status
        status = "active"
        if cond == "C0":
            # C0 can be OFF. If it's in conditions_failed for all scans or never passes,
            # it might be off. For now, assume active unless we see evidence of being OFF.
            # TODO: read from config to determine if C0 is disabled
            status = "active"
        elif cond == "C5":
            # C5 shadow: enabled but not gating
            # TODO: read from config to determine if C5 is enabled and gating
            status = "shadow"

        pass_rate = (passes / total_scans * 100) if total_scans > 0 else 0.0

        pass_rates.append(
            {
                "condition": cond,
                "label": condition_labels.get(cond, cond),
                "status": status,
                "scans": total_scans,
                "passes": passes,
                "pass_rate": round(pass_rate, 1),
            }
        )

    # ---- Funnel ----
    funnel_buckets: Dict[int, int] = defaultdict(int)
    alerted_count = 0

    for s in signals:
        if s.get("event_type") == "scan":
            num_passed = len(s.get("conditions_passed") or [])
            funnel_buckets[num_passed] += 1

        if s.get("all_passed") and s.get("event_type") == "alert":
            alerted_count += 1

    funnel = [
        {"bucket": f"{i}/5", "count": funnel_buckets.get(i, 0)}
        for i in range(6)
    ]
    funnel.append({"bucket": "Alerted", "count": alerted_count})

    # ---- Bottleneck (conditions that block near-misses) ----
    # Near-miss = 4 conditions passed (one blocker)
    blockers: Dict[str, int] = defaultdict(int)
    for s in scans:
        passed = set(s.get("conditions_passed") or [])
        failed = set(s.get("conditions_failed") or [])
        if len(passed) == 4 and len(failed) == 1:
            blocker_cond = list(failed)[0]
            blockers[blocker_cond] += 1

    bottleneck = [
        {"condition": cond, "blocked_count": count}
        for cond, count in sorted(blockers.items(), key=lambda x: -x[1])
    ][:5]

    # ---- C5 Shadow Analysis ----
    # Find all alerts where C5 is present
    c5_alerts = [
        s for s in signals
        if s.get("all_passed") and s.get("event_type") == "alert"
        and "C5" in (s.get("conditions_passed") or []) or "C5" in (s.get("conditions_failed") or [])
    ]

    c5_passed_in_alerts = sum(
        1 for a in c5_alerts
        if "C5" in (a.get("conditions_passed") or [])
    )
    c5_failed_in_alerts = sum(
        1 for a in c5_alerts
        if "C5" in (a.get("conditions_failed") or [])
    )

    c5_pass_rate = (
        (c5_passed_in_alerts / len(c5_alerts) * 100)
        if c5_alerts
        else 0.0
    )

    # Join with paper_trades to compute win rates
    c5_shadow = {
        "alerts_total": len(c5_alerts),
        "c5_passed": c5_passed_in_alerts,
        "c5_failed": c5_failed_in_alerts,
        "c5_pass_rate": round(c5_pass_rate, 1),
        "when_c5_passed": _compute_c5_outcome_stats(c5_alerts, "passed"),
        "when_c5_failed": _compute_c5_outcome_stats(c5_alerts, "failed"),
    }

    # Add join_note if join coverage is incomplete
    join_note = _check_c5_join_coverage(c5_alerts)
    if join_note:
        c5_shadow["join_note"] = join_note

    # ---- DI Alignment (optional) ----
    di_alignment = None
    # Check if DI fields are present
    sample_with_di = next(
        (s for s in signals if "spot_di_aligned" in s or "option_di_aligned" in s),
        None,
    )
    if sample_with_di:
        spot_aligned_count = sum(
            1 for s in signals if s.get("spot_di_aligned")
        )
        option_aligned_count = sum(
            1 for s in signals if s.get("option_di_aligned")
        )
        total_with_spot_di = sum(
            1 for s in signals if "spot_di_aligned" in s
        )
        total_with_option_di = sum(
            1 for s in signals if "option_di_aligned" in s
        )

        di_alignment = {
            "spot_aligned_pct": (
                (spot_aligned_count / total_with_spot_di * 100)
                if total_with_spot_di > 0
                else 0.0
            ),
            "option_aligned_pct": (
                (option_aligned_count / total_with_option_di * 100)
                if total_with_option_di > 0
                else 0.0
            ),
            "note": "DI alignment is informational only (does not affect C5 pass/fail)",
        }

    return {
        "pass_rates": pass_rates,
        "funnel": funnel,
        "bottleneck": bottleneck,
        "c5_shadow": c5_shadow,
        **({"di_alignment": di_alignment} if di_alignment else {}),
    }


def _compute_c5_outcome_stats(
    c5_alerts: List[Dict[str, Any]],
    c5_status: str,  # "passed" or "failed"
) -> Dict[str, Any]:
    """Compute outcome stats for C5 alerts filtered by C5 status.
    Returns: {"n": int, "win_rate": float, "avg_r": float}
    """
    try:
        paper_trades = read_jsonl(PAPER_TRADES_JSONL, max_lines=20_000)
    except Exception:
        paper_trades = []

    # Filter to the subset of C5 alerts with the desired status
    if c5_status == "passed":
        subset = [a for a in c5_alerts if "C5" in (a.get("conditions_passed") or [])]
    else:
        subset = [a for a in c5_alerts if "C5" in (a.get("conditions_failed") or [])]

    if not subset:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0}

    # Try to join each alert to a paper trade
    # Key: symbol + strike + option_type + candle_timestamp
    matched_outcomes = []
    for alert in subset:
        alert_key = (
            alert.get("symbol"),
            alert.get("strike"),
            alert.get("option_type"),
            alert.get("timestamp_ist"),
        )
        # Find matching paper trade (TAKEN only)
        for trade in paper_trades:
            trade_key = (
                trade.get("symbol"),
                trade.get("strike"),
                trade.get("option_type"),
                trade.get("candle_timestamp"),
            )
            if alert_key == trade_key and trade.get("decision") == "TAKEN":
                outcome = trade.get("outcome")
                realized_r = trade.get("realized_R")
                if outcome and realized_r is not None:
                    matched_outcomes.append((outcome, realized_r))
                break

    if not matched_outcomes:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0}

    # Compute win rate (TP2_HIT + TP1_HIT + PARTIAL / total)
    winners = sum(
        1 for outcome, _ in matched_outcomes
        if outcome in ("TP2_HIT", "TP1_HIT", "PARTIAL")
    )
    win_rate = (winners / len(matched_outcomes) * 100) if matched_outcomes else 0.0

    # Compute avg R
    avg_r = (
        sum(r for _, r in matched_outcomes) / len(matched_outcomes)
        if matched_outcomes
        else 0.0
    )

    return {
        "n": len(matched_outcomes),
        "win_rate": round(win_rate, 1),
        "avg_r": round(avg_r, 2),
    }


def _check_c5_join_coverage(c5_alerts: List[Dict[str, Any]]) -> Optional[str]:
    """Return a note if the C5 → paper trade join is incomplete."""
    if not c5_alerts:
        return None

    try:
        paper_trades = read_jsonl(PAPER_TRADES_JSONL, max_lines=20_000)
    except Exception:
        return "Limited join coverage: could not read paper trades."

    # Count how many C5 alerts matched to a paper trade
    matched = 0
    for alert in c5_alerts:
        alert_key = (
            alert.get("symbol"),
            alert.get("strike"),
            alert.get("option_type"),
            alert.get("timestamp_ist"),
        )
        for trade in paper_trades:
            trade_key = (
                trade.get("symbol"),
                trade.get("strike"),
                trade.get("option_type"),
                trade.get("candle_timestamp"),
            )
            if alert_key == trade_key and trade.get("decision") == "TAKEN":
                matched += 1
                break

    join_coverage = (matched / len(c5_alerts) * 100) if c5_alerts else 0.0
    if join_coverage < 80:
        return f"Limited join coverage: {join_coverage:.0f}% of C5 alerts matched to paper trades."

    return None
