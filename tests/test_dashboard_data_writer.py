"""Phase 5.2 — JSONL → Parquet writer tests.

Every test isolates logs/ and data/ to a tmp_path. Production paths
are monkeypatched at module level so the tests never touch real files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Redirect data_writer LOGS_DIR / DATA_DIR / DASHBOARDS_DIR to tmp_path.

    Returns (logs_dir, data_dir, dashboards_dir).
    """
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    dashboards = logs / "dashboards"
    logs.mkdir()
    data.mkdir()
    dashboards.mkdir()

    import src.dashboard.data_writer as dw

    monkeypatch.setattr(dw, "LOGS_DIR", logs)
    monkeypatch.setattr(dw, "DATA_DIR", data)
    monkeypatch.setattr(dw, "DASHBOARDS_DIR", dashboards)
    monkeypatch.setattr(dw, "SIGNALS_JSONL", logs / "signals.jsonl")
    monkeypatch.setattr(dw, "ALERTS_JSONL", logs / "alerts.jsonl")
    monkeypatch.setattr(dw, "GAP_JSONL", logs / "gap_log.jsonl")

    return logs, data, dashboards


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _scan(ts: str, **kw) -> dict:
    base = {
        "timestamp_ist": ts,
        "event_type": "scan",
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "relation": "ATM",
        "expiry": "2026-06-02",
        "option_close": 150.0,
        "option_vwap": 140.0,
        "rsi": 65.0,
        "rsi_ma": 55.0,
        "oi": 800_000,
        "oi_ma": 1_000_000,
        "volume": 3000,
        "volume_ma": 1500,
        "all_passed": False,
        "summary": "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✗",
        "opt_above_vwap_pct": 7.0,
        "reasons": {"C0": "ok", "C1": "ok"},
    }
    base.update(kw)
    return base


def _alert(ts: str, **kw) -> dict:
    return _scan(
        ts,
        event_type="alert",
        all_passed=True,
        entry=150.0,
        sl=140.0,
        tp1=165.0,
        tp2=175.0,
        lots=3,
        total_risk=2850.0,
        bot_remark="5/5 strong — opt 7% above VWAP, RSI 65 healthy zone",
        bot_tags="fresh_breakout,strong_rsi,strong_oi,high_volume,morning,normal_vix,normal_day,first_alert",
        **kw,
    )


def _gap(ts: str, decision: str, **kw) -> dict:
    return {
        "timestamp_ist": ts,
        "decision": decision,
        "enabled": True,
        "threshold_pct": 1.0,
        "direction": "both",
        "any_triggered": decision != "NORMAL",
        "per_symbol": {
            "NIFTY": {
                "open": 24050.0,
                "prev_close": 24000.0,
                "gap_pct": kw.get("nifty_gap_pct", 0.21),
                "triggers": decision != "NORMAL",
                "error": None,
            },
            "BANKNIFTY": {
                "open": 51000.0,
                "prev_close": 50950.0,
                "gap_pct": kw.get("bn_gap_pct", 0.10),
                "triggers": False,
                "error": None,
            },
        },
    }


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


