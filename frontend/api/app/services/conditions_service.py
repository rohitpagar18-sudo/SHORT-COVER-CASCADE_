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
from . import config_service


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

    adx_deep_dive = _build_adx_deep_dive(signals)

    return {
        "pass_rates": pass_rates,
        "funnel": funnel,
        "bottleneck": bottleneck,
        "c5_shadow": c5_shadow,
        "adx_deep_dive": adx_deep_dive,
        **({"di_alignment": di_alignment} if di_alignment else {}),
    }


# ---------------------------------------------------------------------------
# ADX Threshold Deep Dive (Phase F7a-2)
# ---------------------------------------------------------------------------

_ADX_BUCKETS: List[tuple] = [
    ("<15", lambda a: a < 15),
    ("15-20", lambda a: 15 <= a < 20),
    ("20-25", lambda a: 20 <= a < 25),
    ("25-30", lambda a: 25 <= a < 30),
    ("30-35", lambda a: 30 <= a < 35),
    ("35+", lambda a: a >= 35),
]


def _r1(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def _avg(values: List[float]) -> Optional[float]:
    return (sum(values) / len(values)) if values else None


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])


def _profile(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "avg_adx": None, "median_adx": None,
            "pct_rising": None,
            "avg_spot_di_plus": None, "avg_spot_di_minus": None,
            "pct_spot_aligned": None,
            "avg_opt_di_plus": None, "avg_opt_di_minus": None,
            "pct_opt_aligned": None,
            "pct_c5_passed": None,
        }

    def _nums(key: str) -> List[float]:
        out: List[float] = []
        for r in rows:
            v = r.get(key)
            if isinstance(v, (int, float)):
                out.append(float(v))
        return out

    adx_vals = _nums("adx")

    rising = 0
    rising_total = 0
    for r in rows:
        a, p = r.get("adx"), r.get("adx_prev")
        if isinstance(a, (int, float)) and isinstance(p, (int, float)):
            rising_total += 1
            if a > p:
                rising += 1

    spot_align = 0
    spot_align_total = 0
    for r in rows:
        dip, dim = r.get("di_plus"), r.get("di_minus")
        if not (isinstance(dip, (int, float)) and isinstance(dim, (int, float))):
            continue
        spot_align_total += 1
        opt_type = r.get("option_type")
        if opt_type == "CE" and dip > dim:
            spot_align += 1
        elif opt_type == "PE" and dim > dip:
            spot_align += 1

    opt_dip = _nums("option_di_plus")
    opt_dim = _nums("option_di_minus")
    opt_align = 0
    opt_align_total = 0
    for r in rows:
        dip, dim = r.get("option_di_plus"), r.get("option_di_minus")
        if isinstance(dip, (int, float)) and isinstance(dim, (int, float)):
            opt_align_total += 1
            if dip > dim:
                opt_align += 1

    c5_pass = sum(1 for r in rows if r.get("c5_passed") is True)

    return {
        "n": n,
        "avg_adx": _r1(_avg(adx_vals)),
        "median_adx": _r1(_median(adx_vals)),
        "pct_rising": _r1((rising / rising_total * 100.0) if rising_total else None),
        "avg_spot_di_plus": _r1(_avg(_nums("di_plus"))),
        "avg_spot_di_minus": _r1(_avg(_nums("di_minus"))),
        "pct_spot_aligned": _r1((spot_align / spot_align_total * 100.0) if spot_align_total else None),
        "avg_opt_di_plus": _r1(_avg(opt_dip)),
        "avg_opt_di_minus": _r1(_avg(opt_dim)),
        "pct_opt_aligned": _r1((opt_align / opt_align_total * 100.0) if opt_align_total else None),
        "pct_c5_passed": _r1((c5_pass / n * 100.0) if n else None),
    }


def _read_adx_config_snapshot() -> Dict[str, Any]:
    """Read C5 ADX knobs from live config.yaml — single source of truth."""
    try:
        return {
            "adx_min": float(config_service.get("conditions.c5_adx.adx_min", 20.0)),
            "require_rising": bool(config_service.get("conditions.c5_adx.require_rising", True)),
            "use_di_alignment": bool(config_service.get("conditions.c5_adx.use_di_alignment", False)),
            "gating": bool(config_service.get("conditions.c5_adx.gating", False)),
            "period": int(config_service.get("conditions.c5_adx.period", 14)),
        }
    except Exception:
        return {
            "adx_min": 20.0, "require_rising": True,
            "use_di_alignment": False, "gating": False, "period": 14,
        }


