"""Kite (Zerodha) data feed adapter.

All imports of kiteconnect happen lazily inside connect() / methods so that
importing this module never loads the SDK when the active feed is Upstox.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from src.config_loader import AppConfig
from src.data.base_feed import BaseFeed

IST = ZoneInfo("Asia/Kolkata")

_KITE_SPOT_INSTRUMENT = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
}
_KITE_NAME_LOOKUP = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
}
_STRIKE_INTERVAL = {"NIFTY": 50, "BANKNIFTY": 100}


class KiteFeed(BaseFeed):
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._kite: Any = None
        self._connected = False
        self._lot_sizes: dict[str, int] = {}
        self._instruments_cache: list[dict[str, Any]] | None = None

    def get_broker_name(self) -> str:
        return "kite"

    def is_token_valid(self) -> bool:
        token = os.getenv("KITE_ACCESS_TOKEN", "").strip()
        token_date = os.getenv("KITE_TOKEN_DATE", "").strip()
        if not token or not token_date:
            return False
        today_ist = datetime.now(IST).date().isoformat()
        return token_date == today_ist

    def connect(self) -> bool:
        if not self.is_token_valid():
            raise RuntimeError(
                "Kite token is stale. Run: python scripts/refresh_token_kite.py"
            )

        from kiteconnect import KiteConnect

        api_key = os.getenv("KITE_API_KEY", "").strip()
        access_token = os.getenv("KITE_ACCESS_TOKEN", "").strip()

        self._kite = KiteConnect(api_key=api_key)
        self._kite.set_access_token(access_token)
        try:
            self._kite.profile()
        except Exception as e:
            raise RuntimeError(f"Kite connection failed: {e}") from e

        self._connected = True
        logger.info("Kite feed connected")
        return True

    def get_spot_price(self, symbol: str) -> float:
        instrument = _KITE_SPOT_INSTRUMENT[symbol]
        resp = self._kite.ltp([instrument])
        return float(resp[instrument]["last_price"])

    def _load_instruments(self) -> list[dict[str, Any]]:
        if self._instruments_cache is None:
            self._instruments_cache = list(self._kite.instruments("NFO"))
        return self._instruments_cache

    def get_lot_size(self, symbol: str) -> int:
        if symbol in self._lot_sizes:
            return self._lot_sizes[symbol]

        try:
            instruments = self._load_instruments()
            name = _KITE_NAME_LOOKUP[symbol]
            today = date.today()
            futs = [
                row
                for row in instruments
                if row.get("name") == name
                and row.get("instrument_type") == "FUT"
                and row.get("expiry")
                and self._as_date(row["expiry"]) >= today
            ]
            if not futs:
                raise RuntimeError(f"No upcoming FUT instrument found for {symbol}")
            futs.sort(key=lambda r: self._as_date(r["expiry"]))
            lot_size = int(futs[0]["lot_size"])
            self._lot_sizes[symbol] = lot_size
            logger.info("Lot size for {} from Kite instrument dump: {}", symbol, lot_size)
            return lot_size
        except Exception as e:
            fallback = (
                self._config.instruments.nifty_lot_size
                if symbol == "NIFTY"
                else self._config.instruments.banknifty_lot_size
            )
            logger.warning(
                "Lot-size fetch failed for {} ({}); falling back to config value {}",
                symbol,
                e,
                fallback,
            )
            self._lot_sizes[symbol] = fallback
            return fallback

    @staticmethod
    def _as_date(v: Any) -> date:
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        return datetime.fromisoformat(str(v)).date()

    def get_5min_candles(self, instrument_key: str, n_candles: int) -> pd.DataFrame:
        token = self._get_instrument_token(instrument_key)
        now = datetime.now(IST)
        from_date = now - timedelta(minutes=n_candles * 5 + 15)

        retries = self._config.bot.api_retry_count
        delay = self._config.bot.api_retry_delay_seconds
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                data = self._kite.historical_data(
                    token,
                    from_date,
                    now,
                    interval="5minute",
                    oi=True,
                )
                break
            except Exception as e:
                last_err = e
                logger.warning(
                    "Kite historical_data failed (attempt {}/{}): {}",
                    attempt + 1,
                    retries + 1,
                    e,
                )
                if attempt < retries:
                    time.sleep(delay)
        else:
            raise RuntimeError(
                f"Kite historical_data failed after {retries + 1} attempts: {last_err}"
            )

        if not data:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
            )

        df = pd.DataFrame(data)
        df = df.rename(columns={"date": "timestamp"})
        if "oi" not in df.columns:
            df["oi"] = 0
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize(IST)
        else:
            df["timestamp"] = df["timestamp"].dt.tz_convert(IST)
        df = df[["timestamp", "open", "high", "low", "close", "volume", "oi"]]
        df = df.sort_values("timestamp").reset_index(drop=True)
        if n_candles > 0:
            df = df.tail(n_candles).reset_index(drop=True)
        return df

    def get_option_chain(self, symbol: str, expiry: str) -> pd.DataFrame:
        instruments = self._load_instruments()
        name = _KITE_NAME_LOOKUP[symbol]
        target_expiry = datetime.fromisoformat(expiry).date()
        rows: list[dict[str, Any]] = []
        for row in instruments:
            if row.get("name") != name:
                continue
            if row.get("instrument_type") not in ("CE", "PE"):
                continue
            if not row.get("expiry"):
                continue
            if self._as_date(row["expiry"]) != target_expiry:
                continue
            rows.append(
                {
                    "strike": float(row["strike"]),
                    "instrument_type": row["instrument_type"],
                    "instrument_token": int(row["instrument_token"]),
                    "tradingsymbol": row["tradingsymbol"],
                    "expiry": target_expiry.isoformat(),
                    "lot_size": int(row["lot_size"]),
                }
            )
        df = pd.DataFrame(
            rows,
            columns=[
                "strike",
                "instrument_type",
                "instrument_token",
                "tradingsymbol",
                "expiry",
                "lot_size",
            ],
        )
        df = df.sort_values("strike").reset_index(drop=True)
        return df

    def get_india_vix(self) -> float:
        try:
            resp = self._kite.ltp(["NSE:INDIA VIX"])
            return float(resp["NSE:INDIA VIX"]["last_price"])
        except Exception as e:
            logger.warning("Kite India VIX fetch failed: {}", e)
            return -1.0

    def get_atm_strike(self, symbol: str) -> int:
        spot = self.get_spot_price(symbol)
        interval = _STRIKE_INTERVAL[symbol]
        return int(round(spot / interval) * interval)

    def _get_instrument_token(self, trading_symbol: str, exchange: str = "NFO") -> int:
        if trading_symbol.isdigit():
            return int(trading_symbol)
        if ":" in trading_symbol:
            _, sym = trading_symbol.split(":", 1)
        else:
            sym = trading_symbol
        instruments = self._load_instruments()
        for row in instruments:
            if row.get("tradingsymbol") == sym:
                return int(row["instrument_token"])
        raise ValueError(f"Instrument symbol not found in Kite NFO dump: {trading_symbol}")
