"""List upcoming NIFTY / BankNifty option expiries from the broker's
NFO instrument dump.

Source-of-truth utility: whatever expiries the exchange has actually
listed will appear here. The weekly/monthly pattern is derived from the
data, not hardcoded — if SEBI changes the rules, this script reflects
reality on the next run.

Usage:
    python scripts/list_expiries.py
"""

from __future__ import annotations

import sys
from calendar import monthrange
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config, load_secrets
from src.data.feed_factory import connect_feed

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"

NIFTY_SHOW = 8
BANKNIFTY_SHOW = 4


def _as_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.fromisoformat(str(v)).date()


def is_last_weekday_of_month(d: date) -> bool:
    """True iff no later date in d's month falls on the same weekday."""
    days_in_month = monthrange(d.year, d.month)[1]
    return d.day + 7 > days_in_month


def unique_future_expiries(
    instruments: Iterable[dict[str, Any]], name: str, today: date
) -> list[date]:
    seen: set[date] = set()
    for row in instruments:
        if row.get("name") != name:
            continue
        if row.get("instrument_type") not in ("CE", "PE"):
            continue
        exp = row.get("expiry")
        if not exp:
            continue
        d = _as_date(exp)
        if d >= today:
            seen.add(d)
    return sorted(seen)


def detect_pattern(expiries: list[date]) -> str:
    """Derive 'weekly <Day>' vs 'monthly last-<Day>' from the data."""
    if not expiries:
        return "no upcoming expiries"
    weekday = Counter(d.strftime("%A") for d in expiries).most_common(1)[0][0]
    per_month = Counter((d.year, d.month) for d in expiries)
    avg_per_month = sum(per_month.values()) / len(per_month)
    if avg_per_month > 1.5:
        return f"weekly {weekday}"
    return f"monthly last-{weekday}"


def print_expiries(label: str, expiries: list[date], n: int) -> None:
    print(f"{label} expiries (next {n}):")
    if not expiries:
        print("  (none found)")
        print()
        return
    for d in expiries[:n]:
        weekday = d.strftime("%A")
        suffix = ", monthly" if is_last_weekday_of_month(d) else ""
        print(f"  {d.isoformat()} ({weekday}{suffix})")
    print()


def main() -> int:
    try:
        load_secrets(SECRETS_PATH)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    config = load_config(CONFIG_PATH)
    feed = connect_feed(config)

    broker = feed.get_broker_name()
    if broker == "kite":
        instruments = feed._load_instruments()
    else:
        print(
            f"ERROR: list_expiries.py currently supports Kite only "
            f"(active feed is '{broker}'). Set feeds.active_feed: kite "
            "in config/config.yaml and rerun.",
            file=sys.stderr,
        )
        return 1

    today = datetime.now().date()
    nifty = unique_future_expiries(instruments, "NIFTY", today)
    banknifty = unique_future_expiries(instruments, "BANKNIFTY", today)

    print_expiries("NIFTY", nifty, NIFTY_SHOW)
    print_expiries("BANKNIFTY", banknifty, BANKNIFTY_SHOW)

    print(
        f"NIFTY pattern: {detect_pattern(nifty)} | "
        f"BANKNIFTY pattern: {detect_pattern(banknifty)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
