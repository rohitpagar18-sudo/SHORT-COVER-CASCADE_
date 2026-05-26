"""C0 — Spot Trend Filter.

The direction of the underlying spot index must agree with the option
side. For a CE trade we need the spot above its session VWAP; for a PE
trade we need the spot below it. No buffer zone, no higher-high check
— a simple above/below.

This is the first gate. If C0 fails, the caller does not even need to
fetch the option chart.

The function is pure: it takes raw primitives and returns
``(passed, reason)``. It never raises.
"""

from __future__ import annotations


def check_c0(spot_close: float, spot_vwap: float, option_type: str) -> tuple[bool, str]:
    """Evaluate C0 for the latest closed 5-minute candle.

    Args:
        spot_close: latest spot index close (NIFTY or BANKNIFTY).
        spot_vwap: spot's own session-anchored VWAP.
        option_type: ``"CE"`` or ``"PE"``.

    Returns:
        ``(passed, reason)`` — ``reason`` always describes which side of
        VWAP the spot sat on, regardless of pass/fail, so it can be
        logged verbatim.
    """
    if option_type == "CE":
        if spot_close > spot_vwap:
            return True, (
                f"C0 PASS: spot {spot_close:.2f} above VWAP {spot_vwap:.2f} "
                f"(CE direction OK)"
            )
        return False, (
            f"C0 FAIL: spot {spot_close:.2f} not above VWAP {spot_vwap:.2f} "
            f"(CE needs spot above)"
        )
    if option_type == "PE":
        if spot_close < spot_vwap:
            return True, (
                f"C0 PASS: spot {spot_close:.2f} below VWAP {spot_vwap:.2f} "
                f"(PE direction OK)"
            )
        return False, (
            f"C0 FAIL: spot {spot_close:.2f} not below VWAP {spot_vwap:.2f} "
            f"(PE needs spot below)"
        )
    return False, f"C0 ERROR: invalid option_type '{option_type}', must be CE or PE"
