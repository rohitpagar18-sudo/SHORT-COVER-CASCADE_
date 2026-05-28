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
    def get_5min_candles(
        self, instrument_key: str, lookback_candles: int = 100
    ) -> pd.DataFrame:
        """Return 5-min candles, fetching enough history to cover ``lookback_candles``.

        Implementations may return MORE rows than requested but must not
        return fewer (subject to broker history availability). Callers
        rely on this for indicators like RSI MA that need 33+ candles
        and for gap detection that needs prev-day's last candle.

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
    def get_india_vix_with_timestamp(self) -> tuple[float, str | None]:
        """Return ``(vix_value, last_trade_time_iso)`` for the holiday-guard
        second check. ``last_trade_time_iso`` is the IST ISO timestamp of
        the most recent VIX tick, or ``None`` if the broker does not
        expose one. Returns ``(-1.0, None)`` on any error so callers can
        treat it as 'unknown — trust the first check'.
        """
        raise NotImplementedError

    @abstractmethod
    def get_atm_strike(self, symbol: str) -> int:
        """Return the ATM strike for the given index based on current spot."""
        raise NotImplementedError

    @abstractmethod
    def get_broker_name(self) -> str:
        """Short broker identifier, e.g. 'kite' or 'upstox'."""
        raise NotImplementedError

    @abstractmethod
    def get_spot_instrument_key(self, symbol: str) -> str:
        """Broker-specific instrument key for the spot index's 5-min candles.

        Strategy code calls ``get_5min_candles(feed.get_spot_instrument_key(sym), ...)``
        when it needs spot candles (e.g. C0 spot VWAP). The exact string
        is opaque to strategy code — Kite returns its numeric instrument
        token as a string, Upstox returns its ``NSE_INDEX|...`` key.

        Args:
            symbol: "NIFTY" or "BANKNIFTY".

        Returns:
            Opaque broker-specific identifier that ``get_5min_candles``
            accepts.
        """
        raise NotImplementedError

    @abstractmethod
    def list_expiries(self, symbol: str) -> list:
        """Return the sorted, deduplicated list of upcoming expiry dates
        (``datetime.date``) for the given index symbol.

        Source-of-truth: each broker's instrument dump. Past expiries
        are filtered out by the caller — implementations may include or
        exclude them at their discretion, but must be consistent.

        Args:
            symbol: "NIFTY" or "BANKNIFTY".

        Returns:
            list of ``datetime.date`` sorted oldest first.
        """
        raise NotImplementedError
