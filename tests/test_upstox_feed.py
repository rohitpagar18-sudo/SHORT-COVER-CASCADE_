"""Unit tests for UpstoxFeed. All broker interactions are mocked."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.config_loader import AppConfig
from src.data.upstox_feed import IST, UpstoxFeed


def _today() -> str:
    return datetime.now(IST).date().isoformat()


def _yesterday() -> str:
    return (datetime.now(IST).date() - timedelta(days=1)).isoformat()


def _config_with_validity(base: AppConfig, days: int) -> AppConfig:
    upstox = base.feeds.upstox.model_copy(update={"token_validity_days": days})
    feeds = base.feeds.model_copy(update={"upstox": upstox})
    return base.model_copy(update={"feeds": feeds})


def test_is_token_valid_365day(monkeypatch: pytest.MonkeyPatch, upstox_config: AppConfig) -> None:
    cfg = _config_with_validity(upstox_config, 365)
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "long-token")
    monkeypatch.setenv("UPSTOX_TOKEN_DATE", _yesterday())  # stale date doesn't matter
    feed = UpstoxFeed(cfg)
    assert feed.is_token_valid() is True


def test_is_token_valid_1day_today(monkeypatch: pytest.MonkeyPatch, upstox_config: AppConfig) -> None:
    cfg = _config_with_validity(upstox_config, 1)
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "tok-x")
    monkeypatch.setenv("UPSTOX_TOKEN_DATE", _today())
    feed = UpstoxFeed(cfg)
    assert feed.is_token_valid() is True


def test_is_token_valid_1day_yesterday(monkeypatch: pytest.MonkeyPatch, upstox_config: AppConfig) -> None:
    cfg = _config_with_validity(upstox_config, 1)
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "tok-x")
    monkeypatch.setenv("UPSTOX_TOKEN_DATE", _yesterday())
    feed = UpstoxFeed(cfg)
    assert feed.is_token_valid() is False


def test_get_atm_strike_nifty(upstox_config: AppConfig) -> None:
    feed = UpstoxFeed(upstox_config)
    feed._market_quote_api = MagicMock()
    fake = MagicMock()
    # Round-to-nearest-50: 24520 is 20 away from 24500, 30 from 24550 -> 24500.
    fake.data = {"NSE_INDEX|Nifty 50": MagicMock(last_price=24520.0)}
    feed._market_quote_api.get_full_market_quote.return_value = fake
    assert feed.get_atm_strike("NIFTY") == 24500


def test_get_atm_strike_banknifty(upstox_config: AppConfig) -> None:
    feed = UpstoxFeed(upstox_config)
    feed._market_quote_api = MagicMock()
    fake = MagicMock()
    fake.data = {"NSE_INDEX|Nifty Bank": MagicMock(last_price=54312.0)}
    feed._market_quote_api.get_full_market_quote.return_value = fake
    assert feed.get_atm_strike("BANKNIFTY") == 54300
