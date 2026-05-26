"""C2 — OI Below MA(20).

Option open-interest must close strictly below its 20-period simple MA.
Together with C1's green-candle requirement, this is the classic
short-covering signature (OI falling while price rises).

C2 only checks the OI half; the price-up half is enforced by C1. If C1
is ever modified, the price-up check must be restored here explicitly
— see strategy doc Section 5 note.

Pure function.
"""

from __future__ import annotations

from src.indicators.calculator import IndicatorSnapshot


def check_c2(snapshot: IndicatorSnapshot) -> tuple[bool, str]:
    """Evaluate C2 on the supplied option snapshot.

    Args:
        snapshot: option IndicatorSnapshot for the latest 5m candle.

    Returns:
        ``(passed, reason)``.
    """
    oi = snapshot.oi
    oi_ma = snapshot.oi_ma

    if oi_ma <= 0:
        return False, f"C2 FAIL: OI MA(20) is {oi_ma:,.0f} (non-positive — cannot evaluate)"

    if oi < oi_ma:
        pct_below = ((oi_ma - oi) / oi_ma) * 100.0
        return True, (
            f"C2 PASS: OI {oi:,.0f} below MA(20) {oi_ma:,.0f} "
            f"({pct_below:.1f}% below MA — short covering signal)"
        )

    pct_above = ((oi - oi_ma) / oi_ma) * 100.0
    return False, (
        f"C2 FAIL: OI {oi:,.0f} above MA(20) {oi_ma:,.0f} "
        f"({pct_above:.1f}% above MA — not short covering)"
    )
