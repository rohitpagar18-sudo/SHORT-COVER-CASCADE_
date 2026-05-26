"""C4 — Volume Above MA(20) on a Green Candle.

Two checks combined: (1) the latest volume bar must close above its
20-period simple MA; (2) the candle must be green. A "green volume
bar" on most charts is colored by the same candle's close-vs-open, so
we re-use ``snapshot.is_green`` rather than introducing a separate
volume colour flag.

Pure function.
"""

from __future__ import annotations

from src.indicators.calculator import IndicatorSnapshot


def check_c4(snapshot: IndicatorSnapshot) -> tuple[bool, str]:
    """Evaluate C4 on the supplied option snapshot.

    Args:
        snapshot: option IndicatorSnapshot.

    Returns:
        ``(passed, reason)``.
    """
    volume = snapshot.volume
    volume_ma = snapshot.volume_ma
    is_green = snapshot.is_green

    if volume <= volume_ma:
        return False, (
            f"C4 FAIL: volume {volume:,.0f} not above MA(20) {volume_ma:,.0f} "
            f"(thin market)"
        )
    if not is_green:
        return False, (
            f"C4 FAIL: volume {volume:,.0f} above MA(20) {volume_ma:,.0f} but candle "
            f"is RED — sellers active, wait one candle"
        )

    return True, (
        f"C4 PASS: volume {volume:,.0f} above MA(20) {volume_ma:,.0f} on green candle"
    )
