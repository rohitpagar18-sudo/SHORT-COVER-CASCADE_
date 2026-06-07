"""Strategy conditions package.

Re-exports the five pure condition functions (C0–C4) plus the
``check_all_conditions`` orchestrator so strategy code can import from
``src.conditions`` without reaching into individual modules.
"""

from __future__ import annotations

from src.conditions.all_conditions import (
    AllConditionsResult,
    ConditionResult,
    check_all_conditions,
)
from src.conditions.c0_spot_trend import check_c0
from src.conditions.c1_option_price_vwap import check_c1
from src.conditions.c2_oi_below_ma import check_c2
from src.conditions.c3_rsi_momentum import check_c3
from src.conditions.c4_volume import check_c4
from src.conditions.c5_adx import check_c5_adx

__all__ = [
    "check_c0",
    "check_c1",
    "check_c2",
    "check_c3",
    "check_c4",
    "check_c5_adx",
    "check_all_conditions",
    "ConditionResult",
    "AllConditionsResult",
]
