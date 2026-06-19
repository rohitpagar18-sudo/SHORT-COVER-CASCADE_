#!/usr/bin/env python
"""Standalone entry point for the shadow stop-loss lab.

This script is NEVER imported by the live bot. It is the only way
``logs/shadow_sl.jsonl`` is updated. The lab is read-only over
``logs/alerts.jsonl`` and ``data/replay_cache/``.

Usage:
    python scripts/update_shadow_sl.py
    update_shadow_sl.bat        (Windows convenience launcher)
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

from src.config_loader import load_config  # noqa: E402
from src.shadow_sl.runner import run  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    print("=" * 60)
    print("  SCC Shadow-SL Lab (experimental, read-only)")
    print(f"  Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    cfg = load_config(PROJECT_ROOT / "config" / "config.yaml")
    if not cfg.shadow_sl.enabled:
        print("shadow_sl.enabled is OFF — nothing to do.")
        return 0

    result = run(app_config=cfg)
    print()
    print(f"  Alerts read:           {result.alerts_read}")
    print(f"  Cache misses (skipped):{result.alerts_skipped_cache_miss}")
    print(f"  Methods evaluated:     {', '.join(result.methods_run) or '(none)'}")
    print(f"  Duplicate rows skipped:{result.rows_skipped_duplicate}")
    print(f"  Rows written:          {result.rows_written}")
    print(f"  Output file:           {result.output_path}")
    print()
    print("[OK] Done. Live pipelines untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
