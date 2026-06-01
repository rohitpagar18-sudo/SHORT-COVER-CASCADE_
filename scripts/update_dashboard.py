#!/usr/bin/env python
"""Manual entry point for the Phase 5.2 dashboard pipeline.

Runs three steps sequentially:

  1. ``sync_jsonl_to_parquet`` — append new JSONL rows to the monthly
     Parquet files under ``data/``.
  2. ``update_dashboard`` — refresh the current quarter's Excel workbook
     under ``logs/dashboards/``.
  3. ``sync_excel_notes_to_parquet`` — best-effort: read user-filled
     outcome columns from the Order Place sheet and write them back to
     Parquet so future ML/backtest reads see the outcomes.

Idempotent: run twice and the second run reports 0 new rows.

Usage:
    python scripts/update_dashboard.py
    update_dashboard.bat        (Windows convenience launcher)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Windows cmd is cp1252 by default — let UTF-8 in print() succeed.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config_loader import load_secrets  # noqa: E402
from src.dashboard import (  # noqa: E402
    sync_excel_notes_to_parquet,
    sync_jsonl_to_parquet,
    update_dashboard,
)

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def main() -> None:
    print("=" * 60)
    print("  SCC Dashboard + Parquet Update")
    print(f"  Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Secrets are optional for the dashboard pipeline (it only reads
    # local JSONL / Excel), but other code paths assume they're loaded.
    if SECRETS_PATH.exists():
        try:
            load_secrets(SECRETS_PATH)
        except Exception as e:
            print(f"  ⚠ secrets load skipped: {e}")
    else:
        print(f"  ⚠ {SECRETS_PATH} not found — continuing without it")

    print("\n[1/3] JSONL -> Parquet sync (monthly files)...")
    pq = sync_jsonl_to_parquet()
    print(f"  Rows added: {pq.get('rows_added', 0)}")
    print(f"  Months touched: {pq.get('months_updated', 0)}")
    print(f"  Total rows in Parquet: {pq.get('total_rows_in_parquet', 0)}")

    print("\n[2/3] Updating dashboard.xlsx (quarterly file)...")
    xl = update_dashboard()
    if xl.get("status") == "no_data":
        print("  No data yet — skipped.")
    else:
        print(f"  File: {xl.get('output_path')}")
        print(f"  Quarters touched: {xl.get('quarters_touched', 0)}")
        print(f"  Alerts: {xl.get('alerts_added', 0)}")
        print(f"  Signals: {xl.get('signals_added', 0)}")
        print(f"  Order Place rows: {xl.get('order_place_added', 0)}")
        print(f"  Gap rows: {xl.get('gaps_added', 0)}")

    print("\n[3/3] Excel notes -> Parquet sync (best-effort)...")
    notes = sync_excel_notes_to_parquet()
    if notes.get("alerts_updated", 0) > 0:
        print(f"  Outcome columns updated for {notes['alerts_updated']} alerts")
    else:
        print(f"  Skipped: {notes.get('skipped_reason', 'no notes filled yet')}")

    print("\n[OK] Done.")
    print("  Human review: logs/dashboards/")
    print("  ML/backtest:  data/")


if __name__ == "__main__":
    main()
