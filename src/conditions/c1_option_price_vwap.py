"""C1 — Option Price Above VWAP on a Green Candle.

On the option's own 5-minute chart the current candle must be GREEN
(close > open) and close above the option's session VWAP. Strategy doc
section 5 also defines the late-entry rule: if the candle has already
moved ``c1_max_distance_pct`` (config-driven, default 30%) or more above
VWAP, do not chase — wait for a retrace.

Pure function: in → ``(bool, reason, opt_above_vwap_pct)``, no I/O,
no logging, no raises.
"""

from __future__ import annotations

from src.indicators.calculator import IndicatorSnapshot


def check_c1(
    snapshot: IndicatorSnapshot, late_entry_threshold_pct: float
) -> tuple[bool, str, float]:
    """Evaluate C1 on the supplied option snapshot.

    Args:
        snapshot: option IndicatorSnapshot for the latest 5m candle.
        late_entry_threshold_pct: from
            ``config.conditions.c1_max_distance_pct`` (Phase 5.2).
            Reason strings include this value so logs are self-explanatory.

    Returns:
        ``(passed, reason, opt_above_vwap_pct)``.

        ``opt_above_vwap_pct`` is always populated (even on failure
        cases) so Phase 5.2 can log it and decide whether to fire a
        ``would_alert_extended`` event.
    """
    close = snapshot.close
    vwap = snapshot.vwap
    is_green = snapshot.is_green

    if vwap <= 0:
        return False, "C1 FAIL: VWAP not yet available", 0.0

    opt_above_vwap_pct = ((close - vwap) / vwap) * 100.0

    if not is_green:
        return False, (
            f"C1 FAIL: candle is RED (close {close:.2f} <= open {snapshot.open:.2f})"
        ), opt_above_vwap_pct

    if close <= vwap:
        return False, f"C1 FAIL: close {close:.2f} not above VWAP {vwap:.2f}", opt_above_vwap_pct

    if opt_above_vwap_pct >= late_entry_threshold_pct:
        return False, (
            f"C1 FAIL (LATE ENTRY): close {close:.2f} is {opt_above_vwap_pct:.1f}% above "
            f"VWAP {vwap:.2f} (threshold {late_entry_threshold_pct}%) — wait for retrace"
        ), opt_above_vwap_pct

    return True, (
        f"C1 PASS: green candle, close {close:.2f} above VWAP {vwap:.2f} "
        f"({opt_above_vwap_pct:.1f}% above, under {late_entry_threshold_pct}% threshold)"
    ), opt_above_vwap_pct
