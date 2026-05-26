"""India VIX regime classifier.

Source-of-truth: strategy doc Section 5 (v3.1 FINAL).

The numbers in this module are strategy-level constants (multipliers and
SL percentages). The ON/OFF toggle for "use VIX multiplier" lives in
config.yaml — but the multipliers themselves do not.

Boundary rule (strategy doc): boundaries at 12, 16, 20 belong to the
higher regime. So 12.0 is NORMAL, 16.0 is ELEVATED, 20.0 is HIGH.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VixRegime(Enum):
    LOW = "Low Vol"          # VIX below 12
    NORMAL = "Normal"        # VIX 12 - 16
    ELEVATED = "Elevated"    # VIX 16 - 20
    HIGH = "High Vol"        # VIX above 20


@dataclass(frozen=True)
class VixRegimeInfo:
    """Resolved regime row from the strategy doc Section 5 table."""

    regime: VixRegime
    method1_multiplier: float       # 0.75 / 1.0 / 1.25 / 1.5
    method2_sl_normal_pct: float    # 4 / 5 / 6 / 8 (percent)
    method2_sl_expiry_pct: float    # 12 / 15 / 18 / 22 (percent)
    vix_value: float                # the input VIX, retained for logging

    @property
    def label(self) -> str:
        return self.regime.value


def classify_vix(vix_value: float) -> VixRegimeInfo:
    """Classify a live India VIX reading into a strategy regime.

    Boundary rule: 12, 16, 20 belong to the *higher* regime.
    """
    if vix_value < 12.0:
        return VixRegimeInfo(
            regime=VixRegime.LOW,
            method1_multiplier=0.75,
            method2_sl_normal_pct=4.0,
            method2_sl_expiry_pct=12.0,
            vix_value=vix_value,
        )
    if vix_value < 16.0:
        return VixRegimeInfo(
            regime=VixRegime.NORMAL,
            method1_multiplier=1.0,
            method2_sl_normal_pct=5.0,
            method2_sl_expiry_pct=15.0,
            vix_value=vix_value,
        )
    if vix_value < 20.0:
        return VixRegimeInfo(
            regime=VixRegime.ELEVATED,
            method1_multiplier=1.25,
            method2_sl_normal_pct=6.0,
            method2_sl_expiry_pct=18.0,
            vix_value=vix_value,
        )
    return VixRegimeInfo(
        regime=VixRegime.HIGH,
        method1_multiplier=1.5,
        method2_sl_normal_pct=8.0,
        method2_sl_expiry_pct=22.0,
        vix_value=vix_value,
    )
