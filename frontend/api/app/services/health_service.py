"""System health snapshot shared by F7c System Health tab and F8 Bot Status page.

Collects:
- feed: active feed name + connected status
- bot: status, last_activity_ist, uptime_seconds
- scan_cadence: gap analysis on recent signals.jsonl timestamps
- files: stat for 5 key files (last_modified_ist, size_kb, fresh)
- data_issues: recent data_issue rows from signals.jsonl
- last_config_reload_ist: from botstatus_service
- last_dashboard_sync_ist: scanned from bot.log

All wrapped in try/except. Never raises. Missing files → nulls/False.
All times: IST (Asia/Kolkata).
"""
from __future__ import annotations

import re
from datetime import datetime, time as time_cls
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..paths import (
    SIGNALS_JSONL,
    ALERTS_JSONL,
    PAPER_TRADES_JSONL,
    STATE_JSON,
    BOT_LOG,
)
from . import botstatus_service, config_service
from .jsonl_reader import read_jsonl

IST = ZoneInfo("Asia/Kolkata")

# Market hours (IST) for scan-cadence filtering
_MARKET_START = time_cls(9, 15)
_MARKET_END = time_cls(15, 30)

# Gap threshold: more than this many minutes between consecutive scans = a gap
_GAP_THRESHOLD_MIN = 7

# Loguru line prefix pattern: "2026-05-27 10:35:00.123 | INFO | ..."
_LOGURU_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ist() -> datetime:
    return datetime.now(IST)


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (ValueError, TypeError):
        return None


