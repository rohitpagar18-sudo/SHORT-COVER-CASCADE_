"""Profit target calculators — TP1 and TP2.

Source-of-truth: strategy doc v3.1 FINAL Section 8.

R = entry − SL. TP1 and TP2 are R-multiples whose factors depend on
whether today is an expiry day (bigger targets) or a normal day. The
factors live in config.yaml — never hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TPResult:
    """Result of a TP calculation for one entry."""

    tp1: float
    tp2: float
    risk_per_unit: float      # entry − SL
    risk_to_tp1_ratio: float  # 1.5 (normal) or 2.0 (expiry)
    risk_to_tp2_ratio: float  # 2.5 (normal) or 3.0 (expiry)
    is_expiry_day: bool


def compute_tps(
    entry_price: float,
    sl_price: float,
    is_expiry_day: bool,
    config,
) -> TPResult:
    """Return TP1 / TP2 for a buy-side entry.

    Args:
        entry_price: option entry price (rupees).
        sl_price: stop-loss price (rupees). Must be < entry_price.
        is_expiry_day: True iff today is the contract's expiry day.
        config: ``AppConfig``. Reads ``risk_reward.normal_day_tp{1,2}_r``
            or ``risk_reward.expiry_day_tp{1,2}_r``.

    Raises:
        ValueError: if ``sl_price >= entry_price`` (R would be <= 0,
            making the trade nonsensical).
    """
    risk_per_unit = entry_price - sl_price
    if risk_per_unit <= 0:
        raise ValueError(
            f"Invalid SL: sl_price ({sl_price:.2f}) must be strictly below "
            f"entry_price ({entry_price:.2f}); R = {risk_per_unit:.2f}"
        )
    if is_expiry_day:
        r1 = config.risk_reward.expiry_day_tp1_r
        r2 = config.risk_reward.expiry_day_tp2_r
    else:
        r1 = config.risk_reward.normal_day_tp1_r
        r2 = config.risk_reward.normal_day_tp2_r

    tp1 = entry_price + risk_per_unit * r1
    tp2 = entry_price + risk_per_unit * r2

    return TPResult(
        tp1=tp1,
        tp2=tp2,
        risk_per_unit=risk_per_unit,
        risk_to_tp1_ratio=r1,
        risk_to_tp2_ratio=r2,
        is_expiry_day=is_expiry_day,
    )
