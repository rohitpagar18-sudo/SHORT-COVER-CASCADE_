"""Smart strike selector for ATM / ITM / OTM scanning.

Strategy doc Section 4 restricts trades to ATM ± 1 strike. This module
turns spot price + option type + config into a list of concrete strikes
to scan, with their broker-specific instrument keys already resolved
from the option chain.

Two entry points:
  - ``get_alert_strikes`` — uses ``config.strike.alert_strikes`` toggles.
  - ``get_order_strikes`` — uses ``config.strike.order_strikes`` toggles
    (Phase 8). Same logic, different config sub-block.

Both call ``feed.get_option_chain(symbol, expiry)`` exactly once and
filter the rows in-memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd
from loguru import logger

_STRIKE_INTERVAL = {"NIFTY": 50, "BANKNIFTY": 100}
_ORDERED_RELATIONS: tuple[str, ...] = ("ITM", "ATM", "OTM")


@dataclass(frozen=True)
class StrikeChoice:
    """One scanable strike with its broker-resolved instrument key."""

    strike: int
    relation: str              # "ITM" / "ATM" / "OTM"
    instrument_key: str        # opaque string accepted by feed.get_5min_candles
    trading_symbol: str        # human-readable, e.g. NIFTY26JUN24050CE


def get_strike_interval(symbol: str) -> int:
    """Strike spacing: 50 for NIFTY, 100 for BANKNIFTY."""
    sym = symbol.strip().upper()
    if sym not in _STRIKE_INTERVAL:
        raise ValueError(f"Unknown symbol '{symbol}', expected NIFTY or BANKNIFTY")
    return _STRIKE_INTERVAL[sym]


def _compute_atm(spot_price: float, interval: int) -> int:
    return int(round(spot_price / interval) * interval)


def _select_relation_strikes(
    atm: int,
    interval: int,
    option_type: str,
) -> dict[str, int]:
    """Return {relation -> strike} for ITM, ATM, OTM of a CE or PE.

    For a CE: lower strike is ITM, higher strike is OTM.
    For a PE: higher strike is ITM, lower strike is OTM.
    """
    opt = option_type.strip().upper()
    if opt == "CE":
        return {
            "ITM": atm - interval,
            "ATM": atm,
            "OTM": atm + interval,
        }
    if opt == "PE":
        return {
            "ITM": atm + interval,
            "ATM": atm,
            "OTM": atm - interval,
        }
    raise ValueError(f"Unknown option_type '{option_type}', expected CE or PE")


def _instrument_key_col(cols: Iterable[str]) -> str:
    cols = list(cols)
    if "instrument_token" in cols:
        return "instrument_token"
    if "instrument_key" in cols:
        return "instrument_key"
    raise RuntimeError(
        f"Option chain has no instrument_token or instrument_key column; got {cols}"
    )


def _trading_symbol_col(cols: Iterable[str]) -> str | None:
    cols = list(cols)
    if "tradingsymbol" in cols:
        return "tradingsymbol"
    if "trading_symbol" in cols:
        return "trading_symbol"
    return None


def _find_row(
    chain: pd.DataFrame, strike: int, option_type: str
) -> pd.Series | None:
    if chain.empty:
        return None
    matches = chain[
        (chain["strike"] == float(strike))
        & (chain["instrument_type"] == option_type)
    ]
    if matches.empty:
        return None
    return matches.iloc[0]


def _row_to_choice(
    row: pd.Series,
    strike: int,
    relation: str,
    key_col: str,
    sym_col: str | None,
) -> StrikeChoice:
    key_val = row[key_col]
    if isinstance(key_val, (int, float)):
        instrument_key = str(int(key_val))
    else:
        instrument_key = str(key_val)
    trading_symbol = str(row[sym_col]) if sym_col else ""
    return StrikeChoice(
        strike=int(strike),
        relation=relation,
        instrument_key=instrument_key,
        trading_symbol=trading_symbol,
    )


def _select_strikes(
    feed: Any,
    symbol: str,
    spot_price: float,
    option_type: str,
    expiry: str,
    toggles: Any,
) -> list[StrikeChoice]:
    """Shared core for ``get_alert_strikes`` and ``get_order_strikes``."""
    interval = get_strike_interval(symbol)
    atm = _compute_atm(spot_price, interval)
    strikes_by_relation = _select_relation_strikes(atm, interval, option_type)

    chain = feed.get_option_chain(symbol, expiry)
    if chain is None or chain.empty:
        logger.warning(
            "Option chain for {} {} {} is empty — no strikes returned",
            symbol,
            expiry,
            option_type,
        )
        return []

    key_col = _instrument_key_col(chain.columns)
    sym_col = _trading_symbol_col(chain.columns)

    out: list[StrikeChoice] = []
    for relation in _ORDERED_RELATIONS:
        if not getattr(toggles, relation.lower()):
            continue
        strike = strikes_by_relation[relation]
        row = _find_row(chain, strike, option_type)
        if row is None:
            logger.debug(
                "Strike {} {} not in option chain for {} {} — skipping",
                strike,
                option_type,
                symbol,
                expiry,
            )
            continue
        out.append(_row_to_choice(row, strike, relation, key_col, sym_col))
    return out


def get_alert_strikes(
    feed: Any,
    symbol: str,
    spot_price: float,
    option_type: str,
    expiry: str,
    config,
) -> list[StrikeChoice]:
    """Return strikes to ALERT on, filtered by ``config.strike.alert_strikes``.

    A strike absent from the option chain (illiquid, doesn't exist) is
    skipped silently with a debug log.
    """
    return _select_strikes(
        feed, symbol, spot_price, option_type, expiry,
        config.strike.alert_strikes,
    )


def get_order_strikes(
    feed: Any,
    symbol: str,
    spot_price: float,
    option_type: str,
    expiry: str,
    config,
) -> list[StrikeChoice]:
    """Return strikes to AUTO-ORDER on (Phase 8), filtered by
    ``config.strike.order_strikes``.
    """
    return _select_strikes(
        feed, symbol, spot_price, option_type, expiry,
        config.strike.order_strikes,
    )
