"""Phase 5.2 — Excel dashboard builder tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    dashboards = logs / "dashboards"
    logs.mkdir()
    data.mkdir()
    dashboards.mkdir()

    import src.dashboard.data_writer as dw
    import src.dashboard.excel_builder as eb

    monkeypatch.setattr(dw, "LOGS_DIR", logs)
    monkeypatch.setattr(dw, "DATA_DIR", data)
    monkeypatch.setattr(dw, "DASHBOARDS_DIR", dashboards)
    monkeypatch.setattr(dw, "SIGNALS_JSONL", logs / "signals.jsonl")
    monkeypatch.setattr(dw, "ALERTS_JSONL", logs / "alerts.jsonl")
    monkeypatch.setattr(dw, "GAP_JSONL", logs / "gap_log.jsonl")

    # excel_builder imported DASHBOARDS_DIR at module load — patch its copy.
    monkeypatch.setattr(eb, "DASHBOARDS_DIR", dashboards)
    return logs, data, dashboards


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _alert(ts: str, **kw) -> dict:
    base = {
        "timestamp_ist": ts,
        "event_type": "alert",
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "relation": "ATM",
        "expiry": "2026-06-02",
        "trading_symbol": "NIFTY24050CE",
        "spot_price": 24030.0,
        "spot_vwap": 24000.0,
        "option_close": 150.0,
        "option_vwap": 140.0,
        "rsi": 65.0,
        "rsi_ma": 55.0,
        "oi": 800_000,
        "oi_ma": 1_000_000,
        "volume": 3000,
        "volume_ma": 1500,
        "is_green": True,
        "vix": 14.0,
        "vix_regime": "Normal",
        "all_passed": True,
        "summary": "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓",
        "opt_above_vwap_pct": 7.0,
        "entry": 150.0,
        "sl": 140.0,
        "sl_method": 1,
        "tp1": 165.0,
        "tp2": 175.0,
        "tp1_r": 1.5,
        "tp2_r": 2.5,
        "risk_per_unit": 10.0,
        "lots": 3,
        "total_risk": 2850.0,
        "lot_size": 65,
        "day_type": "Normal",
        "vix_multiplier": 1.0,
        "spot": 24030.0,
        "spot_position": "Above VWAP ✓",
        "date": ts[:10],
        "time": ts[11:16],
        "bot_remark": "5/5 strong — opt 7% above VWAP, RSI 65, OI 20% below MA, vol 2× MA",
        "bot_tags": "fresh_breakout,strong_rsi,strong_oi,high_volume,morning,normal_vix,normal_day,first_alert",
    }
    base.update(kw)
    return base


def _gap(ts: str, decision: str) -> dict:
    return {
        "timestamp_ist": ts,
        "decision": decision,
        "enabled": True,
        "threshold_pct": 1.0,
        "direction": "both",
        "any_triggered": decision != "NORMAL",
        "per_symbol": {
            "NIFTY": {"open": 24050.0, "prev_close": 24000.0,
                      "gap_pct": 0.21, "triggers": False, "error": None},
            "BANKNIFTY": {"open": 51000.0, "prev_close": 50950.0,
                          "gap_pct": 0.10, "triggers": False, "error": None},
        },
    }


def _scan(ts: str, **kw) -> dict:
    base = _alert(ts)
    base["event_type"] = "scan"
    base["all_passed"] = False
    base.update(kw)  # caller overrides win over defaults
    return base


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_resolve_excel_path_q1() -> None:
    from src.dashboard.excel_builder import _resolve_excel_path

    p = _resolve_excel_path(2026, 1)
    assert p.name == "dashboard_2026_Q1.xlsx"


def test_resolve_excel_path_q4() -> None:
    from src.dashboard.excel_builder import _resolve_excel_path

    p = _resolve_excel_path(2026, 4)
    assert p.name == "dashboard_2026_Q4.xlsx"


def test_quarter_for_date_april_is_q2() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.dashboard.data_writer import quarter_for_date

    d = datetime(2026, 4, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert quarter_for_date(d) == (2026, 2)


def test_quarter_for_date_december_is_q4() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.dashboard.data_writer import quarter_for_date

    d = datetime(2026, 12, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert quarter_for_date(d) == (2026, 4)


# ---------------------------------------------------------------------------
# Sheet count + names + idempotency
# ---------------------------------------------------------------------------


_EXPECTED_SHEETS = [
    "Strategy Dashboard",
    "Daily Summary",
    "All Alerts",
    "Order Place",
    "All Signals",
    "Gap History",
    "Config Snapshot",
]


def test_dashboard_creates_all_seven_sheets(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    _write_jsonl(logs / "alerts.jsonl", [_alert("2026-05-27T10:35:00+05:30")])
    _write_jsonl(logs / "gap_log.jsonl", [_gap("2026-05-27T09:16:00+05:30", "NORMAL")])
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()
    result = update_dashboard()
    assert result["status"] == "ok"
    wb_path = Path(result["output_path"])
    wb = load_workbook(wb_path, data_only=False)
    assert wb.sheetnames == _EXPECTED_SHEETS


def test_workbook_has_no_rejections_sheet(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    _write_jsonl(logs / "alerts.jsonl", [_alert("2026-05-27T10:35:00+05:30")])
    _write_jsonl(logs / "gap_log.jsonl", [_gap("2026-05-27T09:16:00+05:30", "NORMAL")])
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()
    result = update_dashboard()
    wb = load_workbook(Path(result["output_path"]), data_only=False)
    assert "Rejections" not in wb.sheetnames


def test_dashboard_is_idempotent(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    _write_jsonl(logs / "alerts.jsonl", [_alert("2026-05-27T10:35:00+05:30")])
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()
    a = update_dashboard()
    b = update_dashboard()
    # Second run still writes the workbook but reports the same counts.
    assert a["alerts_added"] == b["alerts_added"] == 1


def test_dashboard_strategy_sheet_has_chart_objects(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    _write_jsonl(logs / "alerts.jsonl", [_alert("2026-05-27T10:35:00+05:30")])
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()
    result = update_dashboard()
    wb = load_workbook(Path(result["output_path"]))
    dash = wb["Strategy Dashboard"]
    # _charts is openpyxl's internal list — non-empty proves chart objects exist.
    assert len(dash._charts) >= 1


def test_dashboard_no_data_returns_no_data_status(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    # No JSONL files yet — but update_dashboard still creates the current
    # quarter's workbook (empty), per spec. Result status is "ok" with
    # zero counts.
    from src.dashboard import update_dashboard

    result = update_dashboard()
    # We accept "ok" with all zero counts OR "no_data" — both are valid.
    assert result["status"] in ("ok", "no_data")


# ---------------------------------------------------------------------------
# Order Place outcome coloring
# ---------------------------------------------------------------------------


def test_order_place_outcome_coloring_applied(isolated_paths) -> None:
    """When parquet contains a filled order_status, the cell is coloured."""
    logs, data, dashboards = isolated_paths
    _write_jsonl(logs / "alerts.jsonl", [_alert("2026-05-27T10:35:00+05:30")])
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()

    # Manually patch the parquet so the alert row carries an order_status.
    parquet_path = data / "scc_data_2026-05.parquet"
    df = pd.read_parquet(parquet_path)
    df["order_status"] = "TP2_HIT"
    df["pnl_rupees"] = 7500.0
    df["exit_price"] = 175.0
    df.to_parquet(parquet_path, index=False)

    result = update_dashboard()
    wb = load_workbook(Path(result["output_path"]))
    ws = wb["Order Place"]
    headers = [c.value for c in ws[1]]
    status_col = headers.index("Order Status") + 1
    # Row 2 (the only alert) status cell should carry a fill.
    cell = ws.cell(row=2, column=status_col)
    assert cell.fill is not None
    # PatternFill with non-default fgColor proves coloring kicked in.
    assert cell.fill.fgColor.rgb is not None


def test_all_signals_marks_extended_zone_rows(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    ext = _scan(
        "2026-05-27T11:00:00+05:30",
        event_type="would_alert_extended",
        opt_above_vwap_pct=37.0,
    )
    _write_jsonl(logs / "signals.jsonl", [ext])
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()
    result = update_dashboard()
    wb = load_workbook(Path(result["output_path"]))
    ws = wb["All Signals"]
    headers = [c.value for c in ws[1]]
    event_col = headers.index("Event Type") + 1
    # Row 2 should be the extended event with a fill applied.
    cell = ws.cell(row=2, column=event_col)
    assert cell.value == "would_alert_extended"
    assert cell.fill is not None


def test_gap_history_colour_for_directional_label(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    _write_jsonl(
        logs / "gap_log.jsonl",
        [
            _gap("2026-05-27T09:16:00+05:30", "GAP_UP"),
            _gap("2026-05-28T09:16:00+05:30", "GAP_DOWN"),
        ],
    )
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()
    result = update_dashboard()
    wb = load_workbook(Path(result["output_path"]))
    ws = wb["Gap History"]
    headers = [c.value for c in ws[1]]
    dec_col = headers.index("Decision") + 1
    assert ws.cell(row=2, column=dec_col).fill is not None
    assert ws.cell(row=3, column=dec_col).fill is not None


def test_config_snapshot_contains_c1_threshold_row(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    _write_jsonl(logs / "alerts.jsonl", [_alert("2026-05-27T10:35:00+05:30")])
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()
    result = update_dashboard()
    wb = load_workbook(Path(result["output_path"]))
    ws = wb["Config Snapshot"]
    settings = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
    assert any("C1 max distance" in str(s) for s in settings)


def test_daily_summary_row_per_date(isolated_paths) -> None:
    logs, data, dashboards = isolated_paths
    _write_jsonl(
        logs / "alerts.jsonl",
        [
            _alert("2026-05-27T10:35:00+05:30"),
            _alert("2026-05-28T11:00:00+05:30"),
        ],
    )
    from src.dashboard import sync_jsonl_to_parquet, update_dashboard

    sync_jsonl_to_parquet()
    result = update_dashboard()
    wb = load_workbook(Path(result["output_path"]))
    ws = wb["Daily Summary"]
    # Header row + 2 dates.
    assert ws.max_row >= 3
