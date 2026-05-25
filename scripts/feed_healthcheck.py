"""Manual pre-market feed healthcheck.

Loads config + secrets, instantiates the active broker feed via feed_factory,
and tries to connect. In Phase 0, connect() raises NotImplementedError —
that's expected; we print a status line and exit.

In Phase 1 this becomes a real connectivity test.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/feed_healthcheck.py` from project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from src.config_loader import ConfigError, load_config
from src.data.feed_factory import get_feed

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def main() -> int:
    try:
        config = load_config(CONFIG_PATH)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    load_dotenv(SECRETS_PATH)

    try:
        feed = get_feed(config)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    broker = feed.get_broker_name()
    try:
        feed.connect()
        print(f"Active feed: {broker} | Status: connected")
        return 0
    except NotImplementedError:
        print(
            f"Active feed: {broker} | Status: Phase 0 stub "
            "(connection logic comes in Phase 1)"
        )
        return 0
    except Exception as e:
        print(f"Active feed: {broker} | Status: ERROR — {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
