"""C3 — RSI Momentum Above MA, In Range.

Strategy doc section 5 lists two valid forms for C3:
- Form A: Fresh upward crossover of RSI over its MA(20) on this or the
  immediately previous candle.
- Form B: RSI already above MA earlier and still clearly above.

Both reduce to "RSI > MA(20)" at the closed candle, plus the RSI value
range filter ``rsi_min < RSI < rsi_max`` (defaults 50 and 80 from the
``conditions`` block in config.yaml).

This implementation collapses Forms A/B into the same predicate per
the PHASE_3.md guidance — fresh-crossover vs sustained-above is left
to logging / future enhancement and does not change the pass/fail.

Pure function.
"""

from __future__ import annotations

from src.indicators.calculator import IndicatorSnapshot


def check_c3(
    snapshot: IndicatorSnapshot, rsi_min: float, rsi_max: float
) -> tuple[bool, str]:
    """Evaluate C3 on the supplied option snapshot.

    Args:
        snapshot: option IndicatorSnapshot.
        rsi_min: minimum RSI value (config.conditions.c3_rsi_min, default 50).
        rsi_max: maximum RSI value (config.conditions.c3_rsi_max, default 80).

    Returns:
        ``(passed, reason)``.
    """
    rsi = snapshot.rsi
    rsi_ma = snapshot.rsi_ma

    if rsi < rsi_min:
        return False, f"C3 FAIL: RSI {rsi:.2f} below minimum {rsi_min} (weak momentum)"
    if rsi > rsi_max:
        return False, f"C3 FAIL: RSI {rsi:.2f} above maximum {rsi_max} (overbought)"
    if rsi <= rsi_ma:
        return False, (
            f"C3 FAIL: RSI {rsi:.2f} not above MA(20) {rsi_ma:.2f} (no upward momentum)"
        )

    return True, (
        f"C3 PASS: RSI {rsi:.2f} above MA(20) {rsi_ma:.2f}, "
        f"within range [{rsi_min}, {rsi_max}]"
    )
