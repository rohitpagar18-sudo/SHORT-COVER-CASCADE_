"""Kite (Zerodha) data feed adapter — Phase 0 stub.

All methods raise NotImplementedError. The kiteconnect SDK is imported
lazily inside each method so importing this module does not load the SDK.
"""

from __future__ import annotations

import pandas as pd

from src.data.base_feed import BaseFeed


class KiteFeed(BaseFeed):
    def __init__(self) -> None:
        self._client = None  # lazy SDK client, populated in Phase 1

    def connect(self) -> bool:
        # TODO: Phase 1 — import kiteconnect.KiteConnect, set access token, verify profile
        raise NotImplementedError("TODO: Phase 1")

    def is_token_valid(self) -> bool:
        # TODO: Phase 1
        raise NotImplementedError("TODO: Phase 1")

    def get_lot_size(self, symbol: str) -> int:
        # TODO: Phase 1
        raise NotImplementedError("TODO: Phase 1")

    def get_spot_price(self, symbol: str) -> float:
        # TODO: Phase 1
        raise NotImplementedError("TODO: Phase 1")

    def get_5min_candles(self, instrument_key: str, n_candles: int) -> pd.DataFrame:
        # TODO: Phase 1
        raise NotImplementedError("TODO: Phase 1")

    def get_option_chain(self, symbol: str, expiry: str) -> pd.DataFrame:
        # TODO: Phase 1
        raise NotImplementedError("TODO: Phase 1")

    def get_india_vix(self) -> float:
        # TODO: Phase 1
        raise NotImplementedError("TODO: Phase 1")

    def get_atm_strike(self, symbol: str) -> int:
        # TODO: Phase 1
        raise NotImplementedError("TODO: Phase 1")

    def get_broker_name(self) -> str:
        return "kite"