def _build_adx_deep_dive(signals: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Join paper trades to the alert-time signal row and slice by ADX bucket.

    Returns ``None`` when fewer than 5 paper trades have an ADX value
    logged (UI shows a placeholder).
    """
    try:
        paper_trades = read_jsonl(PAPER_TRADES_JSONL, max_lines=20_000)
    except Exception:
        paper_trades = []

    # Only TAKEN + representative + finalized.
    paper_finalized = [
        t for t in paper_trades
        if t.get("decision") == "TAKEN"
        and t.get("paper_role") == "representative"
        and t.get("outcome") not in (None, "NO_DATA")
    ]

    # Build signal lookup by (symbol, strike, option_type, candle_timestamp).
    # Prefer alert rows (richer), fall back to scan rows.
    sig_index: Dict[tuple, Dict[str, Any]] = {}
    for s in signals:
        ts = s.get("timestamp_ist")
        if not ts:
            continue
        key = (s.get("symbol"), s.get("strike"), s.get("option_type"), ts)
        existing = sig_index.get(key)
        # Alert rows take precedence over scans for the same key.
        if existing is None or (
            s.get("event_type") == "alert" and existing.get("event_type") != "alert"
        ):
            sig_index[key] = s

    matched_rows: List[Dict[str, Any]] = []
    for t in paper_finalized:
        key = (
            t.get("symbol"), t.get("strike"),
            t.get("option_type"), t.get("candle_timestamp"),
        )
        sig = sig_index.get(key)
        if sig is None:
            continue
        adx = sig.get("adx")
        if not isinstance(adx, (int, float)):
            continue
        # Combine trade + signal fields needed for the deep dive.
        matched_rows.append({
            "option_type": t.get("option_type"),
            "paper_pnl": t.get("paper_pnl"),
            "adx": float(adx),
            "adx_prev": sig.get("adx_prev"),
            "di_plus": sig.get("di_plus"),
            "di_minus": sig.get("di_minus"),
            "option_di_plus": sig.get("option_di_plus"),
            "option_di_minus": sig.get("option_di_minus"),
            "c5_passed": sig.get("c5_passed"),
        })

    if len(matched_rows) < 5:
        return None

    # Bucket counts.
    buckets: List[Dict[str, Any]] = []
    for label, predicate in _ADX_BUCKETS:
        in_bucket = [r for r in matched_rows if predicate(r["adx"])]
        winners = sum(
            1 for r in in_bucket
            if isinstance(r.get("paper_pnl"), (int, float)) and r["paper_pnl"] > 0
        )
        losers = len(in_bucket) - winners
        n = len(in_bucket)
        buckets.append({
            "label": label,
            "n": n,
            "winners": winners,
            "losers": losers,
            "win_rate_pct": _r1((winners / n * 100.0) if n else None),
        })

    # Winner vs loser profile.
    winner_rows = [
        r for r in matched_rows
        if isinstance(r.get("paper_pnl"), (int, float)) and r["paper_pnl"] > 0
    ]
    loser_rows = [
        r for r in matched_rows
        if not (isinstance(r.get("paper_pnl"), (int, float)) and r["paper_pnl"] > 0)
    ]

    total_paper = len(paper_finalized)
    matched = len(matched_rows)
    pct = round((matched / total_paper * 100.0), 1) if total_paper else 0.0
    note: Optional[str] = None
    if total_paper and pct < 80.0:
        note = (
            f"only {matched}/{total_paper} paper trades had an ADX value at "
            "alert time — older trades may pre-date C5 logging"
        )

    return {
        "config": _read_adx_config_snapshot(),
        "join_coverage": {
            "matched": matched,
            "total": total_paper,
            "pct": pct,
            "note": note,
        },
        "buckets": buckets,
        "winner_profile": _profile(winner_rows),
        "loser_profile": _profile(loser_rows),
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
