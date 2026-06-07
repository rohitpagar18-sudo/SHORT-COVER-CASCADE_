"""Phase 5D — persistence + override-merge tests.

The user-owned ``paper_overrides.csv`` is never rewritten by code;
the generator only creates it empty when missing. Manual values
always win over auto values in ``merge_overrides``.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from src.paper.persistence import (
    OVERRIDE_COLUMNS,
    PaperTradeRecord,
    ensure_overrides_file,
    merge_overrides,
    read_overrides,
    read_paper_trades,
    write_paper_trades,
)


def _rec(aid: str, decision: str = "TAKEN", outcome: str = "TP2_HIT") -> PaperTradeRecord:
    return PaperTradeRecord(
        alert_id=aid,
        episode_id="e1",
        paper_role="representative",
        date="2026-05-27",
        candle_timestamp="2026-05-27T10:00:00+05:30",
        symbol="NIFTY",
        strike=24050,
        relation="ATM",
        option_type="CE",
        expiry="2026-06-02",
        entry=150.0, sl=140.0, tp1=165.0, tp2=175.0,
        lots=3, lot_size=65, is_expiry_day=False,
        decision=decision,
        decision_reason="for test",
        slot=1 if decision == "TAKEN" else None,
        outcome=outcome,
        exit_price=175.0, exit_time="2026-05-27T10:20:00+05:30",
        exit_reason="TP2",
        realized_R=2.5, paper_pnl=4875.0, paper_pnl_per_unit=25.0,
        mfe=25.0, mae=2.0,
        mfe_R=2.5, mae_R=0.2, max_drawdown_R=-0.2,
        intrabar_ambiguous=False, fidelity="ohlc", fidelity_note=None,
    )


def test_write_and_read_paper_trades_round_trip(tmp_path: Path):
    p = tmp_path / "paper_trades.jsonl"
    write_paper_trades(p, [_rec("a1"), _rec("a2", decision="SKIPPED", outcome="OPEN_SQOFF")])
    df = read_paper_trades(p)
    assert len(df) == 2
    assert set(df["alert_id"]) == {"a1", "a2"}


def test_ensure_overrides_creates_with_headers(tmp_path: Path):
    p = tmp_path / "paper_overrides.csv"
    assert not p.exists()
    ensure_overrides_file(p)
    assert p.exists()
    with p.open("r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(OVERRIDE_COLUMNS)
    assert len(rows) == 1  # only the header


def test_ensure_overrides_never_overwrites_existing(tmp_path: Path):
    p = tmp_path / "paper_overrides.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(OVERRIDE_COLUMNS)
        writer.writerow(["a1", "SKIPPED", "my reason", "Whipsaw", "", "user note"])
    ensure_overrides_file(p)  # should not touch the file
    df = read_overrides(p)
    assert len(df) == 1
    assert df.iloc[0]["manual_outcome"] == "Whipsaw"


def test_manual_override_wins_over_auto(tmp_path: Path):
    trades = pd.DataFrame([
        _rec("a1").__dict__,
        _rec("a2", outcome="SL_HIT").__dict__,
    ])
    overrides_path = tmp_path / "paper_overrides.csv"
    with overrides_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(OVERRIDE_COLUMNS)
        w.writerow(["a2", "TAKEN", "I caught this one", "TP2", "175", "my note"])

    overrides = read_overrides(overrides_path)
    merged = merge_overrides(trades, overrides)

    a1 = merged[merged["alert_id"] == "a1"].iloc[0]
    a2 = merged[merged["alert_id"] == "a2"].iloc[0]

    # a1 untouched — manual columns stay empty.
    assert a1["manual_outcome"] in (None, "")
    assert a1["effective_outcome"] == "TP2_HIT"

    # a2 — manual wins.
    assert a2["manual_outcome"] == "TP2"
    assert a2["effective_outcome"] == "TP2"
    assert a2["effective_decision"] == "TAKEN"


def test_overrides_survive_paper_trades_regeneration(tmp_path: Path):
    """Re-running the generator MUST NOT touch paper_overrides.csv."""
    overrides_path = tmp_path / "paper_overrides.csv"
    ensure_overrides_file(overrides_path)
    with overrides_path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["a1", "TAKEN", "fix it", "SL", "140", "regenerated note"])

    before = overrides_path.read_text(encoding="utf-8")

    # Simulate a dashboard regeneration that always writes paper_trades.jsonl
    # and re-runs ensure_overrides_file. The CSV must be unchanged.
    write_paper_trades(tmp_path / "paper_trades.jsonl", [_rec("a1")])
    ensure_overrides_file(overrides_path)

    after = overrides_path.read_text(encoding="utf-8")
    assert before == after
