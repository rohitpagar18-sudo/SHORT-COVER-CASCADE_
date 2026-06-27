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
    # In shadow mode "C5" is never written into conditions_passed / conditions_failed.
    # Pass/fail lives in the top-level boolean c5_passed (same field _profile uses).
    # Population: alert rows where C1-C4 fired (all_passed=True) and ADX was computed.
    c5_alerts = [
        s for s in signals
        if s.get("event_type") == "alert"
        and s.get("all_passed")
        and s.get("c5_passed") is not None
    ]

    c5_passed_in_alerts = sum(
        1 for a in c5_alerts if a.get("c5_passed") is True
    )
    c5_failed_in_alerts = sum(
        1 for a in c5_alerts if a.get("c5_passed") is False
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

    # ---- C0 Direction Filter — Retroactive Shadow Analysis ----
    # Reads spot_price + spot_vwap (already on every alert row) and asks:
    # would C0 have passed or blocked this alert? Then joins paper trades
    # to compare bucket outcomes. Pure read-only; no live-bot impact.
    c0_shadow_analysis = _compute_c0_shadow(signals)

    return {
        "pass_rates": pass_rates,
        "funnel": funnel,
        "bottleneck": bottleneck,
        "c5_shadow": c5_shadow,
        "adx_deep_dive": adx_deep_dive,
        "c0_shadow_analysis": c0_shadow_analysis,
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

    # Filter to the subset of C5 alerts with the desired status (boolean field).
    if c5_status == "passed":
        subset = [a for a in c5_alerts if a.get("c5_passed") is True]
    else:
        subset = [a for a in c5_alerts if a.get("c5_passed") is False]

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


# ---------------------------------------------------------------------------
# C0 Direction Filter — Retroactive Shadow Analysis
# ---------------------------------------------------------------------------
# C0 is currently OFF (c0_spot_trend_filter_enabled). When OFF, alerts fire
# for both CE and PE regardless of spot-vs-VWAP direction. This shadow layer
# asks: for each fired alert, would C0 have passed or blocked it? Then
# compares paper-trade outcomes between the two buckets.
#
# Win/Loss bucketing (per task spec — intentionally different from C5):
#   Win  = outcome in ("TP2_HIT", "TP1_HIT", "TP1_BE")
#   Loss = outcome == "SL_HIT"
#   Excluded: NO_DATA, OPEN_SQOFF, HARD_EXIT (unfinalized)

_C0_MIN_SAMPLE = 10
_C0_WIN_OUTCOMES = {"TP2_HIT", "TP1_HIT", "TP1_BE"}
_C0_LOSS_OUTCOMES = {"SL_HIT"}
_C0_EXCLUDED_OUTCOMES = {None, "", "NO_DATA", "OPEN_SQOFF", "HARD_EXIT"}


def _c0_would_pass(option_type: Optional[str], spot: Optional[float], vwap: Optional[float]) -> Optional[bool]:
    """Pure C0 rule. Returns None if inputs are missing."""
    if option_type not in ("CE", "PE"):
        return None
    if not isinstance(spot, (int, float)) or not isinstance(vwap, (int, float)):
        return None
    if option_type == "CE":
        return spot > vwap
    return spot < vwap  # PE


def _c0_bucket_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute {n, win_rate, avg_r, total_pnl} for a bucket.

    Applies the minimum-sample guard: if n < _C0_MIN_SAMPLE, win_rate and
    avg_r are returned as None (UI renders "too few to conclude"). Counts
    and total_pnl are always returned for transparency.
    """
    n = len(rows)
    winners = sum(1 for r in rows if r["outcome"] in _C0_WIN_OUTCOMES)
    losers = sum(1 for r in rows if r["outcome"] in _C0_LOSS_OUTCOMES)
    total_pnl = sum(
        float(r["paper_pnl"]) for r in rows
        if isinstance(r.get("paper_pnl"), (int, float))
    )

    if n < _C0_MIN_SAMPLE:
        return {
            "n": n,
            "winners": winners,
            "losers": losers,
            "win_rate": None,
            "avg_r": None,
            "total_pnl": round(total_pnl, 2),
        }

    decided = winners + losers
    win_rate = (winners / decided * 100.0) if decided > 0 else 0.0
    r_vals = [float(r["realized_R"]) for r in rows if isinstance(r.get("realized_R"), (int, float))]
    avg_r = (sum(r_vals) / len(r_vals)) if r_vals else 0.0
    return {
        "n": n,
        "winners": winners,
        "losers": losers,
        "win_rate": round(win_rate, 1),
        "avg_r": round(avg_r, 2),
        "total_pnl": round(total_pnl, 2),
    }


def _c0_insight_line(
    aligned: Dict[str, Any], misaligned: Dict[str, Any], block_pct: float
) -> str:
    """Auto-generate the bold insight beneath the C0 comparison table."""
    a_wr, m_wr = aligned.get("win_rate"), misaligned.get("win_rate")
    if a_wr is None or m_wr is None:
        return (
            f"C0 would have blocked {block_pct:.0f}% of alerts. "
            "Not enough finalized trades in one bucket to conclude — collect more data."
        )
    if a_wr - m_wr >= 5.0:
        return (
            f"C0 would have blocked {block_pct:.0f}% of alerts. "
            "Aligned trades outperform — consider enabling."
        )
    if m_wr - a_wr >= 5.0:
        return (
            f"C0 would have blocked {block_pct:.0f}% of alerts. "
            "Misaligned trades perform better — keep OFF."
        )
    return (
        f"C0 would have blocked {block_pct:.0f}% of alerts. "
        "No significant quality difference — keep OFF."
    )


def _compute_c0_shadow(signals: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build the C0 shadow report.

    Population: alert rows where all_passed=True AND spot_price + spot_vwap
    are present. Joined to TAKEN + representative paper trades on
    (symbol, strike, option_type, candle_timestamp).

    Returns None if there are no qualifying alerts (UI renders placeholder).
    """
    alerts = [
        s for s in signals
        if s.get("event_type") == "alert"
        and s.get("all_passed") is True
        and isinstance(s.get("spot_price"), (int, float))
        and isinstance(s.get("spot_vwap"), (int, float))
        and s.get("option_type") in ("CE", "PE")
    ]
    if not alerts:
        return None

    try:
        paper_trades = read_jsonl(PAPER_TRADES_JSONL, max_lines=20_000)
    except Exception:
        paper_trades = []

    # Index TAKEN + representative + finalized trades by alert key.
    trades_by_key: Dict[tuple, Dict[str, Any]] = {}
    for t in paper_trades:
        if t.get("decision") != "TAKEN":
            continue
        if t.get("paper_role") != "representative":
            continue
        if t.get("outcome") in _C0_EXCLUDED_OUTCOMES:
            continue
        key = (
            t.get("symbol"), t.get("strike"),
            t.get("option_type"), t.get("candle_timestamp"),
        )
        trades_by_key[key] = t

    aligned_rows: List[Dict[str, Any]] = []
    misaligned_rows: List[Dict[str, Any]] = []
    matched = 0

    for a in alerts:
        passes = _c0_would_pass(
            a.get("option_type"), a.get("spot_price"), a.get("spot_vwap"),
        )
        if passes is None:
            continue
        key = (
            a.get("symbol"), a.get("strike"),
            a.get("option_type"), a.get("timestamp_ist"),
        )
        trade = trades_by_key.get(key)
        if trade is None:
            continue
        matched += 1
        row = {
            "outcome": trade.get("outcome"),
            "realized_R": trade.get("realized_R"),
            "paper_pnl": trade.get("paper_pnl"),
        }
        (aligned_rows if passes else misaligned_rows).append(row)

    alerts_total = len(alerts)
    join_pct = (matched / alerts_total * 100.0) if alerts_total else 0.0
    aligned_count_all = sum(
        1 for a in alerts
        if _c0_would_pass(a.get("option_type"), a.get("spot_price"), a.get("spot_vwap")) is True
    )
    misaligned_count_all = alerts_total - aligned_count_all
    block_pct = (misaligned_count_all / alerts_total * 100.0) if alerts_total else 0.0

    aligned_stats = _c0_bucket_stats(aligned_rows)
    misaligned_stats = _c0_bucket_stats(misaligned_rows)

    pnl_delta = round(aligned_stats["total_pnl"] - misaligned_stats["total_pnl"], 2)

    report: Dict[str, Any] = {
        "alerts_total": alerts_total,
        "aligned_count": aligned_count_all,
        "misaligned_count": misaligned_count_all,
        "block_pct": round(block_pct, 1),
        "when_c0_aligned": aligned_stats,
        "when_c0_misaligned": misaligned_stats,
        "pnl_delta": pnl_delta,
        "insight": _c0_insight_line(aligned_stats, misaligned_stats, block_pct),
        "min_sample": _C0_MIN_SAMPLE,
    }

    if alerts_total > 0 and join_pct < 80.0:
        report["join_note"] = (
            f"Limited join coverage: only {matched}/{alerts_total} alerts "
            f"({join_pct:.0f}%) matched a finalized paper trade — older "
            "alerts may pre-date paper logging."
        )

    return report
