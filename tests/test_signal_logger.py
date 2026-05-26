"""Tests for src/alerts/signal_logger.py."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.alerts.signal_logger import SignalLogger

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def logger(tmp_path) -> SignalLogger:
    return SignalLogger(
        signals_path=tmp_path / "signals.jsonl",
        alerts_path=tmp_path / "alerts.jsonl",
    )


def _read_lines(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_log_signal_appends_to_jsonl(logger: SignalLogger) -> None:
    logger.log_signal({"symbol": "NIFTY", "strike": 24050, "all_passed": False})
    rows = _read_lines(logger.signals_path)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NIFTY"
    assert rows[0]["strike"] == 24050


def test_log_signal_default_event_type_is_scan(logger: SignalLogger) -> None:
    logger.log_signal({"symbol": "NIFTY"})
    rows = _read_lines(logger.signals_path)
    assert rows[0]["event_type"] == "scan"


def test_log_signal_respects_explicit_event_type(logger: SignalLogger) -> None:
    logger.log_signal({"symbol": "NIFTY", "event_type": "scan"})
    rows = _read_lines(logger.signals_path)
    assert rows[0]["event_type"] == "scan"


def test_log_rejection_writes_event_type_rejection(logger: SignalLogger) -> None:
    logger.log_rejection({"symbol": "NIFTY", "rejection_blocker": "C0"})
    rows = _read_lines(logger.signals_path)
    assert rows[0]["event_type"] == "rejection"


def test_log_rejection_overrides_event_type(logger: SignalLogger) -> None:
    """Even if caller passes event_type='scan', rejection logger overrides it."""
    logger.log_rejection({"symbol": "NIFTY", "event_type": "scan"})
    rows = _read_lines(logger.signals_path)
    assert rows[0]["event_type"] == "rejection"


def test_log_alert_appends_to_alerts_jsonl(logger: SignalLogger) -> None:
    logger.log_alert({"symbol": "NIFTY", "strike": 24050, "option_type": "CE"})
    rows_alerts = _read_lines(logger.alerts_path)
    rows_signals = _read_lines(logger.signals_path)
    assert len(rows_alerts) == 1
    assert rows_alerts[0]["event_type"] == "alert"
    # log_alert goes only to alerts.jsonl, NOT to signals.jsonl.
    assert len(rows_signals) == 0


def test_log_creates_directory_if_missing(tmp_path) -> None:
    deep = tmp_path / "a" / "b" / "c"
    sl = SignalLogger(
        signals_path=deep / "signals.jsonl",
        alerts_path=deep / "alerts.jsonl",
    )
    sl.log_signal({"symbol": "NIFTY"})
    assert (deep / "signals.jsonl").exists()


def test_each_line_is_valid_json(logger: SignalLogger) -> None:
    logger.log_signal({"a": 1})
    logger.log_signal({"b": 2})
    logger.log_rejection({"c": 3})
    raw = logger.signals_path.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 3
    for line in raw:
        json.loads(line)  # would raise on bad json


def test_timestamps_are_ist_iso(logger: SignalLogger) -> None:
    before = datetime.now(IST)
    logger.log_signal({"symbol": "NIFTY"})
    after = datetime.now(IST)
    row = _read_lines(logger.signals_path)[0]
    ts = datetime.fromisoformat(row["_logged_at"])
    # tz-aware and within the expected window.
    assert ts.tzinfo is not None
    assert before <= ts <= after


def test_multiple_logs_append_not_overwrite(logger: SignalLogger) -> None:
    for i in range(5):
        logger.log_signal({"idx": i})
    rows = _read_lines(logger.signals_path)
    assert [r["idx"] for r in rows] == [0, 1, 2, 3, 4]


def test_alerts_and_signals_files_are_separate(logger: SignalLogger) -> None:
    logger.log_signal({"symbol": "A"})
    logger.log_alert({"symbol": "B"})
    sigs = _read_lines(logger.signals_path)
    alerts = _read_lines(logger.alerts_path)
    assert sigs[0]["symbol"] == "A"
    assert alerts[0]["symbol"] == "B"
    assert len(sigs) == 1 and len(alerts) == 1
