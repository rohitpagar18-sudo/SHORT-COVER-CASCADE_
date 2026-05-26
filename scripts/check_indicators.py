"""Live calibration script — prints indicator values for one strike.

Usage:
    python scripts/check_indicators.py --symbol NIFTY --strike 24050 \
        --option-type CE --expiry 2026-05-29
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config, load_secrets
from src.data.feed_factory import connect_feed
from src.indicators.calculator import get_latest_snapshot

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=["NIFTY", "BANKNIFTY"], required=True)
    parser.add_argument("--strike", type=int, required=True,
                        help="Strike price, e.g. 24500")
    parser.add_argument("--option-type", choices=["CE", "PE"], required=True)
    parser.add_argument("--expiry", required=True,
                        help="Expiry date YYYY-MM-DD")
    parser.add_argument("--candles", type=int, default=50,
                        help="Number of recent candles to fetch (default 50)")
    args = parser.parse_args()

    try:
        load_secrets(SECRETS_PATH)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    config = load_config(CONFIG_PATH)
    feed = connect_feed(config)

    chain = feed.get_option_chain(args.symbol, args.expiry)
    row = chain[
        (chain["strike"] == args.strike)
        & (chain["instrument_type"] == args.option_type)
    ]
    if len(row) == 0:
        print(f"ERROR: Strike {args.strike}{args.option_type} not found in {args.symbol} {args.expiry} chain")
        return 1

    if "instrument_key" in row.columns:
        instrument_key = row.iloc[0]["instrument_key"]
    else:
        instrument_key = row.iloc[0]["instrument_token"]

    print(f"Fetching {args.candles} candles for {args.symbol} {args.strike}{args.option_type} expiry {args.expiry}...")
    df = feed.get_5min_candles(str(instrument_key), args.candles)
    print(f"Fetched {len(df)} candles, latest timestamp: {df['timestamp'].iloc[-1]}")

    print()
    print("Last 5 candles:")
    print(df.tail(5).to_string(index=False))
    print()

    snap = get_latest_snapshot(df)
    print("=" * 60)
    print(f"  Latest indicators for {args.symbol} {args.strike}{args.option_type}")
    print("=" * 60)
    print(f"  Timestamp    : {snap.timestamp}")
    print(f"  OHLC         : {snap.open:.2f} / {snap.high:.2f} / {snap.low:.2f} / {snap.close:.2f}")
    print(f"  Candle color : {'GREEN' if snap.is_green else 'RED'}")
    print(f"  VWAP (hlc3)  : {snap.vwap:.2f}    ({'ABOVE' if snap.close > snap.vwap else 'BELOW'})")
    print(f"  RSI(14)      : {snap.rsi:.2f}")
    print(f"  RSI MA(20)   : {snap.rsi_ma:.2f}    (RSI {'ABOVE' if snap.rsi > snap.rsi_ma else 'BELOW'} MA)")
    print(f"  OI           : {snap.oi:,.0f}")
    print(f"  OI MA(20)    : {snap.oi_ma:,.0f}    (OI  {'BELOW' if snap.oi < snap.oi_ma else 'ABOVE'} MA)")
    print(f"  Volume       : {snap.volume:,.0f}")
    print(f"  Volume MA(20): {snap.volume_ma:,.0f}    (Vol {'ABOVE' if snap.volume > snap.volume_ma else 'BELOW'} MA)")
    print("=" * 60)
    print()
    print("Now open the same strike on Kite chart and verify these values match within:")
    print("  VWAP: ±0.5%   RSI: ±2 points   MAs: ±1%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
