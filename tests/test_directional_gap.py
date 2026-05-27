"""Phase 5.2 — directional gap label tests.

Replaces the legacy NORMAL / GAP_DAY / GAP_DETECTED_BUT_DISABLED set
with the new directional vocabulary:

  - NORMAL
  - GAP_UP / GAP_DOWN  (rule enabled, threshold breached)
  - GAP_UP_DISABLED / GAP_DOWN_DISABLED  (rule disabled, threshold breached)

Tests stub the spot-candle feed via MagicMock — no broker calls.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.main import Orchestrator

IST = ZoneInfo("Asia/Kolkata")


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_time_rules(*, gap_day_enabled=True, threshold=1.0, direction="both"):
    return _NS(
        normal_start_time="09:45",
        gap_day_start_time="10:15",
        last_entry_time="14:30",
        soft_squareoff_time="14:55",
        hard_squareoff_time="15:00",
        gap_day_enabled=gap_day_enabled,
        gap_day_threshold_pct=threshold,
        gap_day_direction=direction,
    )


def _make_config(time_rules):
    return _NS(
        time_rules=time_rules,
        circuit_breakers=_NS(
            daily_sl_count_breaker=True, max_sl_per_day=2,
            daily_loss_breaker=True, max_loss_per_day_rupees=6000.0,
        ),
        instruments=_NS(
            nifty_enabled=True, banknifty_enabled=True,
            nifty_lot_size=65, banknifty_lot_size=30,
        ),
        logging=_NS(log_level="INFO", log_every_signal_check=True,
                    log_indicator_values=True, log_extended_zone=True),
    )


@pytest.fixture
def orch(tmp_path) -> Orchestrator:
    o = object.__new__(Orchestrator)
    o.config = _make_config(_make_time_rules())
    o.gap_log_path = tmp_path / "gap_log.jsonl"
    o.gap_info = {}
    o.feed = MagicMock()
    o.broker_name = "kite"
    return o


def _candle_df(*, prev_close, today_open):
    today = datetime.now(IST).date()
    from datetime import timedelta

    prev = today - timedelta(days=1)
    return pd.DataFrame({
        "timestamp": [
            datetime(prev.year, prev.month, prev.day, 15, 25, tzinfo=IST),
            datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST),
        ],
        "open": [prev_close, today_open],
        "high": [prev_close, today_open],
        "low": [prev_close, today_open],
        "close": [prev_close, today_open + 5],
        "volume": [1000, 1000],
        "oi": [0, 0],
    })


def test_gap_up_label_when_positive_breach_and_enabled(orch) -> None:
    orch.feed.get_5min_candles = MagicMock(
        return_value=_candle_df(prev_close=24000.0, today_open=24480.0)
    )
    is_gap_day, info = orch._detect_gap_day()
    assert info["decision"] == "GAP_UP"
    assert is_gap_day is True


def test_gap_down_label_when_negative_breach_and_enabled(orch) -> None:
    orch.feed.get_5min_candles = MagicMock(
        return_value=_candle_df(
            prev_close=24000.0, today_open=24000.0 * 0.98
        )
    )
    is_gap_day, info = orch._detect_gap_day()
    assert info["decision"] == "GAP_DOWN"
    assert is_gap_day is True


def test_gap_up_disabled_label_when_positive_breach_and_toggle_off(orch) -> None:
    orch.config = _make_config(_make_time_rules(gap_day_enabled=False))
    orch.feed.get_5min_candles = MagicMock(
        return_value=_candle_df(prev_close=24000.0, today_open=24480.0)
    )
    is_gap_day, info = orch._detect_gap_day()
    assert info["decision"] == "GAP_UP_DISABLED"
    assert is_gap_day is False


def test_gap_down_disabled_label_when_negative_breach_and_toggle_off(orch) -> None:
    orch.config = _make_config(_make_time_rules(gap_day_enabled=False))
    orch.feed.get_5min_candles = MagicMock(
        return_value=_candle_df(
            prev_close=24000.0, today_open=24000.0 * 0.98
        )
    )
    is_gap_day, info = orch._detect_gap_day()
    assert info["decision"] == "GAP_DOWN_DISABLED"
    assert is_gap_day is False


def test_normal_label_when_below_threshold(orch) -> None:
    orch.feed.get_5min_candles = MagicMock(
        return_value=_candle_df(prev_close=24000.0, today_open=24050.0)
    )
    is_gap_day, info = orch._detect_gap_day()
    assert info["decision"] == "NORMAL"
    assert is_gap_day is False


def test_gap_log_jsonl_captures_directional_label(orch) -> None:
    orch.feed.get_5min_candles = MagicMock(
        return_value=_candle_df(prev_close=24000.0, today_open=24480.0)
    )
    orch._detect_gap_day()
    lines = orch.gap_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json
    rec = json.loads(lines[0])
    assert rec["decision"] == "GAP_UP"
