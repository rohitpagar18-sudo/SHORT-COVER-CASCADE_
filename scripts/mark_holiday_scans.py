"""Retroactively tag rows in signals.jsonl / alerts.jsonl that were
written during NSE holidays. Idempotent. Run BEFORE update_dashboard.bat.

Evidence: gap_log.jsonl rows where any per_symbol error contains
'today_n=0' identify dates when the bot ran on a non-trading day. Those
runs produced "ghost" rows in signals.jsonl / alerts.jsonl using stale
prior-day candles. We mark such rows with is_holiday_scan=True so ML
and backtest queries can exclude them.

Usage: python scripts/mark_holiday_scans.py
"""

from __future__ import annotations

import json
from pathlib import Path


def _holiday_dates_from_gap_log(p: Path) -> set[str]:
    out: set[str] = set()
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        per_sym = row.get("per_symbol") or {}
        zero_today = any(
            "today_n=0" in str(s.get("error", ""))
            for s in per_sym.values()
            if isinstance(s, dict)
        )
        if zero_today:
            date_str = str(row.get("timestamp_ist", ""))[:10]
            if date_str:
                out.add(date_str)
    return out


def _mark_file(path: Path, holiday_dates: set[str]) -> int:
    if not path.exists():
        print(f"  {path.name}: not found — skipping.")
        return 0

    new_lines: list[str] = []
    marked = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue
        row_date = str(row.get("timestamp_ist", ""))[:10]
        if row_date in holiday_dates and not row.get("is_holiday_scan"):
            row["is_holiday_scan"] = True
            marked += 1
        new_lines.append(json.dumps(row, ensure_ascii=False))

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(f"  {path.name}: marked {marked} rows")
    return marked


def main(repo_root: Path | None = None) -> None:
    # repo_root override lets tests redirect to a tmp_path. CLI callers
    # leave it None and the script targets the real repo's logs/.
    repo = repo_root if repo_root is not None else Path(__file__).resolve().parents[1]
    gap = repo / "logs" / "gap_log.jsonl"
    sig = repo / "logs" / "signals.jsonl"
    alr = repo / "logs" / "alerts.jsonl"

    holiday_dates = _holiday_dates_from_gap_log(gap)
    if not holiday_dates:
        print("No holiday-run dates detected in gap_log.jsonl.")
        return

    print(f"Holiday dates: {sorted(holiday_dates)}")

    total = 0
    for f in (sig, alr):
        total += _mark_file(f, holiday_dates)

    print(f"Marked {total} rows with is_holiday_scan=True")
    if total:
        print("Next: run update_dashboard.bat to push the flag to Parquet.")


if __name__ == "__main__":
    main()
