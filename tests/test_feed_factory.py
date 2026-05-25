"""Unit tests for feed_factory. Confirms lazy/active-feed isolation."""

from __future__ import annotations

import sys
from typing import Iterator

import pytest

from src.config_loader import AppConfig, ConfigError, load_config
from src.data.feed_factory import get_feed
from src.data.kite_feed import KiteFeed
from src.data.upstox_feed import UpstoxFeed


@pytest.fixture
def _purge_inactive_feed_modules() -> Iterator[None]:
    """Remove cached broker modules so 'inactive SDK not imported' check is real."""
    to_drop = [
        m
        for m in list(sys.modules)
        if m == "upstox_client" or m.startswith("upstox_client.")
    ]
    for m in to_drop:
        sys.modules.pop(m, None)
    yield


def test_get_feed_kite(kite_config: AppConfig) -> None:
    feed = get_feed(kite_config)
    assert isinstance(feed, KiteFeed)
    assert feed.get_broker_name() == "kite"


def test_get_feed_upstox(upstox_config: AppConfig) -> None:
    feed = get_feed(upstox_config)
    assert isinstance(feed, UpstoxFeed)
    assert feed.get_broker_name() == "upstox"


def test_get_feed_invalid(config: AppConfig) -> None:
    # Bypass pydantic Literal validation by constructing the FeedsConfig with a
    # raw value; the factory itself must reject unknown feeds.
    class _FakeFeeds:
        active_feed = "hdfc"

    class _FakeConfig:
        feeds = _FakeFeeds()

    with pytest.raises(ConfigError, match="Unknown feed"):
        get_feed(_FakeConfig())  # type: ignore[arg-type]


def test_inactive_feed_not_imported(
    kite_config: AppConfig, _purge_inactive_feed_modules: None
) -> None:
    get_feed(kite_config)
    assert "upstox_client" not in sys.modules, (
        "upstox_client SDK must NOT be imported when active feed is kite"
    )
