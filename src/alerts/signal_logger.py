"""JSONL writers for signals.jsonl and alerts.jsonl.

Two parallel logs:

  - ``signals.jsonl``  — every scan, every rejection, and every data_issue.
  - ``alerts.jsonl``   — only valid 5/5 signals that fired a Telegram.

Every record carries an ``event_type`` ("scan" / "rejection" / "alert" /
"data_issue") so the EOD counter / backtest harness / verification
scripts can distinguish real condition checks from short-circuit
rejections and from technical data-availability problems.

Records are appended as single JSON objects, one per line, UTF-8.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

IST = ZoneInfo("Asia/Kolkata")


class SignalLogger:
    """Append-only JSONL logger for scans, rejections, and alerts."""

    def __init__(
        self,
        signals_path: str | Path = "logs/signals.jsonl",
        alerts_path: str | Path = "logs/alerts.jsonl",
    ) -> None:
        self.signals_path = Path(signals_path)
        self.alerts_path = Path(alerts_path)
        self.signals_path.parent.mkdir(parents=True, exist_ok=True)
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)

    def log_signal(self, record: dict) -> None:
        """Append one record to signals.jsonl.

        Defaults event_type to "scan" if missing. Any caller-supplied
        event_type ("scan" / "rejection" / "alert" / "data_issue") is
        preserved as-is.
        """
        if "event_type" not in record:
            record["event_type"] = "scan"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_rejection(self, record: dict) -> None:
        """Append a rejection record (event_type forced to "rejection")."""
        record["event_type"] = "rejection"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_alert(self, record: dict) -> None:
        """Append one alert record to alerts.jsonl (event_type "alert")."""
        record["event_type"] = "alert"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.alerts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            "Alert logged: {} {} {}",
            record.get("symbol"),
            record.get("strike"),
            record.get("option_type"),
        )
