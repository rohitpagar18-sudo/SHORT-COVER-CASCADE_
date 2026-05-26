"""Run all 5 conditions (C0–C4) against a live strike and print a verdict.

This is the Phase 3 calibration tool: pick a strike, run the script,
read which conditions pass and which fail. Does NOT place orders or
send alerts — read-only.

Usage::

    python scripts/check_conditions.py --symbol NIFTY --strike 24050 \
        --option-type CE --expiry 2026-06-02

If ``--expiry`` is omitted, the nearest expiry from the broker is used.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.conditions.all_conditions import check_all_conditions
from src.config_loader import load_config, load_secrets
from src.data.expiry_resolver import get_next_expiry
from src.data.feed_factory import connect_feed
from src.indicators.calculator import get_latest_snapshot

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check all 5 conditions for a strike.")
    p.add_argument("--symbol", required=True, choices=["NIFTY", "BANKNIFTY"])
    p.add_argument("--strike", type=int, required=True)
    p.add_argument(
        "--option-type", required=True, choices=["CE", "PE"], dest="option_type"
    )
    p.add_argument(
        "--expiry",
        default=None,
        help="ISO date YYYY-MM-DD. If omitted, the nearest expiry is used.",
    )
    return p.parse_args()


def _resolve_expiry(feed, symbol: str, expiry_arg: str | None) -> date:
    if expiry_arg:
        return datetime.fromisoformat(expiry_arg).date()
    return get_next_expiry(feed, symbol)


def _find_option_instrument_key(
    chain: pd.DataFrame, strike: int, option_type: str
) -> str:
    if chain.empty:
        raise RuntimeError("Empty option chain returned from broker")
    cols = chain.columns

    typ_col = "instrument_type" if "instrument_type" in cols else None
    if typ_col is None:
        raise RuntimeError(f"Option chain missing instrument_type column. Columns: {list(cols)}")

    matches = chain[(chain["strike"] == float(strike)) & (chain[typ_col] == option_type)]
    if matches.empty:
        raise RuntimeError(
            f"Strike {strike} {option_type} not found in option chain. "
            f"Available strikes: {sorted(chain['strike'].unique())[:10]}..."
        )

    row = matches.iloc[0]
    if "instrument_token" in cols:
        return str(int(row["instrument_token"]))
    if "instrument_key" in cols:
        return str(row["instrument_key"])
    raise RuntimeError(
        f"Option chain row has no instrument_token or instrument_key. Columns: {list(cols)}"
    )


def _fmt_side(value: float, ref: float, label: str) -> str:
    if value > ref:
        return f"{value:,.2f} ({label} {ref:,.2f} — ABOVE)"
    if value < ref:
        return f"{value:,.2f} ({label} {ref:,.2f} — BELOW)"
    return f"{value:,.2f} ({label} {ref:,.2f} — EQUAL)"


def main() -> int:
    args = _parse_args()
    try:
        load_secrets(SECRETS_PATH)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    config = load_config(CONFIG_PATH)
    feed = connect_feed(config)

    expiry = _resolve_expiry(feed, args.symbol, args.expiry)

    spot_key = feed.get_spot_instrument_key(args.symbol)
    spot_df = feed.get_5min_candles(spot_key, n_candles=0)
    if spot_df.empty:
        print(f"ERROR: no spot candles returned for {args.symbol}", file=sys.stderr)
        return 1
    spot_snapshot = get_latest_snapshot(spot_df)

    chain = feed.get_option_chain(args.symbol, expiry.isoformat())
    option_key = _find_option_instrument_key(chain, args.strike, args.option_type)
    option_df = feed.get_5min_candles(option_key, n_candles=0)
    if option_df.empty:
        print(
            f"ERROR: no option candles returned for {args.symbol} {args.strike} "
            f"{args.option_type} {expiry}",
            file=sys.stderr,
        )
        return 1
    option_snapshot = get_latest_snapshot(option_df)

    result = check_all_conditions(
        option_snapshot=option_snapshot,
        spot_close=spot_snapshot.close,
        spot_vwap=spot_snapshot.vwap,
        option_type=args.option_type,
        config=config,
    )

    width = 60
    print("=" * width)
    print("  Condition Check Report")
    print(f"  {args.symbol} {expiry.isoformat()} {args.strike} {args.option_type}")
    print(f"  Time: {option_snapshot.timestamp} ({feed.get_broker_name()})")
    print("=" * width)
    print(
        f"Spot {args.symbol:<9} : "
        f"{_fmt_side(spot_snapshot.close, spot_snapshot.vwap, 'VWAP')}"
    )
    print(
        f"Option close       : "
        f"{_fmt_side(option_snapshot.close, option_snapshot.vwap, 'VWAP')}"
    )
    print(
        f"RSI(14)            : {option_snapshot.rsi:.2f} "
        f"(MA {option_snapshot.rsi_ma:.2f})"
    )
    print(
        f"OI                 : {option_snapshot.oi:,.0f} "
        f"(MA {option_snapshot.oi_ma:,.0f})"
    )
    print(
        f"Volume             : {option_snapshot.volume:,.0f} "
        f"(MA {option_snapshot.volume_ma:,.0f})"
    )
    print("-" * width)
    for r in result.results:
        mark = "✓" if r.passed else "✗"
        print(f"  {r.name} {mark}  {r.reason}")
    print("-" * width)
    n_pass = len(result.passed_conditions())
    verdict = "ALERT-READY ✓" if result.all_passed else "NO SIGNAL"
    print(f"SUMMARY: {n_pass}/5 conditions pass — {verdict}")
    if not result.all_passed:
        print(f"Failed: {', '.join(result.failed_conditions())}")
    print("=" * width)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
