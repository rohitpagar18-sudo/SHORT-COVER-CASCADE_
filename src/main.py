"""Bot entry point.

Phase 0 behavior: load config + secrets, configure logging, validate that
the active broker has a token-date recorded, print a startup banner, exit.

NO feed instantiation, NO API calls, NO strategy logic.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "bot.log"

from src.config_loader import AppConfig, ConfigError, load_config


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
        config = load_config(CONFIG_PATH)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    _configure_logging(config.logging.log_level)
    logger.info("Config loaded from {}", CONFIG_PATH)

    if not SECRETS_PATH.exists():
        print(f"ERROR: secrets file not found at {SECRETS_PATH}", file=sys.stderr)
        return 1
    load_dotenv(SECRETS_PATH)

    active = config.feeds.active_feed
    token_date = _resolve_token_date(active)
    if not token_date:
        var = "KITE_TOKEN_DATE" if active == "kite" else "UPSTOX_TOKEN_DATE"
        print(
            f"ERROR: {var} is missing from {SECRETS_PATH}. "
            f"Run scripts/refresh_token_{active}.py to set it.",
            file=sys.stderr,
        )
        return 1

    _print_banner(config, token_date)
    print("Phase 0 setup complete — bot foundation ready")
    logger.info("Phase 0 startup complete (active broker: {})", active)
    return 0


if __name__ == "__main__":
    sys.exit(main())
