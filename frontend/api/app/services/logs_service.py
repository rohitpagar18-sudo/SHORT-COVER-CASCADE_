"""Read-only log file viewer service.

Files served (allowlist — anything else is REJECTED in the router):
  bot.log              — loguru text log (free text)
  signals.jsonl        — one JSON object per scan/alert/etc.
  alerts.jsonl         — one JSON object per fired alert (subset of signals + entry/sl/tp)
  paper_trades.jsonl   — one JSON object per paper trade decision/outcome
  state.json           — single JSON object (full file is small; may be missing)

REAL FIELD NAMES (verified by reading the actual logs on disk):

  bot.log (loguru pattern):
    "YYYY-MM-DD HH:MM:SS.mmm | LEVEL    | module:func:line - message"

  signals.jsonl per-row:
    timestamp_ist, event_type ("scan"|"rejection"|"would_alert_extended"|"alert"|"data_issue"),
    symbol, strike, relation, option_type, expiry, trading_symbol, spot_price,
    spot_vwap, option_close, option_vwap, rsi, rsi_ma, oi, oi_ma, volume,
    volume_ma, is_green, vix, vix_regime, conditions_passed[], conditions_failed[],
    all_passed, summary, reasons{}, opt_above_vwap_pct, issue_type (optional)

  alerts.jsonl per-row:
    (signals fields) + entry, sl, sl_method, tp1, tp2, tp1_r, tp2_r,
    risk_per_unit, lots, total_risk, lot_size, day_type, vix_multiplier,
    spot, spot_position, date, time, bot_remark, bot_tags, telegram_short_remark

  paper_trades.jsonl per-row:
    alert_id, episode_id, paper_role, date, candle_timestamp, symbol,
    strike, relation, option_type, expiry, entry, sl, tp1, tp2, lots,
    lot_size, is_expiry_day, decision, decision_reason, slot, outcome,
    exit_price, exit_time, exit_reason, realized_R, paper_pnl,
    paper_pnl_per_unit, mfe, mae, mfe_R, mae_R, max_drawdown_R,
    intrabar_ambiguous, fidelity, fidelity_note, bot_remark, bot_tags,
    triggered_caps[]

EFFICIENT TAIL
We never load the whole file into memory: we open the file in binary mode,
seek to the end, walk backwards in chunks, and stop as soon as we have
enough lines. Even multi-GB log files only cost the last few KB to tail.

SECURITY
The router validates the `file` query against ALLOWED_FILES before calling
this service. We never accept an arbitrary path.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..paths import (
    ALERTS_JSONL,
    BOT_LOG,
    LOGS_DIR,
    PAPER_TRADES_JSONL,
    SIGNALS_JSONL,
    STATE_JSON,
)
from ..time_utils import IST, fmt_ist

# Allowlist: ONLY these five files can be tailed.
ALLOWED_FILES: Dict[str, Path] = {
    "bot.log": BOT_LOG,
    "signals.jsonl": SIGNALS_JSONL,
    "alerts.jsonl": ALERTS_JSONL,
    "paper_trades.jsonl": PAPER_TRADES_JSONL,
    "state.json": STATE_JSON,
}

# Loguru line prefix:  "2026-05-25 14:55:28.928 | INFO     | __main__:main:82 - msg"
_LOGURU_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*\|\s*"
    r"(?P<level>[A-Z]+)\s*\|\s*(?P<rest>.*)$"
)

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_CHUNK_SIZE = 8192


def list_files() -> List[Dict[str, Any]]:
    """Stat each allowlisted file. Missing files return null mtime/size."""
    out: List[Dict[str, Any]] = []
    for name, path in ALLOWED_FILES.items():
        try:
            st = path.stat()
            mtime = datetime.fromtimestamp(st.st_mtime, tz=IST)
            out.append({
                "name": name,
                "path_label": _path_label(path),
                "size_kb": round(st.st_size / 1024.0, 1),
                "last_modified_ist": fmt_ist(mtime),
            })
        except OSError:
            out.append({
                "name": name,
                "path_label": _path_label(path),
                "size_kb": None,
                "last_modified_ist": None,
            })
    return out


def _path_label(p: Path) -> str:
    """Render a friendly relative path (e.g. "logs/bot.log"). Falls back
    to the absolute path on any path-resolution failure.
    """
    try:
        return p.relative_to(LOGS_DIR.parent).as_posix()
    except Exception:
        return str(p)


def _tail_lines(path: Path, n: int) -> List[str]:
    """Return the last `n` non-empty lines from `path` without loading
    the whole file. Walks backwards in 8 KB chunks from EOF, keeping
    just enough bytes to count `n+1` newlines (the +1 guards against
    the first chunk starting mid-line). Even on multi-GB log files
    only the tail few KB are ever read.

    Decodes bytes as UTF-8 with replacement so partial multi-byte
    sequences at chunk boundaries don't crash. Returns lines oldest-first.
    """
    if n <= 0 or not path.exists():
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size == 0:
        return []

    buffer = b""
    pos = size
    try:
        with path.open("rb") as f:
            while pos > 0:
                read = min(_CHUNK_SIZE, pos)
                pos -= read
                f.seek(pos)
                chunk = f.read(read)
                # Prepend the new (earlier) chunk so the buffer reads
                # oldest-first end-to-end.
                buffer = chunk + buffer
                # Bail out as soon as we have enough newlines AND we're
                # not at the very start (so we don't risk reading a
                # partial first line).
                if buffer.count(b"\n") > n:
                    break
    except OSError:
        return []

    text = buffer.decode("utf-8", errors="replace")
    # Split keeps trailing empty strings if the file ends with `\n` —
    # strip those out below.
    parts = text.splitlines()
    cleaned = [p.rstrip("\r") for p in parts if p.strip()]
    if len(cleaned) > n:
        cleaned = cleaned[-n:]
    return cleaned


def _parse_loguru(line: str) -> Tuple[Optional[str], Optional[str], str]:
    """Parse one loguru line. Returns (time, level, message). If the
    line doesn't match the format, time/level are None and the whole
    line is the message.
    """
    m = _LOGURU_RE.match(line)
    if not m:
        return None, None, line
    return m.group("time"), m.group("level"), m.group("rest")


def tail_text(
    path: Path,
    lines: int,
    level: str = "all",
    search: str = "",
) -> Dict[str, Any]:
    """Tail bot.log (or any text file). Apply optional level + search
    filters AFTER tailing (filtering is a post-step over the small tail
    window, so it never expands what we read from disk).

    Returns:
      {
        "rows": [{"raw": str, "time": str|None, "level": str|None, "message": str}, ...],
        "filtered_count": int,
        "total_read": int,
      }
    """
    raw_lines = _tail_lines(path, max(lines, 1))
    level_up = (level or "all").upper()
    if level_up not in _VALID_LEVELS and level_up != "ALL":
        level_up = "ALL"
    needle = (search or "").lower()

    rows: List[Dict[str, Any]] = []
    for line in raw_lines:
        t, lvl, msg = _parse_loguru(line)
        if level_up != "ALL":
            if (lvl or "").upper() != level_up:
                continue
        if needle and needle not in line.lower():
            continue
        rows.append({
            "raw": line,
            "time": t,
            "level": lvl,
            "message": msg,
        })
    return {
        "rows": rows,
        "filtered_count": len(rows),
        "total_read": len(raw_lines),
    }


def tail_jsonl(
    path: Path,
    lines: int,
    search: str = "",
) -> Dict[str, Any]:
    """Tail a JSONL file. Parse each line as JSON; skip malformed lines.
    Free-text `search` filters case-insensitively against the raw line.

    Returns:
      {
        "rows": [parsed_obj, ...],
        "filtered_count": int,
        "total_read": int,
        "skipped_malformed": int,
      }
    """
    raw_lines = _tail_lines(path, max(lines, 1))
    needle = (search or "").lower()

    rows: List[Dict[str, Any]] = []
    skipped = 0
    for line in raw_lines:
        if needle and needle not in line.lower():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        elif isinstance(obj, list):
            # state.json could conceivably be a list at the top level;
            # surface it as a single row so the UI still shows it.
            rows.append({"_value": obj})
    return {
        "rows": rows,
        "filtered_count": len(rows),
        "total_read": len(raw_lines),
        "skipped_malformed": skipped,
    }


def tail_state_json(path: Path) -> Dict[str, Any]:
    """state.json is a SINGLE JSON document, not JSONL. Read fully (it
    is tiny) and return the parsed object as a one-row table for
    consistency with the JSONL renderer. Missing → empty payload.
    """
    if not path.exists():
        return {"rows": [], "filtered_count": 0, "total_read": 0, "skipped_malformed": 0}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return {"rows": [], "filtered_count": 0, "total_read": 0, "skipped_malformed": 0}
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {"rows": [], "filtered_count": 0, "total_read": 1, "skipped_malformed": 1}
    if isinstance(obj, dict):
        return {"rows": [obj], "filtered_count": 1, "total_read": 1, "skipped_malformed": 0}
    if isinstance(obj, list):
        return {"rows": obj if all(isinstance(x, dict) for x in obj) else [{"_value": obj}],
                "filtered_count": len(obj), "total_read": 1, "skipped_malformed": 0}
    return {"rows": [{"_value": obj}], "filtered_count": 1, "total_read": 1, "skipped_malformed": 0}


def tail(file_name: str, lines: int, level: str, search: str) -> Dict[str, Any]:
    """Dispatcher used by the router. `file_name` must be allowlisted."""
    if file_name not in ALLOWED_FILES:
        # Defensive: the router validates this too, but never trust input.
        return {
            "file": file_name,
            "type": "unknown",
            "error": "not_allowed",
            "rows": [],
        }
    path = ALLOWED_FILES[file_name]
    if file_name == "bot.log":
        body = tail_text(path, lines=lines, level=level, search=search)
        body["file"] = file_name
        body["type"] = "text"
        return body
    if file_name == "state.json":
        body = tail_state_json(path)
        body["file"] = file_name
        body["type"] = "json"
        return body
    body = tail_jsonl(path, lines=lines, search=search)
    body["file"] = file_name
    body["type"] = "jsonl"
    return body


