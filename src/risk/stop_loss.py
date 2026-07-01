"""Stop loss calculators — Method 1 (point buffer), Method 2 (percentage),
and Method 3 (Method-1 initial → N-SMA trail of the option close).

Source-of-truth: strategy doc v3.1 FINAL Sections 6, 7, and 8.

All functions are PURE: take primitives + ``VixRegimeInfo``, return an
``SLResult`` dataclass. No I/O, no broker calls.

Buffer table interpretation
---------------------------
Strategy doc lists ranges as ``50-100``, ``100-200``, ``200-400``, ``400+``.
We interpret each range as lower-inclusive, upper-exclusive — so price
100 belongs to the ``100-200`` band, not the ``50-100`` band. The
sub-₹50 ``0-50`` band is an extension to handle deep-OTM / EOD-expiry
options whose premiums sit below the strategy's documented range; the
hard-cap-lots branch in ``compute_lots()`` accepts these so the bot
issues a flagged alert rather than crashing.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.risk.vix_regime import VixRegimeInfo


@dataclass(frozen=True)
class SLResult:
    """Result of an SL calculation."""

    sl_price: float
    method: int                    # 1 or 2
    base_buffer: float             # Method 1: points; Method 2: 0.0
    vix_multiplier: float          # 0.75 / 1.0 / 1.25 / 1.5, or 1.0 if disabled
    final_buffer_or_pct: float     # Method 1: adjusted point buffer; Method 2: SL %
    reason: str                    # human-readable explanation


# Strategy doc Section 6 — NIFTY base buffer tables
# Each row: (price_min_inclusive, price_max_exclusive, buffer_points)
NIFTY_NORMAL_DAY_BUFFER: list[tuple[float, float, float]] = [
    (0, 50, 3),
    (50, 100, 5),
    (100, 200, 10),
    (200, 400, 15),
    (400, float("inf"), 20),
]
NIFTY_EXPIRY_DAY_BUFFER: list[tuple[float, float, float]] = [
    (0, 50, 10),
    (50, 100, 15),
    (100, 200, 20),
    (200, 400, 25),
    (400, float("inf"), 35),
]
BANKNIFTY_NORMAL_DAY_BUFFER: list[tuple[float, float, float]] = [
    (0, 50, 5),
    (50, 100, 8),
    (100, 200, 15),
    (200, 400, 22),
    (400, float("inf"), 30),
]
BANKNIFTY_EXPIRY_DAY_BUFFER: list[tuple[float, float, float]] = [
    (0, 50, 12),
    (50, 100, 20),
    (100, 200, 28),
    (200, 400, 35),
    (400, float("inf"), 45),
]


def _band_label(low: float, high: float) -> str:
    if high == float("inf"):
        return f"{low:.0f}+"
    return f"{low:.0f}-{high:.0f}"


def _lookup_buffer(
    table: list[tuple[float, float, float]], option_price: float
) -> tuple[float, str]:
    """Return (buffer_points, band_label) from a buffer table.

    Range interpretation: [low, high). Tables cover from 0 upward and the
    last band is unbounded above, so any non-negative price matches.
    """
    for low, high, buf in table:
        if low <= option_price < high:
            return buf, _band_label(low, high)
    raise ValueError(f"No buffer band matched price {option_price:.2f}")


def _pick_table(
    symbol: str, is_expiry_day: bool
) -> list[tuple[float, float, float]]:
    sym = symbol.strip().upper()
    if sym == "NIFTY":
        return NIFTY_EXPIRY_DAY_BUFFER if is_expiry_day else NIFTY_NORMAL_DAY_BUFFER
    if sym == "BANKNIFTY":
        return (
            BANKNIFTY_EXPIRY_DAY_BUFFER
            if is_expiry_day
            else BANKNIFTY_NORMAL_DAY_BUFFER
        )
    raise ValueError(f"Unknown symbol '{symbol}', expected NIFTY or BANKNIFTY")


def get_base_buffer(
    symbol: str, option_price: float, is_expiry_day: bool
) -> float:
    """Return the base SL buffer in points for the given symbol/price/day-type.

    Raises:
        ValueError: symbol unknown.
    """
    table = _pick_table(symbol, is_expiry_day)
    buf, _ = _lookup_buffer(table, option_price)
    return buf


def compute_sl_method1(
    vwap_at_entry: float,
    option_price: float,
    symbol: str,
    is_expiry_day: bool,
    vix_info: VixRegimeInfo,
    use_vix_multiplier: bool,
) -> SLResult:
    """Method 1 — point-buffer stop loss.

    SL = VWAP − (base_buffer × VIX_multiplier if enabled else 1.0)
    """
    table = _pick_table(symbol, is_expiry_day)
    base_buffer, band = _lookup_buffer(table, option_price)
    multiplier = vix_info.method1_multiplier if use_vix_multiplier else 1.0
    final_buffer = base_buffer * multiplier
    sl_price = vwap_at_entry - final_buffer
    day_label = "Expiry" if is_expiry_day else "Normal"
    vix_part = (
        f"× {multiplier} ({vix_info.label})"
        if use_vix_multiplier
        else "× 1.0 (VIX multiplier OFF)"
    )
    reason = (
        f"Method 1 — {symbol.upper()} {day_label} day, band {band}: "
        f"base buffer {base_buffer:g} {vix_part} = {final_buffer:g} pts; "
        f"SL = VWAP {vwap_at_entry:.2f} − {final_buffer:g} = {sl_price:.2f}"
    )
    return SLResult(
        sl_price=sl_price,
        method=1,
        base_buffer=base_buffer,
        vix_multiplier=multiplier,
        final_buffer_or_pct=final_buffer,
        reason=reason,
    )


def compute_sl_method2(
    vwap_at_entry: float,
    is_expiry_day: bool,
    vix_info: VixRegimeInfo,
) -> SLResult:
    """Method 2 — percentage-based stop loss.

    SL = VWAP − (VWAP × SL%). SL% comes from the VIX regime table
    (it already embeds the regime multiplier — there is no additional
    on/off toggle for Method 2).
    """
    sl_pct = (
        vix_info.method2_sl_expiry_pct
        if is_expiry_day
        else vix_info.method2_sl_normal_pct
    )
    sl_price = vwap_at_entry - (vwap_at_entry * sl_pct / 100.0)
    day_label = "Expiry" if is_expiry_day else "Normal"
    reason = (
        f"Method 2 — {day_label} day, {vix_info.label}: SL% = {sl_pct:g}%; "
        f"SL = VWAP {vwap_at_entry:.2f} − ({vwap_at_entry:.2f} × {sl_pct:g}%) "
        f"= {sl_price:.2f}"
    )
    return SLResult(
        sl_price=sl_price,
        method=2,
        base_buffer=0.0,
        vix_multiplier=vix_info.method1_multiplier,
        final_buffer_or_pct=sl_pct,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Method 3 — SMA trailing helper (Phase 4 SL addendum)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SmaTrailParams:
    """Knobs for the SL Method 3 trail. Lifted 1:1 from
    ``AppConfig.stop_loss.sma_trail``.
    """

    sma_period: int            # N closes (default 19)
    activate_after_minutes: int  # first N min after entry uses the static SL
    update_interval_minutes: int  # re-evaluate cadence after activation
    follow_direction: str       # "ratchet" (default) | "both"


def compute_sma_trail_sl(
    *,
    prev_sl: float,
    sma_value: float | None,
    follow_direction: str,
    method1_initial_sl: float,
) -> float:
    """One-shot SL update during a Method 3 trail tick.

    Args:
        prev_sl: the SL currently in effect.
        sma_value: SMA of the last N option closes, or ``None`` when the
            early-entry fallback applies (fewer than N candles available).
        follow_direction: ``"ratchet"`` (default — SL = ``max(prev_sl,
            sma)``, never loosens) or ``"both"`` (SL follows the SMA up
            AND down, but see the floor below).
        method1_initial_sl: the entry-time Method-1 SL. The trailed SL is
            HARD-FLOORED at this value for BOTH directions, so a Method-3
            trade can never loosen its SL past entry-time 1R.

    Returns:
        The new SL price, never below ``method1_initial_sl``. When
        ``sma_value is None`` the previous SL is returned unchanged —
        Method 3's early-entry fallback (hold the Method-1 SL until N
        candles exist).
    """
    if sma_value is None:
        return float(prev_sl)
    direction = (follow_direction or "ratchet").strip().lower()
    if direction == "ratchet":
        trailed = max(prev_sl, sma_value)
    else:  # "both" — follows the SMA up and down
        trailed = sma_value
    # Hard floor (both directions): the trailed SL can never loosen past
    # the Method-1 initial SL, so the trade never risks more than its
    # entry-time 1R. For ratchet this is a no-op (prev_sl already >=
    # initial); for both it is the safety cap spec §8A requires.
    return float(max(method1_initial_sl, trailed))


def check_hard_exit_red_candle(
    candle_open: float,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    vwap_at_entry: float,
) -> tuple[bool, str]:
    """Hard exit rule (strategy doc Sections 6 & 7).

    If a complete red candle body forms entirely below VWAP — open,
    high, low, close ALL strictly below VWAP — exit immediately even
    if the regular SL has not been hit.

    Returns:
        (should_exit, human-readable reason).
    """
    if candle_close >= candle_open:
        return (
            False,
            f"Candle is GREEN (close {candle_close:.2f} >= open {candle_open:.2f}) — "
            "hard-exit rule does not apply",
        )
    # Red candle. Check that the ENTIRE candle is below VWAP.
    if (
        candle_open < vwap_at_entry
        and candle_high < vwap_at_entry
        and candle_low < vwap_at_entry
        and candle_close < vwap_at_entry
    ):
        return (
            True,
            f"Red candle body entirely below VWAP {vwap_at_entry:.2f} "
            f"(O={candle_open:.2f} H={candle_high:.2f} "
            f"L={candle_low:.2f} C={candle_close:.2f}) — hard exit",
        )
    return (
        False,
        f"Red candle but not entirely below VWAP {vwap_at_entry:.2f} "
        f"(O={candle_open:.2f} H={candle_high:.2f} "
        f"L={candle_low:.2f} C={candle_close:.2f}) — hold",
    )
