"""Abstract data-feed interface.

Every broker adapter (Kite, Upstox, ...) implements this. Strategy/condition/
orchestrator code only depends on this ABC — never on a specific SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

import pandas as pd

Symbol = Literal["NIFTY", "BANKNIFTY"]


class BaseFeed(ABC):
    """Broker-agnostic market-data interface."""

    @abstractmethod
    def connect(self) -> bool:
        """Authenticate against the broker and verify the access token.

        Returns:
            True on success, False on auth/network failure.
        """
        raise NotImplementedError

    @abstractmethod
    def is_token_valid(self) -> bool:
        """Quick local check: does the configured access token look fresh enough to use?"""
        raise NotImplementedError

    @abstractmethod
    def get_lot_size(self, symbol: str) -> int:
        """Return the current exchange lot size for the given index symbol.

        Args:
            symbol: "NIFTY" or "BANKNIFTY".

        Returns:
            Positive integer lot size (e.g. 65 for NIFTY at 2026 settings).
        """
        raise NotImplementedError

    @abstractmethod
    def get_spot_price(self, symbol: str) -> float:
        """Return the latest tradable spot LTP for the given index symbol."""
        raise NotImplementedError

    @abstractmethod
    def get_5min_candles(self, instrument_key: str, n_candles: int) -> pd.DataFrame:
        """Return the most recent N 5-minute candles for an instrument.

        Returns:
            DataFrame with columns exactly:
                [timestamp, open, high, low, close, volume, oi]
            Sorted oldest -> newest. Timestamps are timezone-aware (Asia/Kolkata).
        """
        raise NotImplementedError

    @abstractmethod
    def get_option_chain(self, symbol: str, expiry: str) -> pd.DataFrame:
        """Return the option chain snapshot for the given index and expiry.

        Args:
            symbol: "NIFTY" or "BANKNIFTY".
            expiry: ISO date string (YYYY-MM-DD).

        Returns:
            DataFrame with at least: strike, ce_ltp, pe_ltp, ce_oi, pe_oi,
            ce_volume, pe_volume, ce_instrument_key, pe_instrument_key.
        """
        raise NotImplementedError

    @abstractmethod
    def get_india_vix(self) -> float:
        """Return the latest India VIX value (read once at 9:15 AM in production)."""
        raise NotImplementedError

    @abstractmethod
    def get_atm_strike(self, symbol: str) -> int:
        """Return the ATM strike for the given index based on current spot."""
        raise NotImplementedError

    @abstractmethod
    def get_broker_name(self) -> str:
        """Short broker identifier, e.g. 'kite' or 'upstox'."""
        raise NotImplementedError
