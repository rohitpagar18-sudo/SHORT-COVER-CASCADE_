"""Unit tests for KiteFeed. All broker interactions are mocked."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.config_loader import AppConfig
from src.data.kite_feed import IST, KiteFeed


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _yesterday() -> str:
    return (datetime.now(IST).date() - timedelta(days=1)).isoformat()


def test_is_token_valid_today(monkeypatch: pytest.MonkeyPatch, kite_config: AppConfig) -> None:
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "tok-abc")
    monkeypatch.setenv("KITE_TOKEN_DATE", _today())
    feed = KiteFeed(kite_config)
    assert feed.is_token_valid() is True


def test_is_token_valid_yesterday(monkeypatch: pytest.MonkeyPatch, kite_config: AppConfig) -> None:
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "tok-abc")
    monkeypatch.setenv("KITE_TOKEN_DATE", _yesterday())
    feed = KiteFeed(kite_config)
    assert feed.is_token_valid() is False


def test_is_token_valid_missing(monkeypatch: pytest.MonkeyPatch, kite_config: AppConfig) -> None:
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "tok-abc")
    monkeypatch.setenv("KITE_TOKEN_DATE", "")
    feed = KiteFeed(kite_config)
    assert feed.is_token_valid() is False


def test_get_atm_strike_nifty(kite_config: AppConfig) -> None:
    feed = KiteFeed(kite_config)
    feed._kite = MagicMock()
    # Round-to-nearest-50: 24520 is 20 away from 24500, 30 from 24550 -> 24500.
    feed._kite.ltp.return_value = {"NSE:NIFTY 50": {"last_price": 24520.0}}
    assert feed.get_atm_strike("NIFTY") == 24500


def test_get_atm_strike_banknifty(kite_config: AppConfig) -> None:
    feed = KiteFeed(kite_config)
    feed._kite = MagicMock()
    feed._kite.ltp.return_value = {"NSE:NIFTY BANK": {"last_price": 54312.0}}
    assert feed.get_atm_strike("BANKNIFTY") == 54300


def test_connect_stale_token(monkeypatch: pytest.MonkeyPatch, kite_config: AppConfig) -> None:
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "tok-abc")
    monkeypatch.setenv("KITE_TOKEN_DATE", _yesterday())
    feed = KiteFeed(kite_config)
    with pytest.raises(RuntimeError, match="Kite token is stale"):
        feed.connect()


def test_get_spot_price(kite_config: AppConfig) -> None:
    feed = KiteFeed(kite_config)
    feed._kite = MagicMock()
    feed._kite.ltp.return_value = {"NSE:NIFTY 50": {"last_price": 24555.25}}
    assert feed.get_spot_price("NIFTY") == 24555.25
    feed._kite.ltp.assert_called_once_with(["NSE:NIFTY 50"])
