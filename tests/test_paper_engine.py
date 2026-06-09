"""Phase 5D — end-to-end engine tests.

Exercises ``src.paper.engine.run_paper_engine`` against an in-memory
``alerts.jsonl`` and a stub ``candle_source``. Asserts:
  - non-alert / holiday rows are excluded;
  - the engine output records lock-step with the kernel's verdict
    (so we know we didn't rewrite the candle walk);
  - the wrapper never imports a second exit engine.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.paper.engine import run_paper_engine
from src.paper.outcome import OUTCOME_NO_DATA, OUTCOME_TP2

IST = ZoneInfo("Asia/Kolkata")


def _line(rec: dict) -> str:
    return json.dumps(rec) + "\n"


def _alert(when: str, strike: int = 24050, option_type: str = "CE", relation: str = "ATM") -> dict:
    return {
        "timestamp_ist": when,
        "candle_timestamp": when,
        "event_type": "alert",
        "symbol": "NIFTY", "strike": strike, "option_type": option_type,
        "relation": relation, "expiry": "2026-06-02",
        "entry": 150.0, "sl": 140.0, "tp1": 165.0, "tp2": 175.0,
        "lots": 3, "date": when[:10], "day_type": "Normal",
    }


def _candle(hh, mm, o, h, low, c):
    return {
        "timestamp": datetime(2026, 5, 27, hh, mm, tzinfo=IST),
        "open": o, "high": h, "low": low, "close": c,
        "volume": 1000.0, "oi": 100000,
    }


def _tp2_candles():
    rows = [_candle(9, mm, 148, 152, 148, 150) for mm in (15, 20, 25, 30, 35, 40, 45, 50, 55)]
    rows.append(_candle(10, 0, 150, 152, 149, 150))
    rows.append(_candle(10, 5, 150, 166, 149, 165))   # TP1
    rows.append(_candle(10, 10, 165, 176, 160, 174))  # TP2
    return pd.DataFrame(rows)


def test_engine_filters_non_alert_rows(tmp_path: Path, config):
    alerts_path = tmp_path / "alerts.jsonl"
    with alerts_path.open("w", encoding="utf-8") as f:
        f.write(_line(_alert("2026-05-27T10:00:00+05:30")))
        # Non-alert junk that must be ignored:
        f.write(_line({"event_type": "scan", "timestamp_ist": "2026-05-27T10:00:00+05:30"}))
        f.write(_line({"event_type": "data_issue", "issue_type": "holiday"}))
    result = run_paper_engine(
        alerts_path=str(alerts_path),
        app_config=config,
        candle_source=None,
        paper_trades_path=str(tmp_path / "paper_trades.jsonl"),
        overrides_path=str(tmp_path / "paper_overrides.csv"),
        write=False,
    )
    assert len(result.annotated_alerts) == 1


def test_engine_output_matches_kernel_for_tp2(tmp_path: Path, config):
    alerts_path = tmp_path / "alerts.jsonl"
    alerts_path.write_text(
        _line(_alert("2026-05-27T10:00:00+05:30")), encoding="utf-8"
    )
    tp2 = _tp2_candles()

    def source(symbol, strike, option_type, expiry, trading_date):
        return tp2

    result = run_paper_engine(
        alerts_path=str(alerts_path),
        app_config=config,
        candle_source=source,
        paper_trades_path=str(tmp_path / "paper_trades.jsonl"),
        overrides_path=str(tmp_path / "paper_overrides.csv"),
        write=True,
        compute_all_alerts=False,
    )
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec.outcome == OUTCOME_TP2
    assert rec.decision == "TAKEN"
    # Paper R-ladder reads straight from risk_reward (SSOT).
    assert rec.realized_R == pytest.approx(config.risk_reward.normal_day_tp2_r)


def test_engine_reuses_kernel_no_second_walk():
    """Confirm src.paper.outcome relies on src.dashboard.outcome_replay.

    The Phase 5D hard rule says: no second candle walk. We assert it
    by inspecting the module source — any independent walk would
    iterate the candle frame itself.
    """
    import src.paper.outcome as paper_outcome

    src = inspect.getsource(paper_outcome)
    # Must import the kernel
    assert "from src.dashboard.outcome_replay" in src
    # Must call the kernel
    assert "replay_alert(" in src
    # Must NOT iterate candles or call replay_exits independently
    assert "candles.iterrows" not in src
    assert "replay_exits(" not in src


def test_engine_episode_collapse_eight_refires_to_one_record(tmp_path: Path, config):
    alerts_path = tmp_path / "alerts.jsonl"
    # 8 re-fires spaced 5 min apart inside the configured 40-min window.
    with alerts_path.open("w", encoding="utf-8") as f:
        for mm in (5, 10, 15, 20, 25, 30, 35, 40):
            f.write(_line(_alert(f"2026-05-27T10:{mm:02d}:00+05:30")))

    # Widen the dedup window to 40 min so the spec's "8 re-fires of one
    # move" pattern fits in a single episode.
    test_cfg = config.model_copy(
        update={"paper_trading": config.paper_trading.model_copy(
            update={"dedup_window_minutes": 40}
        )}
    )

    result = run_paper_engine(
        alerts_path=str(alerts_path),
        app_config=test_cfg,
        candle_source=None,
        paper_trades_path=str(tmp_path / "paper_trades.jsonl"),
        overrides_path=str(tmp_path / "paper_overrides.csv"),
        write=False,
        compute_all_alerts=False,
    )
    # 8 raw alerts → 1 episode → 1 record.
    assert len(result.episodes) == 1
    assert len(result.records) == 1
    # The 7 echoes are present in the annotated frame.
    assert (result.annotated_alerts["paper_role"] == "echo").sum() == 7
    assert (result.annotated_alerts["paper_role"] == "representative").sum() == 1


def test_paper_trades_jsonl_contains_only_taken(tmp_path: Path, config):
    """paper_trades.jsonl must NEVER contain SKIPPED rows.

    Force SKIPPED rows by triggering the daily cap (default 3) with 4
    distinct (symbol, option_type) episodes — the 4th must be skipped.
    The on-disk JSONL must contain exactly 3 TAKEN records.
    """
    alerts_path = tmp_path / "alerts.jsonl"
    paper_trades_path = tmp_path / "paper_trades.jsonl"

    # 4 distinct episodes via different option_type / strikes,
    # all on the same day. Default max_trades_per_day=3 → last one SKIPPED.
    with alerts_path.open("w", encoding="utf-8") as f:
        f.write(_line(_alert("2026-05-27T10:00:00+05:30", strike=24050, option_type="CE")))
        f.write(_line(_alert("2026-05-27T10:30:00+05:30", strike=24100, option_type="PE")))
        f.write(_line(_alert("2026-05-27T11:00:00+05:30", strike=24150, option_type="CE",
                              relation="ITM1")))
        f.write(_line(_alert("2026-05-27T11:30:00+05:30", strike=24200, option_type="PE",
                              relation="ITM1")))

    result = run_paper_engine(
        alerts_path=str(alerts_path),
        app_config=config,
        candle_source=None,  # outcome=NO_DATA — selector still works
        paper_trades_path=str(paper_trades_path),
        overrides_path=str(tmp_path / "paper_overrides.csv"),
        write=True,
        compute_all_alerts=False,
    )

    # The 4th must be SKIPPED at the selection layer.
    decisions = [s.decision for s in result.selection_results]
    assert decisions.count("TAKEN") == 3
    assert decisions.count("SKIPPED") == 1

    # On-disk JSONL must contain ONLY TAKEN rows.
    lines = [
        json.loads(ln)
        for ln in paper_trades_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(lines) == 3
    for row in lines:
        assert row["decision"] == "TAKEN", f"SKIPPED row leaked into JSONL: {row}"
