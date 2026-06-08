"""Risk-management package.

Pure-function calculators for VIX regime, stop loss (Method 1 + Method 2),
profit targets, and lot sizing. None of these functions perform I/O —
they take primitives or dataclasses and return dataclass results.
"""

from src.risk.lot_sizing import LotSizeResult, compute_lots
from src.risk.profit_targets import TPResult, compute_tps
from src.risk.stop_loss import (
    BANKNIFTY_EXPIRY_DAY_BUFFER,
    BANKNIFTY_NORMAL_DAY_BUFFER,
    NIFTY_EXPIRY_DAY_BUFFER,
    NIFTY_NORMAL_DAY_BUFFER,
    SLResult,
    SmaTrailParams,
    check_hard_exit_red_candle,
    compute_sl_method1,
    compute_sl_method2,
    compute_sma_trail_sl,
    get_base_buffer,
)
from src.risk.vix_regime import VixRegime, VixRegimeInfo, classify_vix

__all__ = [
    "VixRegime",
    "VixRegimeInfo",
    "classify_vix",
    "SLResult",
    "SmaTrailParams",
    "compute_sl_method1",
    "compute_sl_method2",
    "compute_sma_trail_sl",
    "check_hard_exit_red_candle",
    "get_base_buffer",
    "NIFTY_NORMAL_DAY_BUFFER",
    "NIFTY_EXPIRY_DAY_BUFFER",
    "BANKNIFTY_NORMAL_DAY_BUFFER",
    "BANKNIFTY_EXPIRY_DAY_BUFFER",
    "TPResult",
    "compute_tps",
    "LotSizeResult",
    "compute_lots",
]
