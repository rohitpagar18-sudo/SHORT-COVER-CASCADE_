"""One-time migration: rename legacy `relation` values to per-level labels.

Maps "ITM" -> "ITM1" and "OTM" -> "OTM1" in:
  - logs/signals.jsonl
  - logs/alerts.jsonl
  - data/*.parquet

"ATM" is left unchanged. Each file is rewritten in-place via a `.tmp`
file then renamed (atomic on POSIX, best-effort on Windows). Reports
the number of rows updated per file.

Safe to re-run: idempotent — second run reports zero updates.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

LEGACY_MAP = {"ITM": "ITM1", "OTM": "OTM1"}

PROJECT_ROOT = Path(__file__).resolve().parents[1]
JSONL_FILES = [
    PROJECT_ROOT / "logs" / "signals.jsonl",
    PROJECT_ROOT / "logs" / "alerts.jsonl",
]
PARQUET_GLOB = PROJECT_ROOT / "data"


def _migrate_jsonl(path: Path) -> int:
    if not path.exists():
        print(f"[skip] {path} — not found")
        return 0
    updated = 0
    tmp = path.with_suffix(path.suffix + ".tmp")
    with path.open("r", encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as dst:
        for line in src:
            line = line.rstrip("\n")
            if not line.strip():
                dst.write("\n")
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                dst.write(line + "\n")
                continue
            rel = obj.get("relation")
            if isinstance(rel, str) and rel in LEGACY_MAP:
                obj["relation"] = LEGACY_MAP[rel]
                updated += 1
            dst.write(json.dumps(obj, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    print(f"[ok]   {path} — {updated} row(s) updated")
    return updated


def _migrate_parquet(path: Path) -> int:
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        print(f"[skip] {path} — read failed: {e}")
        return 0
    if "relation" not in df.columns:
        print(f"[skip] {path} — no relation column")
        return 0
    mask = df["relation"].isin(LEGACY_MAP.keys())
    updated = int(mask.sum())
    if updated == 0:
        print(f"[ok]   {path} — 0 row(s) updated")
        return 0
    df.loc[mask, "relation"] = df.loc[mask, "relation"].map(LEGACY_MAP)
    df.to_parquet(path, index=False)
    print(f"[ok]   {path} — {updated} row(s) updated")
    return updated


def main() -> int:
    print("Migrating relation labels: ITM -> ITM1, OTM -> OTM1 (ATM unchanged)")
    print("-" * 70)

    total = 0
    for p in JSONL_FILES:
        total += _migrate_jsonl(p)

    if PARQUET_GLOB.exists():
        for p in sorted(PARQUET_GLOB.glob("*.parquet")):
            total += _migrate_parquet(p)
    else:
        print(f"[skip] {PARQUET_GLOB} — directory not found")

    print("-" * 70)
    print(f"Total rows updated across all files: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
