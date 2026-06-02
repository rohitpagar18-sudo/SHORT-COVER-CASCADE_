"""Lot-sizing calculator.

Source-of-truth: strategy doc v3.1 FINAL Section 9.

Three-layer risk control:
  1. Primary    — target ₹3,000 risk per trade (range ₹2,500-₹3,500).
  2. Secondary  — hard lot cap (5 NIFTY / 3 BankNifty).
  3. Outer     — daily ₹6,000 max loss circuit breaker (handled by the
                 state module, not here).

Always round DOWN. Minimum 1 lot floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LotSizeResult:
    """Result of a lot-sizing calculation for one entry."""

    lots: int
    units: int                  # lots × lot_size
    risk_per_unit: float        # entry − SL
    total_risk_rupees: float    # units × risk_per_unit
    capped_by_lot_limit: bool   # True iff the symbol's hard lot cap clipped lots
    capped_by_risk_range: bool  # True iff total_risk falls outside [min, max]
    below_min_risk_band: bool   # True iff total_risk < min AND lots == hard cap
    reason: str


def _max_lot_cap(symbol: str, config) -> int:
    sym = symbol.strip().upper()
    if sym == "NIFTY":
        return int(config.position_sizing.nifty_max_lots)
    if sym == "BANKNIFTY":
        return int(config.position_sizing.banknifty_max_lots)
    raise ValueError(f"Unknown symbol '{symbol}', expected NIFTY or BANKNIFTY")


def compute_lots(
    entry_price: float,
    sl_price: float,
    symbol: str,
    lot_size: int,
    config,
) -> LotSizeResult:
    """Compute lot count for one entry.

    Args:
        entry_price: option entry price (rupees).
        sl_price: stop-loss price (rupees). Must be < entry_price.
        symbol: "NIFTY" or "BANKNIFTY".
        lot_size: exchange lot size (e.g. 65 for NIFTY).
        config: ``AppConfig``. Reads ``risk_reward.target_risk_per_trade``,
            ``risk_reward.risk_range_{min,max}``,
            ``position_sizing.lot_cap_enabled``,
            and the symbol-specific lot cap.

    Raises:
        ValueError: invalid symbol, sl_price >= entry_price,
            or lot_size <= 0.
    """
    if lot_size <= 0:
        raise ValueError(f"lot_size must be > 0, got {lot_size}")
    risk_per_unit = entry_price - sl_price
    if risk_per_unit <= 0:
        raise ValueError(
            f"Invalid SL: sl_price ({sl_price:.2f}) must be strictly below "
            f"entry_price ({entry_price:.2f})"
        )

    target_risk = float(config.risk_reward.target_risk_per_trade)
    risk_range_min = float(config.risk_reward.risk_range_min)
    risk_range_max = float(config.risk_reward.risk_range_max)

    raw_lots = math.floor(target_risk / (risk_per_unit * lot_size))
    lots = max(1, raw_lots)

    capped_by_lot_limit = False
    if config.position_sizing.lot_cap_enabled:
        cap = _max_lot_cap(symbol, config)
        if lots > cap:
            lots = cap
            capped_by_lot_limit = True

    units = lots * lot_size
    total_risk = units * risk_per_unit
    capped_by_risk_range = (
        total_risk < risk_range_min or total_risk > risk_range_max
    )

    # Cheap-option exception: if we're already at the hard lot cap and total
    # risk is still below the ₹2,500 minimum band, accept the trade rather
    # than rejecting it — there is no way to raise risk further without
    # breaching the lot cap. Tag the result so the alert path can flag it.
    below_min_risk_band = (
        capped_by_lot_limit and total_risk < risk_range_min
    )

    parts = [
        f"target ₹{target_risk:g} / (R ₹{risk_per_unit:.2f} × lot {lot_size}) "
        f"= raw {raw_lots} lots",
    ]
    if raw_lots < 1:
        parts.append("floored to 1 lot")
    if capped_by_lot_limit:
        parts.append(f"capped by hard lot limit ({lots})")
    if below_min_risk_band:
        parts.append(
            f"Hard cap applied ({lots} lots); total risk ₹{total_risk:.0f} "
            f"below ₹{risk_range_min:.0f} band — accepted on cheap option"
        )
    elif capped_by_risk_range:
        parts.append(
            f"total risk ₹{total_risk:.2f} outside ₹{risk_range_min:g}-"
            f"₹{risk_range_max:g} target band"
        )
    reason = "; ".join(parts)

    return LotSizeResult(
        lots=lots,
        units=units,
        risk_per_unit=risk_per_unit,
        total_risk_rupees=total_risk,
        capped_by_lot_limit=capped_by_lot_limit,
        capped_by_risk_range=capped_by_risk_range,
        below_min_risk_band=below_min_risk_band,
        reason=reason,
    )
