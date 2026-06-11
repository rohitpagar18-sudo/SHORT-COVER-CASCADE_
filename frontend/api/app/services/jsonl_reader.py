"""Robust JSONL tail-reader.

Used for signals.jsonl, alerts.jsonl, paper_trades.jsonl. Bot writes
these files line-by-line; a tailer or our own reader must tolerate:
  * the file not existing yet (empty result)
  * a partial trailing line being written when we read
  * malformed lines (skip, don't crash)

For the Overview page we never need more than the last ~500 rows, so we
read by line and keep an in-memory ring of size `max_lines`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def read_jsonl(path: Path, max_lines: int = 500) -> List[Dict[str, Any]]:
    """Return up to the last `max_lines` JSON objects from `path`. Bad
    lines are silently skipped. Missing file → []."""
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            # Small files (logs/) are kilobytes today; read all then tail.
            lines = f.readlines()
    except OSError:
        return []
    for line in lines[-max_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def filter_by_date(rows: Iterable[Dict[str, Any]], date_iso: str, ts_field: str) -> List[Dict[str, Any]]:
    """Return rows whose `ts_field` starts with `date_iso` (YYYY-MM-DD)."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        v = r.get(ts_field)
        if isinstance(v, str) and v.startswith(date_iso):
            out.append(r)
    return out
