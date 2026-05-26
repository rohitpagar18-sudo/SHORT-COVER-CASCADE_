"""Upstox data feed adapter.

All imports of upstox_client happen lazily inside connect() / methods so that
importing this module never loads the SDK when the active feed is Kite.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from src.config_loader import AppConfig
from src.data.base_feed import BaseFeed

IST = ZoneInfo("Asia/Kolkata")

_UPSTOX_SPOT_KEY = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
}
_UPSTOX_VIX_KEY = "NSE_INDEX|India VIX"
_STRIKE_INTERVAL = {"NIFTY": 50, "BANKNIFTY": 100}


class UpstoxFeed(BaseFeed):
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._api_client: Any = None
        self._market_quote_api: Any = None
        self._history_api: Any = None
        self._option_chain_api: Any = None
        self._connected = False
        self._lot_sizes: dict[str, int] = {}

    def get_broker_name(self) -> str:
        return "upstox"

    def is_token_valid(self) -> bool:
        token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
        token_date = os.getenv("UPSTOX_TOKEN_DATE", "").strip()
        if not token or not token_date:
            return False
        if self._config.feeds.upstox.token_validity_days >= 365:
            return True
        today_ist = datetime.now(IST).date().isoformat()
        return token_date == today_ist

    def connect(self) -> bool:
        if not self.is_token_valid():
            raise RuntimeError(
                "Upstox token is invalid or missing. Run: "
                "python scripts/refresh_token_upstox.py --manual"
            )

        import upstox_client

        access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
        configuration = upstox_client.Configuration()
        configuration.access_token = access_token

        self._api_client = upstox_client.ApiClient(configuration)
        self._market_quote_api = upstox_client.MarketQuoteApi(self._api_client)
        self._history_api = upstox_client.HistoryApi(self._api_client)
        self._option_chain_api = upstox_client.OptionChainApi(self._api_client)

        try:
            self._market_quote_api.get_full_market_quote(
                symbol=_UPSTOX_SPOT_KEY["NIFTY"], api_version="2.0"
            )
        except Exception as e:
            raise RuntimeError(f"Upstox connection failed: {e}") from e

        self._connected = True
        logger.info("Upstox feed connected")
        return True

    @staticmethod
    def _extract_last_price(resp: Any, instrument_key: str) -> float:
        data = getattr(resp, "data", None)
        if data is None and isinstance(resp, dict):
            data = resp.get("data")
        if data is None:
            raise RuntimeError(f"Upstox quote response missing data field: {resp}")
        # Upstox often returns keys with a colon variant (NSE_INDEX:Nifty 50)
        candidates = [
            instrument_key,
            instrument_key.replace("|", ":"),
        ]
        record = None
        if isinstance(data, dict):
            for k in candidates:
                if k in data:
                    record = data[k]
                    break
            if record is None and len(data) == 1:
                record = next(iter(data.values()))
        else:
            record = data
        if record is None:
            raise RuntimeError(f"Upstox quote response missing record for {instrument_key}")
        last_price = getattr(record, "last_price", None)
        if last_price is None and isinstance(record, dict):
            last_price = record.get("last_price")
        if last_price is None:
            raise RuntimeError(f"Upstox quote response missing last_price for {instrument_key}")
        return float(last_price)

    def get_spot_price(self, symbol: str) -> float:
        instrument_key = _UPSTOX_SPOT_KEY[symbol]
        resp = self._market_quote_api.get_full_market_quote(
            symbol=instrument_key, api_version="2.0"
        )
        return self._extract_last_price(resp, instrument_key)

    def get_lot_size(self, symbol: str) -> int:
        if symbol in self._lot_sizes:
            return self._lot_sizes[symbol]

        fallback = (
            self._config.instruments.nifty_lot_size
            if symbol == "NIFTY"
            else self._config.instruments.banknifty_lot_size
        )
        try:
            df = self._fetch_first_option_chain(symbol)
            if df.empty or "lot_size" not in df.columns:
                raise RuntimeError("empty option chain or missing lot_size")
            lot_size = int(df.iloc[0]["lot_size"])
            self._lot_sizes[symbol] = lot_size
            logger.info(
                "Lot size for {} from Upstox option chain: {}", symbol, lot_size
            )
            return lot_size
        except Exception as e:
            logger.warning(
                "Lot-size fetch failed for {} ({}); falling back to config value {}",
                symbol,
                e,
                fallback,
            )
            self._lot_sizes[symbol] = fallback
            return fallback

    def _fetch_first_option_chain(self, symbol: str) -> pd.DataFrame:
        # Best-effort: pull the first available expiry for the index.
        instrument_key = _UPSTOX_SPOT_KEY[symbol]
        resp = self._option_chain_api.get_option_contracts(
            instrument_key=instrument_key
        )
        data = getattr(resp, "data", None) or []
        rows: list[dict[str, Any]] = []
        for item in data:
            row = self._option_row_to_dict(item)
            if row is not None:
                rows.append(row)
            if len(rows) >= 1:
                break
        return pd.DataFrame(rows)

    @staticmethod
    def _option_row_to_dict(item: Any) -> dict[str, Any] | None:
        get = (
            (lambda k: item.get(k))
            if isinstance(item, dict)
            else (lambda k: getattr(item, k, None))
        )
        strike = get("strike_price")
        if strike is None:
            return None
        return {
            "strike": float(strike),
            "instrument_type": get("instrument_type") or "",
            "instrument_key": get("instrument_key") or "",
            "trading_symbol": get("trading_symbol") or "",
            "expiry": str(get("expiry") or ""),
            "lot_size": int(get("lot_size") or 0),
        }

    def get_5min_candles(self, instrument_key: str, n_candles: int = 0) -> pd.DataFrame:
        """Return 5-min candles for today's full intraday session.

        ``n_candles`` is kept for BaseFeed interface compatibility but
        is a HINT only — this method ALWAYS returns the full session
        Upstox's intraday endpoint exposes. Required for session-
        anchored VWAP to compute from 09:15, not from a sliding window.
        """
        retries = self._config.bot.api_retry_count
        delay = self._config.bot.api_retry_delay_seconds
        last_err: Exception | None = None
        resp = None
        for attempt in range(retries + 1):
            try:
                resp = self._history_api.get_intra_day_candle_data(
                    instrument_key=instrument_key,
                    interval="5minute",
                    api_version="2.0",
                )
                break
            except Exception as e:
                last_err = e
                logger.warning(
                    "Upstox intraday candle fetch failed (attempt {}/{}): {}",
                    attempt + 1,
                    retries + 1,
                    e,
                )
                if attempt < retries:
                    time.sleep(delay)
        else:
            raise RuntimeError(
                f"Upstox candle fetch failed after {retries + 1} attempts: {last_err}"
            )

        data = getattr(resp, "data", None)
        candles = None
        if data is not None:
            candles = getattr(data, "candles", None)
            if candles is None and isinstance(data, dict):
                candles = data.get("candles")
        if not candles:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
            )

        rows: list[dict[str, Any]] = []
        for c in candles:
            # Upstox candle: [timestamp, open, high, low, close, volume, oi]
            ts_raw = c[0]
            if isinstance(ts_raw, str):
                ts = pd.to_datetime(ts_raw)
            else:
                ts = pd.Timestamp(ts_raw)
            if ts.tzinfo is None:
                ts = ts.tz_localize(IST)
            else:
                ts = ts.tz_convert(IST)
            rows.append(
                {
                    "timestamp": ts,
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "oi": float(c[6]) if len(c) > 6 else 0.0,
                }
            )
        df = pd.DataFrame(
            rows,
            columns=["timestamp", "open", "high", "low", "close", "volume", "oi"],
        )
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def get_option_chain(self, symbol: str, expiry: str) -> pd.DataFrame:
        instrument_key = _UPSTOX_SPOT_KEY[symbol]
        resp = self._option_chain_api.get_option_chain_data(
            instrument_key=instrument_key, expiry_date=expiry
        )
        data = getattr(resp, "data", None) or []
        rows: list[dict[str, Any]] = []
        for item in data:
            row = self._option_row_to_dict(item)
            if row is not None:
                rows.append(row)
        df = pd.DataFrame(
            rows,
            columns=[
                "strike",
                "instrument_type",
                "instrument_key",
                "trading_symbol",
                "expiry",
                "lot_size",
            ],
        )
        df = df.sort_values("strike").reset_index(drop=True)
        return df

    def get_india_vix(self) -> float:
        try:
            resp = self._market_quote_api.get_full_market_quote(
                symbol=_UPSTOX_VIX_KEY, api_version="2.0"
            )
            return self._extract_last_price(resp, _UPSTOX_VIX_KEY)
        except Exception as e:
            logger.warning("Upstox India VIX fetch failed: {}", e)
            return -1.0

    def get_atm_strike(self, symbol: str) -> int:
        spot = self.get_spot_price(symbol)
        interval = _STRIKE_INTERVAL[symbol]
        return int(round(spot / interval) * interval)

    def get_spot_instrument_key(self, symbol: str) -> str:
        if symbol not in _UPSTOX_SPOT_KEY:
            raise ValueError(f"Unknown spot symbol for Upstox: {symbol}")
        return _UPSTOX_SPOT_KEY[symbol]

    def list_expiries(self, symbol: str) -> list:
        from datetime import date as _date, datetime as _dt

        instrument_key = _UPSTOX_SPOT_KEY[symbol]
        try:
            resp = self._option_chain_api.get_option_contracts(
                instrument_key=instrument_key
            )
        except Exception as e:
            logger.warning("Upstox list_expiries failed for {}: {}", symbol, e)
            return []

        data = getattr(resp, "data", None) or []
        today = _dt.now(IST).date()
        seen: set = set()
        for item in data:
            getter = (
                (lambda k: item.get(k))
                if isinstance(item, dict)
                else (lambda k: getattr(item, k, None))
            )
            raw = getter("expiry")
            if not raw:
                continue
            try:
                if isinstance(raw, _dt):
                    d = raw.date()
                elif isinstance(raw, _date):
                    d = raw
                else:
                    d = _dt.fromisoformat(str(raw)[:10]).date()
            except Exception:
                continue
            if d >= today:
                seen.add(d)
        return sorted(seen)