def _fmt_ist(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(IST).isoformat()


def _is_market_candle(dt: datetime) -> bool:
    """True if this datetime is Mon-Fri and within 09:15–15:30 IST."""
    if dt.weekday() >= 5:  # Sat=5, Sun=6
        return False
    t = dt.time()
    return _MARKET_START <= t <= _MARKET_END


# ---------------------------------------------------------------------------
# feed section
# ---------------------------------------------------------------------------

def _get_feed(bot_status: str) -> Dict[str, Any]:
    try:
        cfg = config_service.load_config()
        active_feed = (cfg.get("feeds") or {}).get("active_feed", "unknown")
    except Exception:
        active_feed = "unknown"
    connected = bot_status == "RUNNING"
    return {
        "active_feed": active_feed,
        "status": "connected" if connected else "disconnected",
    }


# ---------------------------------------------------------------------------
# bot section
# ---------------------------------------------------------------------------

def _get_bot() -> Dict[str, Any]:
    try:
        bot_status, last_activity = botstatus_service.status()
    except Exception:
        bot_status, last_activity = "STOPPED", None
    try:
        uptime_s = botstatus_service.uptime_seconds()
    except Exception:
        uptime_s = None
    return {
        "status": bot_status,
        "last_activity_ist": last_activity,
        "uptime_seconds": uptime_s,
    }


# ---------------------------------------------------------------------------
# scan_cadence section
# ---------------------------------------------------------------------------

def _get_scan_cadence() -> Dict[str, Any]:
    _safe: Dict[str, Any] = {
        "expected_interval_min": 5,
        "recent_gaps": [],
        "healthy": True,
        "note": "No signal data available.",
    }
    try:
        rows = read_jsonl(SIGNALS_JSONL, max_lines=5000)
        timestamps: List[datetime] = []
        for r in rows:
            ts_str = r.get("timestamp_ist")
            dt = _parse_ts(ts_str)
            if dt is None:
                continue
            if not _is_market_candle(dt):
                continue
            timestamps.append(dt)

        if len(timestamps) < 2:
            return {
                "expected_interval_min": 5,
                "recent_gaps": [],
                "healthy": True,
                "note": "Insufficient signal data for gap analysis.",
            }

        timestamps.sort()

        gaps: List[Dict[str, Any]] = []
        for i in range(1, len(timestamps)):
            gap_sec = (timestamps[i] - timestamps[i - 1]).total_seconds()
            gap_min = gap_sec / 60.0
            if gap_min > _GAP_THRESHOLD_MIN:
                gaps.append({
                    "from": _fmt_ist(timestamps[i - 1]),
                    "to": _fmt_ist(timestamps[i]),
                    "gap_min": round(gap_min, 1),
                })

        recent_gaps = gaps[-10:]  # last 10

        healthy = len(recent_gaps) == 0
        if not healthy:
            note = f"{len(gaps)} gap(s) >7 min detected in market-hours signals."
        else:
            note = "Scan cadence looks healthy — no gaps >7 min."

        return {
            "expected_interval_min": 5,
            "recent_gaps": recent_gaps,
            "healthy": healthy,
            "note": note,
        }
    except Exception:
        return _safe


# ---------------------------------------------------------------------------
# files section
# ---------------------------------------------------------------------------

_FILE_SPECS = [
    ("signals.jsonl", SIGNALS_JSONL),
    ("alerts.jsonl", ALERTS_JSONL),
    ("paper_trades.jsonl", PAPER_TRADES_JSONL),
    ("state.json", STATE_JSON),
    ("bot.log", BOT_LOG),
]

_FRESH_SECONDS = 86_400  # 24 hours


def _stat_file(label: str, path: Path) -> Dict[str, Any]:
    try:
        st = path.stat()
        mtime_dt = datetime.fromtimestamp(st.st_mtime, tz=IST)
        age_s = (_now_ist() - mtime_dt).total_seconds()
        return {
            "name": label,
            "last_modified_ist": _fmt_ist(mtime_dt),
            "size_kb": round(st.st_size / 1024.0, 1),
            "fresh": age_s <= _FRESH_SECONDS,
        }
    except OSError:
        return {
            "name": label,
            "last_modified_ist": None,
            "size_kb": None,
            "fresh": False,
        }


def _get_files() -> List[Dict[str, Any]]:
    return [_stat_file(label, path) for label, path in _FILE_SPECS]


# ---------------------------------------------------------------------------
# data_issues section
# ---------------------------------------------------------------------------

def _get_data_issues() -> Dict[str, Any]:
    try:
        rows = read_jsonl(SIGNALS_JSONL, max_lines=10_000)
        issues: List[Dict[str, Any]] = []
        for r in rows:
            if r.get("event_type") == "data_issue" or r.get("issue_type") is not None:
                detail = r.get("reason") or r.get("detail") or ""
                issues.append({
                    "time": r.get("timestamp_ist"),
                    "issue_type": r.get("issue_type") or "data_issue",
                    "detail": str(detail),
                })
        recent = issues[-10:]
        return {"count": len(issues), "recent": recent}
    except Exception:
        return {"count": 0, "recent": []}


# ---------------------------------------------------------------------------
# last_dashboard_sync_ist: scan bot.log reversed
# ---------------------------------------------------------------------------

def _get_last_dashboard_sync() -> Optional[str]:
    try:
        if not BOT_LOG.exists():
            return None
        with BOT_LOG.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in reversed(lines):
            lower = line.lower()
            if "dashboard" in lower or "sync" in lower:
                m = _LOGURU_TS_RE.match(line.strip())
                if m:
                    ts_str = m.group(1)
                    try:
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        dt = dt.replace(tzinfo=IST)
                        return _fmt_ist(dt)
                    except ValueError:
                        continue
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_health() -> Dict[str, Any]:
    """Return system health snapshot. Never raises."""
    try:
        bot_info = _get_bot()
        bot_status = bot_info.get("status", "STOPPED")
    except Exception:
        bot_info = {"status": "STOPPED", "last_activity_ist": None, "uptime_seconds": None}
        bot_status = "STOPPED"

    try:
        feed_info = _get_feed(bot_status)
    except Exception:
        feed_info = {"active_feed": "unknown", "status": "disconnected"}

    try:
        scan_cadence = _get_scan_cadence()
    except Exception:
        scan_cadence = {
            "expected_interval_min": 5,
            "recent_gaps": [],
            "healthy": True,
            "note": "Error reading scan cadence.",
        }

    try:
        files_info = _get_files()
    except Exception:
        files_info = [
            {"name": label, "last_modified_ist": None, "size_kb": None, "fresh": False}
            for label, _ in _FILE_SPECS
        ]

    try:
        data_issues = _get_data_issues()
    except Exception:
        data_issues = {"count": 0, "recent": []}

    try:
        last_config_reload = botstatus_service.last_config_reload_ist()
    except Exception:
        last_config_reload = None

    try:
        last_dashboard_sync = _get_last_dashboard_sync()
    except Exception:
        last_dashboard_sync = None

    return {
        "feed": feed_info,
        "bot": bot_info,
        "scan_cadence": scan_cadence,
        "files": files_info,
        "data_issues": data_issues,
        "last_config_reload_ist": last_config_reload,
        "last_dashboard_sync_ist": last_dashboard_sync,
    }
