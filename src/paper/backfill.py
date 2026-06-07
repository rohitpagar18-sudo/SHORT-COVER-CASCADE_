"""Phase 5D — Paper-trade backfill CLI.

One-shot replay over ``logs/alerts.jsonl`` + the existing
``data/replay_cache/`` (or live feed for cache misses on completed
days). Prints:

  - raw-alert count → episode count + collapse ratio
  - outcome distribution for the TAKEN set (headline)
  - outcome distribution across ALL alerts (diagnostic, biased by re-fires)

Re-runs are safe: ``paper_trades.jsonl`` is overwritten, the
user-owned ``paper_overrides.csv`` is left alone.

Usage:

    python -m src.paper.backfill
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from src.config_loader import load_config
from src.dashboard.candle_cache import get_or_fetch_candles
from src.paper.engine import outcome_distribution, run_paper_engine


def _print_distribution(label: str, dist: dict[str, int]) -> None:
    total = sum(dist.values()) or 1
    print(f"\n{label}")
    print("-" * len(label))
    if not dist:
        print("  (empty)")
        return
    for outcome, count in sorted(dist.items(), key=lambda kv: -kv[1]):
        pct = count / total * 100.0
        print(f"  {outcome:<12} {count:>4}  ({pct:5.1f}%)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.paper.backfill",
        description="Phase 5D — paper-trade backfill over collected alerts",
    )
    parser.add_argument(
        "--alerts",
        default="logs/alerts.jsonl",
        help="Path to alerts.jsonl (default: logs/alerts.jsonl)",
    )
    parser.add_argument(
        "--no-feed",
        action="store_true",
        help="Disable live-feed cache misses. Cache-only replay.",
    )
    args = parser.parse_args(argv)

    cfg = load_config("config/config.yaml")
    if not cfg.paper_trading.enabled:
        print("paper_trading.enabled is OFF — nothing to do.")
        return 0

    # Cache-only fallback when --no-feed or feed bootstrap fails.
    candle_source = None
    if not args.no_feed:
        try:
            from src.data.feed_factory import connect_feed

            feed = connect_feed(cfg)

            def _source(symbol, strike, option_type, expiry, trading_date):
                return get_or_fetch_candles(
                    feed=feed,
                    symbol=symbol,
                    strike=strike,
                    option_type=option_type,
                    expiry=expiry,
                    trading_date=trading_date,
                )

            candle_source = _source
        except Exception as e:
            logger.warning(
                f"backfill: feed bootstrap failed ({e}) — falling "
                "back to cache-only replay"
            )

            def _cache_only(symbol, strike, option_type, expiry, trading_date):
                return get_or_fetch_candles(
                    feed=None,
                    symbol=symbol,
                    strike=strike,
                    option_type=option_type,
                    expiry=expiry,
                    trading_date=trading_date,
                )

            candle_source = _cache_only
    else:

        def _cache_only(symbol, strike, option_type, expiry, trading_date):
            return get_or_fetch_candles(
                feed=None,
                symbol=symbol,
                strike=strike,
                option_type=option_type,
                expiry=expiry,
                trading_date=trading_date,
            )

        candle_source = _cache_only

    result = run_paper_engine(
        alerts_path=args.alerts,
        app_config=cfg,
        candle_source=candle_source,
        write=True,
        compute_all_alerts=True,
    )

    print("\nPhase 5D backfill")
    print("=" * 40)
    print(result.collapse_summary)
    print(f"representatives: {len(result.representatives)}")
    print(f"records written: {len(result.records)} → {result.paper_trades_path}")
    print(f"overrides file:  {result.overrides_path}")

    taken_outcomes = {
        aid: po
        for aid, po in result.outcomes_taken.items()
        if any(s.alert_id == aid and s.decision == "TAKEN"
               for s in result.selection_results)
    }
    _print_distribution("TAKEN outcomes", outcome_distribution(taken_outcomes))
    _print_distribution(
        "ALL alerts outcomes (diagnostic, biased by re-fires)",
        outcome_distribution(result.outcomes_all_alerts),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