def test_handles_scan_event_type(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    _write_jsonl(logs / "signals.jsonl", [_scan("2026-05-27T10:00:00+05:30")])
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    result = sync_jsonl_to_parquet()
    assert result["rows_added"] == 1
    df = pd.read_parquet(data / "scc_data_2026-05.parquet")
    assert len(df) == 1
    assert df["event_type"].iloc[0] == "scan"


def test_handles_alert_event_type(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    _write_jsonl(logs / "alerts.jsonl", [_alert("2026-05-27T10:35:00+05:30")])
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    sync_jsonl_to_parquet()
    df = pd.read_parquet(data / "scc_data_2026-05.parquet")
    assert (df["event_type"] == "alert").any()
    assert "bot_remark" in df.columns


def test_handles_rejection_event_type(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    rej = {
        "timestamp_ist": "2026-05-27T10:00:00+05:30",
        "event_type": "rejection",
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "rejection_blocker": "C0",
        "rejection_reason": "spot below vwap",
    }
    _write_jsonl(logs / "signals.jsonl", [rej])
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    sync_jsonl_to_parquet()
    df = pd.read_parquet(data / "scc_data_2026-05.parquet")
    assert (df["event_type"] == "rejection").sum() == 1
    assert df["rejection_blocker"].iloc[0] == "C0"


def test_handles_data_issue_event_type(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    di = {
        "timestamp_ist": "2026-05-27T11:30:00+05:30",
        "event_type": "data_issue",
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "issue_type": "INSUFFICIENT_LOOKBACK",
        "issue_message": "need 33 candles",
    }
    _write_jsonl(logs / "signals.jsonl", [di])
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    sync_jsonl_to_parquet()
    df = pd.read_parquet(data / "scc_data_2026-05.parquet")
    assert (df["event_type"] == "data_issue").sum() == 1


def test_handles_would_alert_extended_event_type(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    ext = _scan(
        "2026-05-27T13:00:00+05:30",
        event_type="would_alert_extended",
        opt_above_vwap_pct=37.0,
    )
    _write_jsonl(logs / "signals.jsonl", [ext])
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    sync_jsonl_to_parquet()
    df = pd.read_parquet(data / "scc_data_2026-05.parquet")
    assert (df["event_type"] == "would_alert_extended").sum() == 1
    assert df["opt_above_vwap_pct"].iloc[0] == 37.0


def test_handles_gap_event_type(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    _write_jsonl(logs / "gap_log.jsonl", [_gap("2026-05-27T09:16:00+05:30", "GAP_UP")])
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    sync_jsonl_to_parquet()
    df = pd.read_parquet(data / "scc_data_2026-05.parquet")
    gap_rows = df[df["event_type"] == "gap"]
    assert len(gap_rows) == 1
    assert gap_rows.iloc[0]["decision"] == "GAP_UP"
    assert gap_rows.iloc[0]["nifty_gap_pct"] == 0.21


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_second_run_adds_zero_rows(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    _write_jsonl(
        logs / "signals.jsonl",
        [_scan("2026-05-27T10:00:00+05:30"), _scan("2026-05-27T10:05:00+05:30")],
    )
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    first = sync_jsonl_to_parquet()
    second = sync_jsonl_to_parquet()
    assert first["rows_added"] == 2
    assert second["rows_added"] == 0


def test_dedup_key_handles_null_strike(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    rej = {
        "timestamp_ist": "2026-05-27T10:00:00+05:30",
        "event_type": "rejection",
        "symbol": "NIFTY",
        "strike": None,
        "option_type": "CE",
        "rejection_blocker": "C0",
        "rejection_reason": "spot below vwap",
    }
    _write_jsonl(logs / "signals.jsonl", [rej])
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    sync_jsonl_to_parquet()
    second = sync_jsonl_to_parquet()
    assert second["rows_added"] == 0


# ---------------------------------------------------------------------------
# Monthly split
# ---------------------------------------------------------------------------


def test_monthly_split_writes_two_parquet_files(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    _write_jsonl(
        logs / "signals.jsonl",
        [
            _scan("2026-05-30T10:00:00+05:30"),
            _scan("2026-06-01T10:00:00+05:30"),
        ],
    )
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    sync_jsonl_to_parquet()
    assert (data / "scc_data_2026-05.parquet").exists()
    assert (data / "scc_data_2026-06.parquet").exists()


# ---------------------------------------------------------------------------
# Empty-state handling
# ---------------------------------------------------------------------------


def test_sync_returns_zero_when_no_jsonl_files(isolated_paths) -> None:
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    result = sync_jsonl_to_parquet()
    assert result["rows_added"] == 0
    assert result["months_updated"] == 0


def test_malformed_json_line_is_skipped(isolated_paths) -> None:
    logs, data, _ = isolated_paths
    p = logs / "signals.jsonl"
    p.write_text(
        json.dumps(_scan("2026-05-27T10:00:00+05:30")) + "\n"
        + "{not-valid-json\n"
        + json.dumps(_scan("2026-05-27T10:05:00+05:30")) + "\n",
        encoding="utf-8",
    )
    from src.dashboard.data_writer import sync_jsonl_to_parquet

    result = sync_jsonl_to_parquet()
    assert result["rows_added"] == 2


# ---------------------------------------------------------------------------
# Excel notes best-effort
# ---------------------------------------------------------------------------


def test_sync_excel_notes_skipped_when_no_excel(isolated_paths) -> None:
    from src.dashboard.data_writer import sync_excel_notes_to_parquet

    result = sync_excel_notes_to_parquet()
    assert result["alerts_updated"] == 0
    assert "skipped_reason" in result


def test_sync_excel_notes_skipped_when_excel_empty(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Order Place"
    ws.append(["Timestamp IST", "Symbol", "Strike", "Option", "Order Status"])
    wb.save(dashboards / "dashboard_2026_Q2.xlsx")

    from src.dashboard.data_writer import sync_excel_notes_to_parquet

    result = sync_excel_notes_to_parquet()
    assert result["alerts_updated"] == 0


def test_sync_excel_notes_writes_outcome_back_to_parquet(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    _write_jsonl(
        logs / "alerts.jsonl",
        [_alert("2026-05-27T10:35:00+05:30")],
    )
    from src.dashboard.data_writer import (
        sync_excel_notes_to_parquet,
        sync_jsonl_to_parquet,
    )

    sync_jsonl_to_parquet()

    # Build a stub Order Place sheet with a filled order_status.
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Order Place"
    ws.append(
        ["Timestamp IST", "Symbol", "Strike", "Option",
         "Order Status", "Exit Price", "P&L", "User Notes"]
    )
    ws.append(
        ["2026-05-27T10:35:00+05:30", "NIFTY", 24050, "CE",
         "TP2_HIT", 175.0, 7500.0, "felt right"]
    )
    wb.save(dashboards / "dashboard_2026_Q2.xlsx")

    res = sync_excel_notes_to_parquet()
    assert res["alerts_updated"] >= 1

    df = pd.read_parquet(data / "scc_data_2026-05.parquet")
    alert_row = df[df["event_type"] == "alert"].iloc[0]
    assert alert_row["order_status"] == "TP2_HIT"
    assert float(alert_row["pnl_rupees"]) == pytest.approx(7500.0)
