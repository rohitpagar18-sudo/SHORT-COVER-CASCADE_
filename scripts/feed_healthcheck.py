"""Manual pre-market feed healthcheck.

Connects to the active broker, then runs a series of real-data checks:
spot prices, India VIX, lot sizes (compared against config), ATM strike.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from src.config_loader import ConfigError, load_config
from src.data.feed_factory import connect_feed

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def _check(name: str, fn) -> tuple[bool, object]:
    try:
        value = fn()
        print(f"  [PASS] {name}: {value}")
        return True, value
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        return False, None


def main() -> int:
    print("=== Feed Health Check ===")
    try:
        config = load_config(CONFIG_PATH)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not SECRETS_PATH.exists():
        print(f"ERROR: secrets file not found at {SECRETS_PATH}", file=sys.stderr)
        return 1
    load_dotenv(SECRETS_PATH)

    print(f"Active feed: {config.feeds.active_feed}")

    try:
        feed = connect_feed(config)
    except Exception as e:
        print(f"ERROR: connection failed: {e}", file=sys.stderr)
        return 1

    results: list[bool] = []
    mismatch = False

    ok, _ = _check("get_spot_price(NIFTY)", lambda: feed.get_spot_price("NIFTY"))
    results.append(ok)

    ok, _ = _check(
        "get_spot_price(BANKNIFTY)", lambda: feed.get_spot_price("BANKNIFTY")
    )
    results.append(ok)

    ok, vix = _check("get_india_vix()", feed.get_india_vix)
    if ok and isinstance(vix, (int, float)) and vix == -1.0:
        print("  WARNING: India VIX returned sentinel -1.0 (fetch failed)")
    results.append(ok)

    ok, nifty_lot = _check("get_lot_size(NIFTY)", lambda: feed.get_lot_size("NIFTY"))
    if ok and nifty_lot != config.instruments.nifty_lot_size:
        print(
            f"  WARNING: NIFTY lot size from broker ({nifty_lot}) != "
            f"config ({config.instruments.nifty_lot_size})"
        )
        mismatch = True
    results.append(ok)

    ok, bn_lot = _check(
        "get_lot_size(BANKNIFTY)", lambda: feed.get_lot_size("BANKNIFTY")
    )
    if ok and bn_lot != config.instruments.banknifty_lot_size:
        print(
            f"  WARNING: BANKNIFTY lot size from broker ({bn_lot}) != "
            f"config ({config.instruments.banknifty_lot_size})"
        )
        mismatch = True
    results.append(ok)

    ok, _ = _check("get_atm_strike(NIFTY)", lambda: feed.get_atm_strike("NIFTY"))
    results.append(ok)

    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Summary: {passed}/{total} checks passed")
    if mismatch:
        print("WARNING: Lot size mismatch! Update config.yaml before trading.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
