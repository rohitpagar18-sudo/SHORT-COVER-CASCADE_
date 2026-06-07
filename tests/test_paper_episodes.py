"""Phase 5D — episode-collapse tests.

Pure-function tests against ``src.paper.episodes``. No broker / no
file I/O — frames are built inline.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.paper.episodes import (
    collapse_into_episodes,
    derive_alert_id,
    episode_representatives,
)

IST = ZoneInfo("Asia/Kolkata")


def _alert(
    *,
    when: str,
    symbol: str = "NIFTY",
    strike: int = 24050,
    option_type: str = "CE",
    relation: str = "ATM",
    expiry: str = "2026-06-02",
    candle_ts: str | None = None,
    extra: dict | None = None,
) -> dict:
    rec = {
        "timestamp_ist": when,
        "candle_timestamp": candle_ts if candle_ts is not None else when,
        "symbol": symbol,
        "strike": strike,
        "option_type": option_type,
        "relation": relation,
        "expiry": expiry,
        "entry": 150.0,
        "sl": 140.0,
        "tp1": 165.0,
        "tp2": 175.0,
        "lots": 3,
        "date": when[:10],
    }
    if extra:
        rec.update(extra)
    return rec


def test_derive_alert_id_uses_candle_timestamp():
    row = _alert(when="2026-05-27T10:35:00+05:30")
    alert_id, fallback = derive_alert_id(row)
    assert "2026-05-27" in alert_id
    assert "NIFTY" in alert_id
    assert "24050" in alert_id
    assert "CE" in alert_id
    assert fallback is False


def test_derive_alert_id_falls_back_to_alert_time_for_legacy_rows():
    row = _alert(when="2026-05-27T10:35:00+05:30")
    row.pop("candle_timestamp")
    row["alert_time"] = row["timestamp_ist"]
    alert_id, fallback = derive_alert_id(row)
    assert fallback is True
    assert "2026-05-27" in alert_id


def test_eight_refires_collapse_to_one_representative_seven_echoes():
    """A continuous run of 8 re-fires of one move = 1 rep + 7 echoes."""
    rows = [
        _alert(when=f"2026-05-27T10:{mm:02d}:00+05:30")
        for mm in (5, 10, 15, 20, 25, 30, 35, 40)
    ]
    df = pd.DataFrame(rows)
    annotated, episodes = collapse_into_episodes(
        df,
        episode_key=["symbol", "option_type"],
        dedup_window_minutes=40,  # window covers all 8
        relation_priority=["ITM1", "ATM", "ITM2"],
    )
    assert len(episodes) == 1
    ep = episodes[0]
    assert len(ep.member_indices) == 8
    assert len(ep.echo_indices) == 7
    reps = episode_representatives(annotated)
    assert len(reps) == 1
    # The representative is the EARLIEST candle_timestamp.
    rep = reps.iloc[0]
    assert rep["candle_ts"].minute == 5


def test_window_expiry_splits_into_two_episodes():
    """A re-fire OUTSIDE the dedup window starts a new episode."""
    rows = [
        _alert(when="2026-05-27T10:00:00+05:30"),
        _alert(when="2026-05-27T10:15:00+05:30"),   # in-window
        _alert(when="2026-05-27T11:00:00+05:30"),   # out-of-window → new ep
    ]
    df = pd.DataFrame(rows)
    annotated, episodes = collapse_into_episodes(
        df,
        episode_key=["symbol", "option_type"],
        dedup_window_minutes=20,
        relation_priority=["ITM1", "ATM"],
    )
    assert len(episodes) == 2
    assert episode_representatives(annotated).shape[0] == 2


def test_same_candle_ts_tie_break_prefers_itm1():
    """Multiple strikes on the same candle_timestamp → relation_priority wins."""
    when = "2026-05-27T10:00:00+05:30"
    rows = [
        _alert(when=when, strike=24000, relation="ATM"),
        _alert(when=when, strike=23950, relation="ITM1"),
        _alert(when=when, strike=23900, relation="ITM2"),
    ]
    df = pd.DataFrame(rows)
    annotated, episodes = collapse_into_episodes(
        df,
        # ATM tie-break edge: episode_key is (symbol, option_type) so
        # all three rows live in the same episode and the tie-break
        # picks the relation_priority winner.
        episode_key=["symbol", "option_type"],
        dedup_window_minutes=20,
        relation_priority=["ITM1", "ATM", "ITM2", "ITM3", "OTM1", "OTM2", "OTM3"],
    )
    assert len(episodes) == 1
    rep = episode_representatives(annotated).iloc[0]
    assert rep["relation"] == "ITM1"


def test_different_option_types_are_separate_episodes():
    when = "2026-05-27T10:00:00+05:30"
    rows = [
        _alert(when=when, option_type="CE"),
        _alert(when=when, option_type="PE"),
    ]
    df = pd.DataFrame(rows)
    _, episodes = collapse_into_episodes(
        df,
        episode_key=["symbol", "option_type"],
        dedup_window_minutes=20,
        relation_priority=["ITM1", "ATM"],
    )
    assert len(episodes) == 2


def test_legacy_fallback_marks_fidelity_note():
    rows = [
        {
            "timestamp_ist": "2026-05-27T10:35:00+05:30",
            "symbol": "NIFTY", "strike": 24050,
            "option_type": "CE", "relation": "ATM",
            "expiry": "2026-06-02",
            "entry": 150.0, "sl": 140.0, "tp1": 165.0, "tp2": 175.0,
            "lots": 3,
        }
    ]
    df = pd.DataFrame(rows)
    annotated, _ = collapse_into_episodes(
        df,
        episode_key=["symbol", "option_type"],
        dedup_window_minutes=20,
        relation_priority=["ITM1", "ATM"],
    )
    assert annotated.iloc[0]["fidelity_note"] == "legacy_pre_candle_ts"
