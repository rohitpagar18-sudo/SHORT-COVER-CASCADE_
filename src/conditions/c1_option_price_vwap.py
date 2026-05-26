"""C1 — Option Price Above VWAP on a Green Candle.

On the option's own 5-minute chart the current candle must be GREEN
(close > open) and close above the option's session VWAP. Strategy doc
section 5 also defines the late-entry rule: if the candle has already
moved ``late_entry_threshold_percent`` (config-driven, default 30%) or
more above VWAP, do not chase — wait for a retrace.

Pure function: in → ``(bool, reason)``, no I/O, no logging, no raises.
"""

from __future__ import annotations

from src.indicators.calculator import IndicatorSnapshot


def check_c1(
    snapshot: IndicatorSnapshot, late_entry_threshold_pct: float
) -> tuple[bool, str]:
    """Evaluate C1 on the supplied option snapshot.

    Args:
        snapshot: option IndicatorSnapshot for the latest 5m candle.
        late_entry_threshold_pct: from
            ``config.strike.late_entry_threshold_percent``. Reason
            strings include this value so logs are self-explanatory.

    Returns:
        ``(passed, reason)``.
    """
    close = snapshot.close
    vwap = snapshot.vwap
    is_green = snapshot.is_green

    if not is_green:
        return False, (
            f"C1 FAIL: candle is RED (close {close:.2f} <= open {snapshot.open:.2f})"
        )

    if close <= vwap:
        return False, f"C1 FAIL: close {close:.2f} not above VWAP {vwap:.2f}"

    pct_above_vwap = ((close - vwap) / vwap) * 100.0
    if pct_above_vwap >= late_entry_threshold_pct:
        return False, (
            f"C1 FAIL (LATE ENTRY): close {close:.2f} is {pct_above_vwap:.1f}% above "
            f"VWAP {vwap:.2f} (threshold {late_entry_threshold_pct}%) — wait for retrace"
        )

    return True, (
        f"C1 PASS: green candle, close {close:.2f} above VWAP {vwap:.2f} "
        f"({pct_above_vwap:.1f}% above, under {late_entry_threshold_pct}% threshold)"
    )
