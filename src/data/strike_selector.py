"""Smart strike selector for per-level ITM / ATM / OTM scanning.

Each strike depth (ITM1/ITM2/ITM3, ATM, OTM1/OTM2/OTM3) is an independent
ON/OFF toggle in ``config.strike.alert_strikes``. This module turns spot
price + option type + config into a list of concrete strikes to scan,
with their broker-specific instrument keys already resolved from the
option chain.

Two entry points:
  - ``get_alert_strikes`` — uses ``config.strike.alert_strikes`` toggles
    (7 per-level booleans).
  - ``get_order_strikes`` — uses ``config.strike.order_strikes`` toggles
    (3-way ITM/ATM/OTM, Phase 8). Different config sub-block.

Both call ``feed.get_option_chain(symbol, expiry)`` exactly once and
filter the rows in-memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd
from loguru import logger

_STRIKE_INTERVAL = {"NIFTY": 50, "BANKNIFTY": 100}

# Per-level alert toggles, in display order ITM3..ATM..OTM3. Each entry maps
# the relation label to (toggle_attr, ce_offset_units, pe_offset_units),
# where the offset is multiplied by the symbol strike interval. CE puts ITM
# below ATM and OTM above; PE mirrors.
_ALERT_LEVELS: tuple[tuple[str, str, int, int], ...] = (
    ("ITM3", "itm3", -3, +3),
    ("ITM2", "itm2", -2, +2),
    ("ITM1", "itm1", -1, +1),
    ("ATM",  "atm",   0,  0),
    ("OTM1", "otm1", +1, -1),
    ("OTM2", "otm2", +2, -2),
    ("OTM3", "otm3", +3, -3),
)

# Legacy 3-way relations used by ``get_order_strikes`` (Phase 8 config).
_ORDER_RELATIONS: tuple[str, ...] = ("ITM", "ATM", "OTM")


@dataclass(frozen=True)
class StrikeChoice:
    """One scanable strike with its broker-resolved instrument key."""

    strike: int
    relation: str              # "ITM1" / "ITM2" / "ITM3" / "ATM" / "OTM1" / "OTM2" / "OTM3"
                               #  (or legacy "ITM"/"ATM"/"OTM" from get_order_strikes)
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
    """Return {relation -> strike} for every per-level relation of a CE or PE.

    For a CE: ITMn = atm - n*interval, OTMn = atm + n*interval.
    For a PE: ITMn = atm + n*interval, OTMn = atm - n*interval.
    ATM is the same strike on both sides.
    """
    opt = option_type.strip().upper()
    if opt == "CE":
        return {label: atm + ce * interval for (label, _, ce, _) in _ALERT_LEVELS}
    if opt == "PE":
        return {label: atm + pe * interval for (label, _, _, pe) in _ALERT_LEVELS}
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


def _fetch_chain(
    feed: Any, symbol: str, expiry: str, option_type: str,
) -> tuple[pd.DataFrame | None, str | None, str | None]:
    chain = feed.get_option_chain(symbol, expiry)
    if chain is None or chain.empty:
        logger.warning(
            "Option chain for {} {} {} is empty — no strikes returned",
            symbol, expiry, option_type,
        )
        return None, None, None
    return chain, _instrument_key_col(chain.columns), _trading_symbol_col(chain.columns)


def get_alert_strikes(
    feed: Any,
    symbol: str,
    spot_price: float,
    option_type: str,
    expiry: str,
    config,
) -> list[StrikeChoice]:
    """Return strikes to ALERT on, filtered by per-level toggles in
    ``config.strike.alert_strikes`` (ITM3/ITM2/ITM1/ATM/OTM1/OTM2/OTM3).

    Strikes computed by arithmetic (atm ± n*interval) but only returned if
    present in the broker option chain — gaps in the chain (illiquid,
    doesn't exist) are skipped silently with a debug log. Returned in
    display order ITM3..ATM..OTM3.
    """
    interval = get_strike_interval(symbol)
    atm = _compute_atm(spot_price, interval)
    strikes_by_relation = _select_relation_strikes(atm, interval, option_type)

    chain, key_col, sym_col = _fetch_chain(feed, symbol, expiry, option_type)
    if chain is None:
        return []

    toggles = config.strike.alert_strikes
    out: list[StrikeChoice] = []
    for relation, attr, _, _ in _ALERT_LEVELS:
        if not getattr(toggles, attr):
            continue
        strike = strikes_by_relation[relation]
        row = _find_row(chain, strike, option_type)
        if row is None:
            logger.debug(
                "Strike {} {} not in option chain for {} {} — skipping",
                strike, option_type, symbol, expiry,
            )
            continue
        out.append(_row_to_choice(row, strike, relation, key_col, sym_col))

    logger.info(
        "Strike selector: {} {} {} ATM={} -> {} enabled contracts ({})",
        symbol, expiry, option_type, atm, len(out),
        ",".join(c.relation for c in out) if out else "none",
    )
    return out


def get_order_strikes(
    feed: Any,
    symbol: str,
    spot_price: float,
    option_type: str,
    expiry: str,
    config,
) -> list[StrikeChoice]:
    """Return strikes to AUTO-ORDER on (Phase 8), filtered by
    ``config.strike.order_strikes`` (legacy 3-way ITM/ATM/OTM).

    ITM = atm ∓ interval (1 strike deep) — same as the old behavior.
    """
    interval = get_strike_interval(symbol)
    atm = _compute_atm(spot_price, interval)
    opt = option_type.strip().upper()
    if opt == "CE":
        legacy = {"ITM": atm - interval, "ATM": atm, "OTM": atm + interval}
    elif opt == "PE":
        legacy = {"ITM": atm + interval, "ATM": atm, "OTM": atm - interval}
    else:
        raise ValueError(f"Unknown option_type '{option_type}', expected CE or PE")

    chain, key_col, sym_col = _fetch_chain(feed, symbol, expiry, option_type)
    if chain is None:
        return []

    toggles = config.strike.order_strikes
    out: list[StrikeChoice] = []
    for relation in _ORDER_RELATIONS:
        if not getattr(toggles, relation.lower()):
            continue
        strike = legacy[relation]
        row = _find_row(chain, strike, option_type)
        if row is None:
            logger.debug(
                "Order strike {} {} not in option chain for {} {} — skipping",
                strike, option_type, symbol, expiry,
            )
            continue
        out.append(_row_to_choice(row, strike, relation, key_col, sym_col))
    return out
