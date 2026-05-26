"""Risk preview — show SL/TP/lot picture for a hypothetical entry.

Pure math, no broker calls. Useful for sanity-checking the strategy
config against the v3.1 strategy doc tables.

Usage::

    python scripts/check_risk.py --symbol NIFTY --entry 152.50 \
        --vwap 150 --vix 14.2 --expiry-day false

If ``--vwap`` is omitted, the script uses the entry price as VWAP (worst
case for SL distance — gives the most conservative preview).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config, load_secrets
from src.risk import (
    classify_vix,
    compute_lots,
    compute_sl_method1,
    compute_sl_method2,
    compute_tps,
    get_base_buffer,
)

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def _parse_bool(s: str) -> bool:
    v = s.strip().lower()
    if v in ("true", "yes", "y", "on", "1"):
        return True
    if v in ("false", "no", "n", "off", "0"):
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {s!r}")


def _band_label(buf_table: list[tuple[float, float, float]], option_price: float) -> str:
    for low, high, _ in buf_table:
        if low <= option_price < high:
            return f"{low:.0f}-{high:.0f}" if high != float("inf") else f"{low:.0f}+"
    return "?"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Preview SL/TP/lots for a hypothetical entry.")
    p.add_argument("--symbol", required=True, choices=["NIFTY", "BANKNIFTY"])
    p.add_argument("--entry", type=float, required=True,
                   help="Hypothetical option entry price (e.g. 152.50)")
    p.add_argument("--vwap", type=float, default=None,
                   help="VWAP at entry. Defaults to --entry value.")
    p.add_argument("--vix", type=float, required=True,
                   help="India VIX value (e.g. 14.2)")
    p.add_argument("--expiry-day", dest="expiry_day", type=_parse_bool,
                   default=False, help="true/false — is today expiry day?")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        load_secrets(SECRETS_PATH)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    config = load_config(CONFIG_PATH)

    symbol = args.symbol
    entry = float(args.entry)
    vwap = float(args.vwap) if args.vwap is not None else entry
    vix = float(args.vix)
    is_expiry = bool(args.expiry_day)
    use_vix = bool(config.stop_loss.use_vix_multiplier)

    vix_info = classify_vix(vix)
    day_label = "Expiry" if is_expiry else "Non-expiry"

    base_buf = get_base_buffer(symbol, entry, is_expiry)

    # Compute Method 1 + Method 2 for comparison
    sl_m1 = compute_sl_method1(
        vwap_at_entry=vwap, option_price=entry, symbol=symbol,
        is_expiry_day=is_expiry, vix_info=vix_info, use_vix_multiplier=use_vix,
    )
    sl_m2 = compute_sl_method2(
        vwap_at_entry=vwap, is_expiry_day=is_expiry, vix_info=vix_info,
    )

    lot_size = (
        config.instruments.nifty_lot_size
        if symbol == "NIFTY"
        else config.instruments.banknifty_lot_size
    )

    tp_m1 = compute_tps(entry, sl_m1.sl_price, is_expiry, config)
    tp_m2 = compute_tps(entry, sl_m2.sl_price, is_expiry, config)

    lots_m1 = compute_lots(entry, sl_m1.sl_price, symbol, lot_size, config)
    lots_m2 = compute_lots(entry, sl_m2.sl_price, symbol, lot_size, config)

    # Determine band label for display
    from src.risk.stop_loss import (
        BANKNIFTY_EXPIRY_DAY_BUFFER,
        BANKNIFTY_NORMAL_DAY_BUFFER,
        NIFTY_EXPIRY_DAY_BUFFER,
        NIFTY_NORMAL_DAY_BUFFER,
    )
    if symbol == "NIFTY":
        table = NIFTY_EXPIRY_DAY_BUFFER if is_expiry else NIFTY_NORMAL_DAY_BUFFER
    else:
        table = BANKNIFTY_EXPIRY_DAY_BUFFER if is_expiry else BANKNIFTY_NORMAL_DAY_BUFFER
    band = _band_label(table, entry)

    width = 60
    print("=" * width)
    print(f"  Risk Preview - {symbol} @ entry Rs.{entry:.2f}")
    print(
        f"  VWAP Rs.{vwap:.2f}, VIX {vix:g} ({vix_info.label} Regime, "
        f"{vix_info.method1_multiplier:g}x)"
    )
    print(f"  Day type: {day_label}    Lot size: {lot_size}")
    print("=" * width)
    print("Method 1 (Point Buffer):")
    multiplier_label = (
        f"x {sl_m1.vix_multiplier:g}"
        if use_vix
        else "x 1.0 (VIX multiplier OFF)"
    )
    print(f"  Base buffer    : {base_buf:g} points ({symbol} {band} range)")
    print(
        f"  VIX-adjusted   : {base_buf:g} {multiplier_label} = "
        f"{sl_m1.final_buffer_or_pct:g} points"
    )
    print(f"  SL price       : Rs.{sl_m1.sl_price:.2f}")
    print(f"  Risk per unit  : Rs.{lots_m1.risk_per_unit:.2f}")
    cap_note = " (capped by lot limit)" if lots_m1.capped_by_lot_limit else ""
    print(f"  Lots           : {lots_m1.lots}{cap_note}")
    print(
        f"  Total risk     : Rs.{lots_m1.total_risk_rupees:,.2f}  "
        f"({lots_m1.lots} x {lot_size} x Rs.{lots_m1.risk_per_unit:.2f})"
    )
    print(
        f"  TP1            : Rs.{tp_m1.tp1:.2f} "
        f"({tp_m1.risk_to_tp1_ratio:g}R, exit 50%)"
    )
    print(
        f"  TP2            : Rs.{tp_m1.tp2:.2f} "
        f"({tp_m1.risk_to_tp2_ratio:g}R, exit 50%)"
    )
    print()
    print("Method 2 (Percentage):")
    print(f"  SL %           : {sl_m2.final_buffer_or_pct:g}%  ({vix_info.label} regime)")
    print(f"  SL price       : Rs.{sl_m2.sl_price:.2f}")
    print(f"  Risk per unit  : Rs.{lots_m2.risk_per_unit:.2f}")
    cap_note2 = " (capped by lot limit)" if lots_m2.capped_by_lot_limit else ""
    print(f"  Lots           : {lots_m2.lots}{cap_note2}")
    print(
        f"  Total risk     : Rs.{lots_m2.total_risk_rupees:,.2f}  "
        f"({lots_m2.lots} x {lot_size} x Rs.{lots_m2.risk_per_unit:.2f})"
    )
    print(
        f"  TP1            : Rs.{tp_m2.tp1:.2f} "
        f"({tp_m2.risk_to_tp1_ratio:g}R)"
    )
    print(
        f"  TP2            : Rs.{tp_m2.tp2:.2f} "
        f"({tp_m2.risk_to_tp2_ratio:g}R)"
    )
    print("=" * width)
    active_method = config.stop_loss.method
    print(
        f"Active SL method (config.stop_loss.method): Method {active_method}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
