"""Bot entry point.

Phase 1 behavior: load config + secrets, configure logging, instantiate the
active feed via feed_factory.get_feed(), verify token validity (without
calling broker APIs), print a startup banner, exit.

Connect-to-broker happens in Phase 5 when the orchestrator starts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "bot.log"

from src.config_loader import AppConfig, ConfigError, load_config, load_secrets
from src.data.feed_factory import get_feed


def _configure_logging(level: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=level)
    logger.add(
        LOG_FILE,
        level=level,
        rotation="10 MB",
        retention="14 days",
        enqueue=False,
        backtrace=True,
        diagnose=False,
    )


def _print_banner(config: AppConfig, token_date: str | None) -> None:
    active = config.feeds.active_feed
    mode = config.mode
    instruments = []
    if config.instruments.nifty_enabled:
        instruments.append("NIFTY")
    if config.instruments.banknifty_enabled:
        instruments.append("BANKNIFTY")

    line = "=" * 62
    banner = [
        line,
        "  SHORT COVER CASCADE — Bot Startup",
        line,
        f"  Active broker     : {active}",
        f"  alert_mode        : {'ON' if mode.alert_mode else 'OFF'}",
        f"  order_place_mode  : {'ON' if mode.order_place_mode else 'OFF'}",
        f"  paper_trade_mode  : {'ON' if mode.paper_trade_mode else 'OFF'}",
        f"  Instruments       : {', '.join(instruments) if instruments else '(none enabled)'}",
        f"  Token date ({active:<6}): {token_date or '(missing)'}",
        line,
    ]
    for ln in banner:
        print(ln)


def _resolve_token_date(active_feed: str) -> str | None:
    var = "KITE_TOKEN_DATE" if active_feed == "kite" else "UPSTOX_TOKEN_DATE"
    val = os.getenv(var, "").strip()
    return val or None


def main() -> int:
    try:
        load_secrets(SECRETS_PATH)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        config = load_config(CONFIG_PATH)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    _configure_logging(config.logging.log_level)
    logger.info("Config loaded from {}", CONFIG_PATH)

    active = config.feeds.active_feed
    token_date = _resolve_token_date(active)
    _print_banner(config, token_date)

    feed = get_feed(config)
    if not feed.is_token_valid():
        if active == "kite":
            print(
                "ERROR: Kite token is stale. Run: "
                "python scripts\\refresh_token_kite.py",
                file=sys.stderr,
            )
        else:
            print(
                "ERROR: Upstox token missing. Run: "
                "python scripts\\refresh_token_upstox.py --manual",
                file=sys.stderr,
            )
        return 1

    print(f"Token check: PASS (active feed: {active})")
    print("Phase 1 complete — token valid, feed ready to connect")
    logger.info("Phase 1 startup complete (active broker: {})", active)
    return 0


if __name__ == "__main__":
    sys.exit(main())
