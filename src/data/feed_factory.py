"""Feed factory — selects and instantiates the active broker adapter.

CRITICAL: Only the active feed's module is imported. The inactive broker's
SDK is never touched.
"""

from __future__ import annotations

from src.config_loader import AppConfig, ConfigError
from src.data.base_feed import BaseFeed


def get_feed(config: AppConfig) -> BaseFeed:
    """Return a BaseFeed instance for the broker selected in config.feeds.active_feed."""
    active = config.feeds.active_feed
    if active == "kite":
        from src.data.kite_feed import KiteFeed
        return KiteFeed()
    if active == "upstox":
        from src.data.upstox_feed import UpstoxFeed
        return UpstoxFeed()
    raise ConfigError(
        f"Unsupported feeds.active_feed: {active!r} (must be 'kite' or 'upstox')"
    )
