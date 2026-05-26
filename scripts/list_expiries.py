"""List upcoming NIFTY / BankNifty option expiries from the active broker.

Source-of-truth utility: whatever expiries the exchange has actually
listed will appear here. Weekly vs monthly pattern is derived from the
data — if SEBI changes the rules tomorrow, this script reflects reality
on the next run.

Usage::

    python scripts/list_expiries.py            # next 8 expiries per symbol
    python scripts/list_expiries.py --all      # all expiries returned by broker
"""

from __future__ import annotations

import argparse
import calendar
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config, load_secrets
from src.data.expiry_resolver import get_all_expiries, get_expiry_summary
from src.data.feed_factory import connect_feed

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="List broker-listed option expiries.")
    p.add_argument(
        "--all",
        action="store_true",
        help="Print every expiry the broker returns (diagnostic).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        load_secrets(SECRETS_PATH)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    config = load_config(CONFIG_PATH)
    feed = connect_feed(config)

    summary = get_expiry_summary(feed, n=8)
    print("=" * 60)
    print(f"  Expiry Calendar (source: {feed.get_broker_name()})")
    print("=" * 60)
    for symbol, info in summary.items():
        print()
        print(f"{symbol}:")
        print(f"  Pattern detected : {info['weekday_pattern']}")
        print(f"  Total upcoming   : {info['total_count']}")

        if args.all:
            print("  All expiries:")
            all_expiries = get_all_expiries(feed, symbol)
            if not all_expiries:
                print("    (none found)")
                continue
            for d in all_expiries:
                day_name = calendar.day_name[d.weekday()]
                print(f"    {d.isoformat()}  ({day_name})")
        else:
            print("  Next 8 expiries:")
            expiries = info["next_expiries"]
            if not expiries:
                print("    (none found)")
                continue
            for d in expiries:
                day_name = calendar.day_name[d.weekday()]
                print(f"    {d.isoformat()}  ({day_name})")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
