"""Tests for src/main.py Orchestrator.

All broker / Telegram / I/O dependencies are mocked. Orchestrator
is constructed via the ``orch`` fixture which bypasses ``__init__``
entirely so we don't need a real config or secrets.env.
"""

from __future__ import annotations

from datetime import datetime, time as dt_time
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.main import Orchestrator

IST = ZoneInfo("Asia/Kolkata")


# ----------------------------------------------------------------------
# Lightweight stand-ins so we don't need to load the real config
# ----------------------------------------------------------------------


class _NS:
    """Anonymous namespace — easier than a Mock for nested attribute trees."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_time_rules(
    *,
    normal_start: str = "09:45",
    gap_day_start: str = "10:15",
    last_entry: str = "14:30",
    soft_squareoff: str = "14:55",
    hard_squareoff: str = "15:00",
    gap_day_enabled: bool = True,
    gap_day_threshold_pct: float = 1.0,
    gap_day_direction: str = "both",
) -> _NS:
    return _NS(
        normal_start_time=normal_start,
        gap_day_start_time=gap_day_start,
        last_entry_time=last_entry,
        soft_squareoff_time=soft_squareoff,
        hard_squareoff_time=hard_squareoff,
        gap_day_enabled=gap_day_enabled,
        gap_day_threshold_pct=gap_day_threshold_pct,
        gap_day_direction=gap_day_direction,
    )


def _make_config(
    *,
    time_rules=None,
    max_sl_per_day: int = 2,
    max_loss_per_day: float = 6000.0,
    daily_sl_breaker: bool = True,
    daily_loss_breaker: bool = True,
) -> _NS:
    return _NS(
        time_rules=time_rules or _make_time_rules(),
        circuit_breakers=_NS(
            daily_sl_count_breaker=daily_sl_breaker,
            max_sl_per_day=max_sl_per_day,
            daily_loss_breaker=daily_loss_breaker,
            max_loss_per_day_rupees=max_loss_per_day,
        ),
        instruments=_NS(
            nifty_enabled=True,
            banknifty_enabled=True,
            nifty_lot_size=65,
            banknifty_lot_size=30,
        ),
        logging=_NS(
            log_level="INFO",
            log_every_signal_check=True,
            log_indicator_values=True,
        ),
        telegram=_NS(
            send_signal_alerts=True,
            send_rejection_alerts=False,
            send_eod_summary=True,
            send_circuit_breaker_alerts=True,
            send_startup_alert=True,
        ),
        mode=_NS(
            alert_mode=True,
            order_place_mode=False,
            paper_trade_mode=True,
        ),
        stop_loss=_NS(
            method=1, use_vix_multiplier=True,
            hard_exit_red_candle_below_vwap=True,
        ),
        bot=_NS(
            scan_buffer_seconds=20,
            api_retry_count=0,
            api_retry_delay_seconds=0,
            state_persistence_enabled=True,
        ),
        conditions=_NS(
            c3_rsi_min=50, c3_rsi_max=80,
            c0_spot_trend_filter_enabled=False,
            c1_max_distance_pct=30,
            c1_extended_zone_enabled=True,
            c1_extended_zone_max_pct=50,
        ),
    )


@pytest.fixture
def orch(tmp_path) -> Orchestrator:
    """Orchestrator instance with __init__ bypassed (no real config load)."""
    o = object.__new__(Orchestrator)
    o.config = _make_config()
    o.gap_log_path = tmp_path / "gap_log.jsonl"
    o.gap_info = {}
    o.feed = MagicMock()
    o.telegram = MagicMock()
    o.signal_logger = MagicMock()
    o.state = MagicMock()
    o.state._state = MagicMock(circuit_breaker_triggered=False, circuit_breaker_reason=None)
    o.state.get_daily_sl_count = MagicMock(return_value=0)
    o.state.get_daily_loss = MagicMock(return_value=0.0)
    o.broker_name = "kite"
    o.session_vix = 14.0
    o.session_vix_info = _NS(
        regime=_NS(value="Normal"),
        method1_multiplier=1.0,
        method2_sl_normal_pct=5.0,
        method2_sl_expiry_pct=15.0,
        label="Normal",
        vix_value=14.0,
    )
    o.is_gap_day = False
    o.nifty_lot = 65
    o.banknifty_lot = 30
    o.nifty_expiry = None
    o.banknifty_expiry = None
    o.session_scan_count = 0
    o.session_alert_count = 0
    o.session_nifty_alerts = 0
    o.session_bn_alerts = 0
    o.dashboard_synced = False
    o.market_status = None
    o.holiday_abort = False
    return o


# ----------------------------------------------------------------------
# Market-hours / scan-time tests
# ----------------------------------------------------------------------


def _dt(hh: int, mm: int, weekday: int = 1) -> datetime:
    """A weekday IST datetime — defaults to Tuesday."""
    # 2026-05-26 is a Tuesday — wkday=1
    base = datetime(2026, 5, 26, hh, mm, tzinfo=IST)
    # Shift if a different weekday wanted.
    delta_days = (weekday - base.weekday()) % 7
    return base.replace(day=base.day + delta_days)


def test_is_market_hours_weekday_open(orch) -> None:
    assert orch._is_market_hours(_dt(10, 30, weekday=1)) is True


def test_is_market_hours_weekend_closed(orch) -> None:
    saturday = datetime(2026, 5, 30, 10, 30, tzinfo=IST)
    sunday = datetime(2026, 5, 31, 10, 30, tzinfo=IST)
    assert saturday.weekday() == 5
    assert orch._is_market_hours(saturday) is False
    assert orch._is_market_hours(sunday) is False


def test_is_market_hours_before_open(orch) -> None:
    assert orch._is_market_hours(_dt(9, 14)) is False


def test_is_market_hours_after_close(orch) -> None:
    assert orch._is_market_hours(_dt(15, 31)) is False


def test_is_scan_time_before_945_normal_day(orch) -> None:
    orch.is_gap_day = False
    assert orch._is_scan_time(_dt(9, 30)) is False


def test_is_scan_time_before_1015_gap_day(orch) -> None:
    orch.is_gap_day = True
    # 09:50 — before gap-day start of 10:15, even though after normal 9:45.
    assert orch._is_scan_time(_dt(9, 50)) is False
    assert orch._is_scan_time(_dt(10, 10)) is False
    assert orch._is_scan_time(_dt(10, 16)) is True


def test_is_scan_time_during_window(orch) -> None:
    orch.is_gap_day = False
    assert orch._is_scan_time(_dt(11, 0)) is True
    assert orch._is_scan_time(_dt(14, 25)) is True


def test_is_scan_time_after_1430(orch) -> None:
    orch.is_gap_day = False
    assert orch._is_scan_time(_dt(14, 31)) is False
    assert orch._is_scan_time(_dt(15, 0)) is False


def test_is_hard_squareoff_after_3pm(orch) -> None:
    assert orch._is_hard_squareoff_time(_dt(15, 0)) is True
    assert orch._is_hard_squareoff_time(_dt(15, 1)) is True
    assert orch._is_hard_squareoff_time(_dt(14, 59)) is False


# ----------------------------------------------------------------------
# Circuit breaker tests
# ----------------------------------------------------------------------


def test_trigger_circuit_breaker_at_2_sl(orch) -> None:
    """When daily SL count == config.max_sl_per_day, scan triggers CB."""
    orch.state.get_daily_sl_count.return_value = 2
    orch.config = _make_config(max_sl_per_day=2)
    orch._scan_symbol = MagicMock()  # nothing should be scanned

    # Pretend we're inside the scan window so we get past the time gate.
    orch.is_gap_day = False
    fake_now = _dt(10, 30)
    import src.main as main_mod
    real_now = main_mod.datetime
    main_mod.datetime = type(
        "_DT", (real_now,), {"now": classmethod(lambda cls, tz=None: fake_now)}
    )
    main_mod.load_config = MagicMock(return_value=orch.config)
    try:
        orch.scan_once()
    finally:
        main_mod.datetime = real_now

    orch.state.trigger_circuit_breaker.assert_called_once()
    orch._scan_symbol.assert_not_called()


def test_trigger_circuit_breaker_at_6k_loss(orch) -> None:
    orch.state.get_daily_loss.return_value = 6000.0
    orch.config = _make_config(max_loss_per_day=6000.0)
    orch._scan_symbol = MagicMock()
    orch.is_gap_day = False

    fake_now = _dt(10, 30)
    import src.main as main_mod
    real_now = main_mod.datetime
    main_mod.datetime = type(
        "_DT", (real_now,), {"now": classmethod(lambda cls, tz=None: fake_now)}
    )
    main_mod.load_config = MagicMock(return_value=orch.config)
    try:
        orch.scan_once()
    finally:
        main_mod.datetime = real_now

    orch.state.trigger_circuit_breaker.assert_called_once()


def test_circuit_breaker_blocks_further_scans(orch) -> None:
    """Already-tripped breaker short-circuits scan_once before symbol loop."""
    orch.state._state.circuit_breaker_triggered = True
    orch.state._state.circuit_breaker_reason = "Pre-tripped"
    orch._scan_symbol = MagicMock()
    orch.is_gap_day = False

    fake_now = _dt(10, 30)
    import src.main as main_mod
    real_now = main_mod.datetime
    main_mod.datetime = type(
        "_DT", (real_now,), {"now": classmethod(lambda cls, tz=None: fake_now)}
    )
    main_mod.load_config = MagicMock(return_value=orch.config)
    try:
        orch.scan_once()
    finally:
        main_mod.datetime = real_now

    orch._scan_symbol.assert_not_called()
    orch.state.trigger_circuit_breaker.assert_not_called()


# ----------------------------------------------------------------------
# Token freshness tests
# ----------------------------------------------------------------------


def test_token_freshness_kite_stale_raises(orch, monkeypatch) -> None:
    orch.broker_name = "kite"
    monkeypatch.setenv("KITE_TOKEN_DATE", "1999-01-01")
    with pytest.raises(RuntimeError, match="stale"):
        orch._verify_token_freshness()


def test_token_freshness_kite_today_ok(orch, monkeypatch) -> None:
    orch.broker_name = "kite"
    today_str = datetime.now(IST).date().isoformat()
    monkeypatch.setenv("KITE_TOKEN_DATE", today_str)
    # No raise — completes silently.
    orch._verify_token_freshness()


def test_token_freshness_kite_missing_raises(orch, monkeypatch) -> None:
    orch.broker_name = "kite"
    monkeypatch.delenv("KITE_TOKEN_DATE", raising=False)
    with pytest.raises(RuntimeError):
        orch._verify_token_freshness()


def test_token_freshness_upstox_missing_raises(orch, monkeypatch) -> None:
    orch.broker_name = "upstox"
    monkeypatch.delenv("UPSTOX_TOKEN_DATE", raising=False)
    with pytest.raises(RuntimeError, match="UPSTOX_TOKEN_DATE missing"):
        orch._verify_token_freshness()


def test_token_freshness_upstox_recent_ok(orch, monkeypatch) -> None:
    orch.broker_name = "upstox"
    today = datetime.now(IST).date().isoformat()
    monkeypatch.setenv("UPSTOX_TOKEN_DATE", today)
    orch._verify_token_freshness()


def test_token_freshness_upstox_invalid_format_raises(
    orch, monkeypatch
) -> None:
    orch.broker_name = "upstox"
    monkeypatch.setenv("UPSTOX_TOKEN_DATE", "not-a-date")
    with pytest.raises(RuntimeError, match="format invalid"):
        orch._verify_token_freshness()


# ----------------------------------------------------------------------
# Gap-day detection tests
# ----------------------------------------------------------------------


def _make_candle_df(rows: list[tuple[datetime, float, float]]) -> pd.DataFrame:
    """rows = [(timestamp, open, close), ...]"""
    return pd.DataFrame(
        {
            "timestamp": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[2] for r in rows],
            "volume": [1000] * len(rows),
            "oi": [0] * len(rows),
        }
    )


def _gap_df(*, prev_close: float, today_open: float) -> pd.DataFrame:
    """Two-candle DataFrame: yesterday's close + today's open."""
    today = datetime.now(IST).date()
    prev = today.replace(day=max(1, today.day - 1))
    if prev == today:  # 1st of the month — go to previous month
        # Step back to a date that is definitely yesterday-or-earlier.
        prev_dt = datetime(today.year, today.month, today.day, tzinfo=IST)
        prev_dt = prev_dt.replace(day=1)
        # Use day before month-start by going back one second.
        from datetime import timedelta
        prev_dt = prev_dt - timedelta(days=1)
        prev = prev_dt.date()
    return _make_candle_df(
        [
            (
                datetime(prev.year, prev.month, prev.day, 15, 25, tzinfo=IST),
                prev_close,
                prev_close,
            ),
            (
                datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST),
                today_open,
                today_open + 5,
            ),
        ]
    )


def test_gap_detection_disabled_toggle_returns_false(orch) -> None:
    """When gap_day_enabled=False, is_gap_day is always False even on big gaps."""
    orch.config = _make_config(
        time_rules=_make_time_rules(gap_day_enabled=False)
    )
    # 2% gap up — would trigger if enabled.
    df = _gap_df(prev_close=24000.0, today_open=24480.0)
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    is_gap_day, info = orch._detect_gap_day()
    assert is_gap_day is False
    assert info["enabled"] is False
    assert info["decision"] == "GAP_UP_DISABLED"


def test_gap_detection_enabled_under_threshold_returns_false(orch) -> None:
    """Toggle ON, gap < threshold → not a gap day."""
    orch.config = _make_config(
        time_rules=_make_time_rules(gap_day_enabled=True)
    )
    # 0.2% gap.
    df = _gap_df(prev_close=24000.0, today_open=24050.0)
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    is_gap_day, info = orch._detect_gap_day()
    assert is_gap_day is False
    assert info["decision"] == "NORMAL"


def test_gap_detection_enabled_over_threshold_returns_true(orch) -> None:
    """Toggle ON, gap >= threshold → gap day."""
    orch.config = _make_config(
        time_rules=_make_time_rules(gap_day_enabled=True)
    )
    # 2% gap up.
    df = _gap_df(prev_close=24000.0, today_open=24480.0)
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    is_gap_day, info = orch._detect_gap_day()
    assert is_gap_day is True
    assert info["decision"] == "GAP_UP"
    assert info["any_triggered"] is True


def test_gap_detection_symmetric_negative_triggers(orch) -> None:
    """Toggle ON, direction=both, -1.2% gap → gap day."""
    orch.config = _make_config(
        time_rules=_make_time_rules(
            gap_day_enabled=True, gap_day_direction="both"
        )
    )
    # -1.2% gap down.
    df = _gap_df(prev_close=24000.0, today_open=24000.0 * (1 - 0.012))
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    is_gap_day, info = orch._detect_gap_day()
    assert is_gap_day is True
    assert info["decision"] == "GAP_DOWN"


def test_gap_detection_direction_up_only_ignores_negative(orch) -> None:
    """direction=up, -1.2% gap → NOT a gap day."""
    orch.config = _make_config(
        time_rules=_make_time_rules(
            gap_day_enabled=True, gap_day_direction="up"
        )
    )
    df = _gap_df(prev_close=24000.0, today_open=24000.0 * (1 - 0.012))
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    is_gap_day, info = orch._detect_gap_day()
    assert is_gap_day is False
    assert info["decision"] == "NORMAL"


def test_gap_detection_direction_down_only_ignores_positive(orch) -> None:
    """direction=down, +1.2% gap → NOT a gap day."""
    orch.config = _make_config(
        time_rules=_make_time_rules(
            gap_day_enabled=True, gap_day_direction="down"
        )
    )
    df = _gap_df(prev_close=24000.0, today_open=24000.0 * (1 + 0.012))
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    is_gap_day, info = orch._detect_gap_day()
    assert is_gap_day is False
    assert info["decision"] == "NORMAL"


def test_gap_log_jsonl_written_when_disabled(orch) -> None:
    """Math is logged even when toggle is OFF."""
    orch.config = _make_config(
        time_rules=_make_time_rules(gap_day_enabled=False)
    )
    df = _gap_df(prev_close=24000.0, today_open=24480.0)
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    orch._detect_gap_day()
    assert orch.gap_log_path.exists()
    lines = orch.gap_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json as _json
    rec = _json.loads(lines[0])
    assert rec["enabled"] is False
    assert rec["decision"] == "GAP_UP_DISABLED"


def test_gap_log_jsonl_appends_not_truncates(orch) -> None:
    """Two consecutive runs produce 2 lines in gap_log.jsonl."""
    orch.config = _make_config(
        time_rules=_make_time_rules(gap_day_enabled=True)
    )
    df = _gap_df(prev_close=24000.0, today_open=24050.0)
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    orch._detect_gap_day()
    orch._detect_gap_day()
    lines = orch.gap_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_gap_info_decision_field_correct(orch) -> None:
    """Phase 5.2: directional labels — GAP_UP / GAP_DOWN / *_DISABLED / NORMAL."""
    # NORMAL
    orch.config = _make_config(
        time_rules=_make_time_rules(gap_day_enabled=True)
    )
    orch.feed.get_5min_candles = MagicMock(
        return_value=_gap_df(prev_close=24000.0, today_open=24050.0)
    )
    _, info = orch._detect_gap_day()
    assert info["decision"] == "NORMAL"

    # GAP_UP
    orch.gap_log_path.unlink(missing_ok=True)
    orch.feed.get_5min_candles = MagicMock(
        return_value=_gap_df(prev_close=24000.0, today_open=24480.0)
    )
    _, info = orch._detect_gap_day()
    assert info["decision"] == "GAP_UP"

    # GAP_UP_DISABLED — rule OFF but a positive breach still occurred.
    orch.gap_log_path.unlink(missing_ok=True)
    orch.config = _make_config(
        time_rules=_make_time_rules(gap_day_enabled=False)
    )
    orch.feed.get_5min_candles = MagicMock(
        return_value=_gap_df(prev_close=24000.0, today_open=24480.0)
    )
    _, info = orch._detect_gap_day()
    assert info["decision"] == "GAP_UP_DISABLED"


# ----------------------------------------------------------------------
# Scan-loop dedup test (candle_key invariant)
# ----------------------------------------------------------------------


def test_scan_loop_fires_exactly_once_per_candle() -> None:
    """The candle_key dedup tuple is stable across multiple wall-clock ticks
    within the same 5-min window. We don't run the loop — we just verify
    the math of (date, hour, candle_minute) groups all 09:45:05–09:49:59
    timestamps under the same key.
    """
    base_date = datetime(2026, 5, 26, tzinfo=IST).date()

    def candle_key(now: datetime) -> tuple:
        candle_minute = (now.minute // 5) * 5
        return (now.date(), now.hour, candle_minute)

    # Five wall-clock samples in the same 09:45 candle window.
    samples = [
        datetime(2026, 5, 26, 9, 45, 5, tzinfo=IST),
        datetime(2026, 5, 26, 9, 45, 30, tzinfo=IST),
        datetime(2026, 5, 26, 9, 47, 12, tzinfo=IST),
        datetime(2026, 5, 26, 9, 49, 59, tzinfo=IST),
    ]
    keys = {candle_key(s) for s in samples}
    assert keys == {(base_date, 9, 45)}

    # Next candle window 09:50–09:54 must produce a different key.
    next_candle = datetime(2026, 5, 26, 9, 50, 5, tzinfo=IST)
    assert candle_key(next_candle) != (base_date, 9, 45)


def test_scan_loop_trigger_window_uses_scan_buffer_seconds() -> None:
    """The trigger window is [buffer, buffer+25] driven by config.bot.scan_buffer_seconds.

    With scan_buffer_seconds=20 the window is 20–45s into a candle, so Kite
    has time to finalize the just-closed 5-min bar before we fetch it.
    """
    def seconds_into_candle(now: datetime) -> int:
        return (now.minute % 5) * 60 + now.second

    buffer = 20  # mirrors orch fixture and config.yaml default

    boundary = datetime(2026, 5, 26, 9, 45, 0, tzinfo=IST)
    too_early_5 = datetime(2026, 5, 26, 9, 45, 5, tzinfo=IST)
    too_early_19 = datetime(2026, 5, 26, 9, 45, 19, tzinfo=IST)
    inside_low = datetime(2026, 5, 26, 9, 45, 20, tzinfo=IST)
    inside_mid = datetime(2026, 5, 26, 9, 45, 30, tzinfo=IST)
    inside_high = datetime(2026, 5, 26, 9, 45, 45, tzinfo=IST)
    just_after = datetime(2026, 5, 26, 9, 45, 46, tzinfo=IST)
    well_past = datetime(2026, 5, 26, 9, 48, 0, tzinfo=IST)

    def in_window(now: datetime) -> bool:
        s = seconds_into_candle(now)
        return buffer <= s <= buffer + 25

    assert in_window(boundary) is False        # exactly at candle close — too early
    assert in_window(too_early_5) is False     # old hardcoded lower bound — must NOT fire
    assert in_window(too_early_19) is False
    assert in_window(inside_low) is True
    assert in_window(inside_mid) is True
    assert in_window(inside_high) is True
    assert in_window(just_after) is False
    assert in_window(well_past) is False


def test_scan_loop_trigger_window_respects_buffer_at_10s_and_22s(orch) -> None:
    """Within the same candle: +10s must NOT trigger, +22s MUST trigger.

    Drives the same predicate the orchestrator uses, parameterized off
    orch.config.bot.scan_buffer_seconds (=20 in the fixture).
    """
    orch.config.bot.scan_buffer_seconds = 20

    def candle_key(now: datetime):
        return (now.date(), now.hour, (now.minute // 5) * 5)

    def in_window(now: datetime) -> bool:
        s = (now.minute % 5) * 60 + now.second
        buffer = orch.config.bot.scan_buffer_seconds
        return buffer <= s <= buffer + 25

    at_10s = datetime(2026, 5, 26, 10, 5, 10, tzinfo=IST)
    at_22s = datetime(2026, 5, 26, 10, 5, 22, tzinfo=IST)

    # Same candle on both samples.
    assert candle_key(at_10s) == candle_key(at_22s)
    assert in_window(at_10s) is False
    assert in_window(at_22s) is True


def test_scan_buffer_seconds_validation_rejects_out_of_range(tmp_path) -> None:
    """config_loader must reject scan_buffer_seconds outside [5, 60]."""
    from src.config_loader import BotConfig
    from pydantic import ValidationError

    # In-range value accepted.
    BotConfig(
        scan_buffer_seconds=20,
        api_retry_count=3,
        api_retry_delay_seconds=2,
        state_persistence_enabled=True,
    )

    # Below lower bound (would re-introduce the partial-candle bug).
    with pytest.raises(ValidationError):
        BotConfig(
            scan_buffer_seconds=2,
            api_retry_count=3,
            api_retry_delay_seconds=2,
            state_persistence_enabled=True,
        )

    # Above upper bound (would overrun the 300s candle).
    with pytest.raises(ValidationError):
        BotConfig(
            scan_buffer_seconds=120,
            api_retry_count=3,
            api_retry_delay_seconds=2,
            state_persistence_enabled=True,
        )


# ----------------------------------------------------------------------
# EOD summary uses in-memory counters
# ----------------------------------------------------------------------


def test_eod_summary_uses_in_memory_counters(orch) -> None:
    orch.session_scan_count = 42
    orch.session_alert_count = 3
    orch.session_nifty_alerts = 2
    orch.session_bn_alerts = 1
    summary = orch._compute_eod_summary()
    assert summary["total_scans"] == 42
    assert summary["alerts_fired"] == 3
    assert summary["nifty_alerts"] == 2
    assert summary["banknifty_alerts"] == 1
    assert summary["circuit_breaker"] == "NO"


def test_eod_summary_circuit_breaker_yes(orch) -> None:
    orch.state._state.circuit_breaker_triggered = True
    summary = orch._compute_eod_summary()
    assert summary["circuit_breaker"] == "YES"


def test_enabled_instruments_str(orch) -> None:
    assert orch._enabled_instruments_str() == "NIFTY, BANKNIFTY"
    orch.config.instruments.nifty_enabled = False
    assert orch._enabled_instruments_str() == "BANKNIFTY"
    orch.config.instruments.banknifty_enabled = False
    assert orch._enabled_instruments_str() == "NONE"


def test_log_rejection_respects_toggle(orch) -> None:
    orch.config.logging.log_every_signal_check = False
    orch._log_rejection("NIFTY", 24050, "CE", "C0", "test", _dt(10, 30))
    orch.signal_logger.log_rejection.assert_not_called()


def test_log_rejection_logs_when_enabled(orch) -> None:
    orch.config.logging.log_every_signal_check = True
    orch._log_rejection("NIFTY", 24050, "CE", "C0", "test", _dt(10, 30))
    orch.signal_logger.log_rejection.assert_called_once()
    record = orch.signal_logger.log_rejection.call_args[0][0]
    assert record["rejection_blocker"] == "C0"
    assert record["rejection_reason"] == "test"


def test_trigger_circuit_breaker_sends_telegram_when_enabled(orch) -> None:
    orch._trigger_circuit_breaker("test reason")
    orch.state.trigger_circuit_breaker.assert_called_once_with("test reason")
    orch.telegram.send_circuit_breaker.assert_called_once_with("test reason")


def test_trigger_circuit_breaker_skips_telegram_when_disabled(orch) -> None:
    orch.config.telegram.send_circuit_breaker_alerts = False
    orch._trigger_circuit_breaker("test reason")
    orch.state.trigger_circuit_breaker.assert_called_once()
    orch.telegram.send_circuit_breaker.assert_not_called()


# ----------------------------------------------------------------------
# Phase 5.1.5: data_issue vs rejection / gap detection robustness
# ----------------------------------------------------------------------


def test_scan_strike_logs_data_issue_not_rejection_on_insufficient_lookback(
    orch, monkeypatch,
) -> None:
    """When indicator calc raises 'Insufficient lookback', the orchestrator
    must record a data_issue (not a rejection). Keeps rejection analytics
    clean for mid-session bot starts where RSI MA hasn't warmed up.
    """
    import src.main as main_mod

    strike_choice = _NS(
        strike=24050,
        relation="ATM",
        instrument_key="DUMMY",
        trading_symbol="NIFTY24050CE",
    )
    orch.state.can_re_enter = MagicMock(return_value=(True, ""))
    # Feed a non-empty, fresh candle so the new stale-candle guard does
    # NOT fire — we want INSUFFICIENT_LOOKBACK from the indicator calc.
    from datetime import timedelta as _td
    now_local = datetime.now(IST)
    boundary_local = now_local.replace(second=0, microsecond=0) - _td(
        minutes=now_local.minute % 5
    )
    fresh_ts = boundary_local - _td(minutes=5)
    fresh_df = pd.DataFrame([{
        "timestamp": pd.Timestamp(fresh_ts),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        "volume": 1000.0, "oi": 0,
    }])
    orch.feed.get_5min_candles = MagicMock(return_value=fresh_df)

    def _raise_insufficient(_df):
        raise ValueError(
            "Insufficient lookback for indicators ['rsi_ma']; need 33 candles."
        )

    monkeypatch.setattr(main_mod, "get_latest_snapshot", _raise_insufficient)
    orch._scan_strike(
        "NIFTY", strike_choice, "CE", "2026-05-28", 65,
        spot_close=24050.0, spot_vwap=24000.0, now=now_local,
    )

    # Rejection logger must NOT have been called.
    orch.signal_logger.log_rejection.assert_not_called()
    # log_signal must have been called once with event_type='data_issue'.
    orch.signal_logger.log_signal.assert_called_once()
    record = orch.signal_logger.log_signal.call_args[0][0]
    assert record["event_type"] == "data_issue"
    assert record["issue_type"] == "INSUFFICIENT_LOOKBACK"
    assert record["symbol"] == "NIFTY"
    assert record["strike"] == 24050
    assert "Insufficient" in record["issue_message"]


def test_data_issue_skipped_when_logging_toggle_off(orch) -> None:
    """log_every_signal_check OFF must suppress data_issue records too."""
    orch.config.logging.log_every_signal_check = False
    orch._log_data_issue(
        "NIFTY", 24050, "CE", "INSUFFICIENT_LOOKBACK", "msg", _dt(11, 30)
    )
    orch.signal_logger.log_signal.assert_not_called()


def test_gap_detection_succeeds_with_multi_day_candles(orch) -> None:
    """At 11:30 mid-session start, a multi-day candle frame must still
    produce a clean gap math result (not silently 'None%').
    """
    orch.config = _make_config(time_rules=_make_time_rules(gap_day_enabled=True))
    today = datetime.now(IST).date()
    from datetime import timedelta
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev = prev - timedelta(days=1)

    # 75 prev-day candles + 30 today candles (mid-session start at 11:30).
    rows = []
    for i in range(75):
        ts = datetime(prev.year, prev.month, prev.day, 9, 15, tzinfo=IST) + \
            timedelta(minutes=5 * i)
        rows.append((ts, 24000.0, 24000.0))
    for i in range(30):
        ts = datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST) + \
            timedelta(minutes=5 * i)
        rows.append((ts, 24120.0, 24120.0))
    df = _make_candle_df(rows)
    orch.feed.get_5min_candles = MagicMock(return_value=df)

    is_gap_day, info = orch._detect_gap_day()
    nifty = info["per_symbol"]["NIFTY"]
    assert nifty["error"] is None
    assert nifty["gap_pct"] is not None
    # 24120 / 24000 = +0.5% → under 1% threshold.
    assert nifty["gap_pct"] == pytest.approx(0.5, abs=0.01)
    assert is_gap_day is False  # 0.5% < 1% threshold


def test_gap_detection_logs_clear_error_on_no_prev_day_data(orch) -> None:
    """If the candle frame has no prev-day rows, error message must
    include explicit counts (not the old vague 'missing today or prev day').
    """
    today = datetime.now(IST).date()
    from datetime import timedelta
    rows = []
    for i in range(10):
        ts = datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST) + \
            timedelta(minutes=5 * i)
        rows.append((ts, 24000.0, 24000.0))
    df = _make_candle_df(rows)
    orch.feed.get_5min_candles = MagicMock(return_value=df)

    _, info = orch._detect_gap_day()
    nifty_err = info["per_symbol"]["NIFTY"]["error"]
    assert nifty_err is not None
    assert "today_n=" in nifty_err
    assert "prev_n=" in nifty_err


# ----------------------------------------------------------------------
# Phase 5.2.1: finally-block dashboard sync tests
# ----------------------------------------------------------------------


def _make_dashboard_config(*, auto_trigger: bool = True) -> _NS:
    cfg = _make_config()
    cfg.dashboard = _NS(auto_trigger_at_1535=auto_trigger)
    return cfg


def test_dashboard_sync_runs_in_finally_block_on_clean_exit(
    orch, monkeypatch
) -> None:
    """On a weekday with toggle ON, all three sync functions are called exactly once."""
    import src.main as main_mod
    from unittest.mock import patch

    orch.config = _make_dashboard_config(auto_trigger=True)
    orch.dashboard_synced = False

    fake_now = datetime(2026, 5, 26, 10, 30, tzinfo=IST)  # Tuesday
    real_dt = main_mod.datetime
    main_mod.datetime = type(
        "_DT", (real_dt,), {"now": classmethod(lambda cls, tz=None: fake_now)}
    )
    try:
        with patch("src.dashboard.sync_jsonl_to_parquet") as m_sync, \
             patch("src.dashboard.update_dashboard") as m_update, \
             patch("src.dashboard.sync_excel_notes_to_parquet") as m_excel:
            orch._run_dashboard_sync_on_exit()
            m_sync.assert_called_once()
            m_update.assert_called_once()
            m_excel.assert_called_once()
        assert orch.dashboard_synced is True
    finally:
        main_mod.datetime = real_dt


def test_dashboard_sync_runs_on_keyboard_interrupt(orch, monkeypatch) -> None:
    """KeyboardInterrupt mid-loop → finally still calls _run_dashboard_sync_on_exit."""
    import src.main as main_mod

    orch.config = _make_dashboard_config(auto_trigger=True)
    orch.dashboard_synced = False
    orch.setup = MagicMock()
    orch._run_dashboard_sync_on_exit = MagicMock()

    fake_now = datetime(2026, 5, 26, 10, 30, tzinfo=IST)  # mid-session, no break
    real_dt = main_mod.datetime
    main_mod.datetime = type(
        "_DT", (real_dt,), {"now": classmethod(lambda cls, tz=None: fake_now)}
    )
    monkeypatch.setattr(
        main_mod.time_mod, "sleep", MagicMock(side_effect=KeyboardInterrupt())
    )
    try:
        orch.run_forever()
    finally:
        main_mod.datetime = real_dt

    orch._run_dashboard_sync_on_exit.assert_called_once()


def test_dashboard_sync_skipped_on_weekend_exit(orch, monkeypatch) -> None:
    """Saturday/Sunday → sync must NOT run (no market data)."""
    import src.main as main_mod
    from unittest.mock import patch

    orch.config = _make_dashboard_config(auto_trigger=True)
    orch.dashboard_synced = False

    saturday = datetime(2026, 5, 30, 15, 31, tzinfo=IST)  # Saturday
    real_dt = main_mod.datetime
    main_mod.datetime = type(
        "_DT", (real_dt,), {"now": classmethod(lambda cls, tz=None: saturday)}
    )
    try:
        with patch("src.dashboard.sync_jsonl_to_parquet") as m_sync, \
             patch("src.dashboard.update_dashboard") as m_update, \
             patch("src.dashboard.sync_excel_notes_to_parquet") as m_excel:
            orch._run_dashboard_sync_on_exit()
            m_sync.assert_not_called()
            m_update.assert_not_called()
            m_excel.assert_not_called()
    finally:
        main_mod.datetime = real_dt


def test_dashboard_sync_skipped_when_toggle_disabled(orch, monkeypatch) -> None:
    """config.dashboard.auto_trigger_at_1535 = False → no sync on exit."""
    import src.main as main_mod
    from unittest.mock import patch

    orch.config = _make_dashboard_config(auto_trigger=False)
    orch.dashboard_synced = False

    fake_now = datetime(2026, 5, 26, 15, 31, tzinfo=IST)
    real_dt = main_mod.datetime
    main_mod.datetime = type(
        "_DT", (real_dt,), {"now": classmethod(lambda cls, tz=None: fake_now)}
    )
    try:
        with patch("src.dashboard.sync_jsonl_to_parquet") as m_sync:
            orch._run_dashboard_sync_on_exit()
            m_sync.assert_not_called()
    finally:
        main_mod.datetime = real_dt


def test_dashboard_sync_failure_does_not_prevent_exit(orch, monkeypatch) -> None:
    """If sync raises, _run_dashboard_sync_on_exit must not re-raise."""
    import src.main as main_mod
    from unittest.mock import patch

    orch.config = _make_dashboard_config(auto_trigger=True)
    orch.dashboard_synced = False

    fake_now = datetime(2026, 5, 26, 15, 31, tzinfo=IST)
    real_dt = main_mod.datetime
    main_mod.datetime = type(
        "_DT", (real_dt,), {"now": classmethod(lambda cls, tz=None: fake_now)}
    )
    try:
        with patch(
            "src.dashboard.sync_jsonl_to_parquet",
            side_effect=RuntimeError("Parquet write failed"),
        ):
            # Must not raise — bot exit must remain clean.
            orch._run_dashboard_sync_on_exit()
    finally:
        main_mod.datetime = real_dt


# ======================================================================
# Holiday-guard tests (Phase 5.2.2)
#
# Cover the four exits of _check_market_status() — weekend, pre-open,
# candle-check (open / holiday / opening-window pre_open), API error
# fail-open — plus scan_once() gating and the cleanup script.
# pytest-mock is not installed; we use the monkeypatch fixture + the
# same datetime-freezing pattern used elsewhere in this file.
# ======================================================================


def _make_candles(dates: list[str]) -> pd.DataFrame:
    """Build a minimal candle DataFrame for a list of timestamp strings."""
    return pd.DataFrame({
        "timestamp": pd.to_datetime(dates).tz_localize("Asia/Kolkata"),
        "open":   [100.0] * len(dates),
        "high":   [101.0] * len(dates),
        "low":    [99.0]  * len(dates),
        "close":  [100.5] * len(dates),
        "volume": [1000]  * len(dates),
        "oi":     [500000] * len(dates),
    })


def _orch_with_mocked_now(monkeypatch, now_iso: str):
    """Build an Orchestrator with __init__ bypassed and datetime.now frozen.

    Mirrors the existing pattern: subclass real datetime and swap it in
    src.main so dt_time / dt constructors still work normally.
    """
    import src.main as main_mod

    orch = Orchestrator.__new__(Orchestrator)
    orch.market_status = None
    orch.holiday_abort = False
    orch.feed = MagicMock()
    orch.broker_name = "kite"

    fixed_now = datetime.fromisoformat(now_iso).replace(tzinfo=IST)
    real_dt = main_mod.datetime
    FrozenDT = type(
        "_FrozenDT",
        (real_dt,),
        {"now": classmethod(lambda cls, tz=None: fixed_now)},
    )
    monkeypatch.setattr(main_mod, "datetime", FrozenDT)
    return orch, fixed_now


# ----- _check_market_status decision tree -----


def test_market_status_saturday_returns_weekend(monkeypatch):
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-30 11:00")  # Sat
    result = orch._check_market_status()
    assert result.status.value == "weekend"
    orch.feed.get_5min_candles.assert_not_called()


def test_market_status_sunday_returns_weekend(monkeypatch):
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-31 11:00")  # Sun
    result = orch._check_market_status()
    assert result.status.value == "weekend"
    orch.feed.get_5min_candles.assert_not_called()


def test_market_status_before_0915_returns_pre_open(monkeypatch):
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-29 08:45")  # Fri
    result = orch._check_market_status()
    assert result.status.value == "pre_open"
    orch.feed.get_5min_candles.assert_not_called()


def test_market_status_no_today_candles_after_0930_returns_holiday(monkeypatch):
    # 2026-05-28 is the Bakri Id holiday (Thursday).
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-28 10:00")
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-27 14:55", "2026-05-27 15:00", "2026-05-27 15:25"]
    )
    result = orch._check_market_status()
    assert result.status.value == "holiday"
    assert result.today_candle_count == 0


def test_market_status_today_candles_present_returns_open(monkeypatch):
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-29 10:30")
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-29 09:15", "2026-05-29 09:20", "2026-05-29 09:25"]
    )
    result = orch._check_market_status()
    assert result.status.value == "open"
    assert result.today_candle_count == 3


def test_market_status_no_candles_before_0930_returns_pre_open(monkeypatch):
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-29 09:20")
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-28 14:55", "2026-05-28 15:25"]  # prior day only
    )
    result = orch._check_market_status()
    assert result.status.value == "pre_open"


def test_market_status_api_error_returns_unknown_not_holiday(monkeypatch):
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-29 10:30")
    orch.feed.get_5min_candles.side_effect = RuntimeError("Kite timeout")
    result = orch._check_market_status()
    assert result.status.value == "unknown"
    # UNKNOWN is fail-open: must not be mistaken for HOLIDAY evidence.
    assert "timeout" in result.reason.lower() or "error" in result.reason.lower()
    assert orch.holiday_abort is False


# ----- scan_once() gating on holiday_abort -----


def test_scan_once_returns_immediately_when_holiday_abort_true():
    orch = Orchestrator.__new__(Orchestrator)
    orch.holiday_abort = True
    orch.market_status = MagicMock()
    orch.market_status.status.value = "holiday"
    orch.feed = MagicMock()
    orch.signal_logger = MagicMock()
    orch.state = MagicMock()

    orch.scan_once()

    # No state queries, no feed calls, no JSONL writes.
    orch.feed.get_5min_candles.assert_not_called()
    orch.signal_logger.log_signal.assert_not_called()
    orch.signal_logger.log_alert.assert_not_called()


# ----- mark_holiday_scans cleanup script -----


def test_mark_holiday_scans_marks_correct_dates(tmp_path):
    import json
    from scripts.mark_holiday_scans import main as mark_main

    logs = tmp_path / "logs"
    logs.mkdir()

    # gap_log shows 2026-05-28 was a holiday (today_n=0 in error)
    gap = logs / "gap_log.jsonl"
    gap.write_text(json.dumps({
        "timestamp_ist": "2026-05-28T09:16:00+05:30",
        "per_symbol": {
            "NIFTY": {"error": "insufficient_data: today_n=0, prev_n=5"},
            "BANKNIFTY": {"error": "insufficient_data: today_n=0, prev_n=5"},
        },
    }) + "\n")

    # signals.jsonl has rows from holiday and from a normal day
    sig = logs / "signals.jsonl"
    sig.write_text(
        json.dumps({"timestamp_ist": "2026-05-28T10:00:00+05:30", "symbol": "NIFTY"}) + "\n" +
        json.dumps({"timestamp_ist": "2026-05-27T10:00:00+05:30", "symbol": "NIFTY"}) + "\n"
    )

    mark_main(tmp_path)

    lines = [json.loads(l) for l in sig.read_text().splitlines() if l.strip()]
    holiday_row = next(r for r in lines if r["timestamp_ist"].startswith("2026-05-28"))
    normal_row = next(r for r in lines if r["timestamp_ist"].startswith("2026-05-27"))
    assert holiday_row.get("is_holiday_scan") is True
    assert "is_holiday_scan" not in normal_row  # untouched


def test_mark_holiday_scans_idempotent(tmp_path):
    """Running the script twice produces the same result, not double-marked."""
    import json
    from scripts.mark_holiday_scans import main as mark_main

    logs = tmp_path / "logs"
    logs.mkdir()
    gap = logs / "gap_log.jsonl"
    gap.write_text(json.dumps({
        "timestamp_ist": "2026-05-28T09:16:00+05:30",
        "per_symbol": {"NIFTY": {"error": "insufficient_data: today_n=0"}},
    }) + "\n")
    sig = logs / "signals.jsonl"
    sig.write_text(json.dumps({"timestamp_ist": "2026-05-28T10:00:00+05:30"}) + "\n")

    mark_main(tmp_path)
    first_state = sig.read_text()
    mark_main(tmp_path)
    second_state = sig.read_text()

    assert first_state == second_state  # second run did not double-mark


# ======================================================================
# VIX second-source holiday confirmation tests
#
# Cover the five paths through _confirm_holiday_via_vix():
#   - both candles and VIX stale → HOLIDAY confirmed
#   - candles stale, VIX fresh   → flip to UNKNOWN (connectivity glitch)
#   - candles OPEN               → VIX check never invoked
#   - VIX fetch raises           → trust the candle check (HOLIDAY)
#   - VIX returns (value, None)  → trust the candle check (HOLIDAY)
# ======================================================================


def _vix_iso(now_iso: str, minutes_ago: float) -> str:
    """Return an IST ISO timestamp ``minutes_ago`` before ``now_iso``."""
    from datetime import timedelta
    base = datetime.fromisoformat(now_iso).replace(tzinfo=IST)
    return (base - timedelta(minutes=minutes_ago)).isoformat()


def test_holiday_confirmed_when_both_candles_and_vix_stale(monkeypatch):
    """Candle check + VIX both stale → HOLIDAY survives confirmation."""
    now_iso = "2026-05-28 10:00"
    orch, _ = _orch_with_mocked_now(monkeypatch, now_iso)
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-27 14:55", "2026-05-27 15:00", "2026-05-27 15:25"]
    )
    # VIX last tick 2 hours ago — also confirms market is closed.
    orch.feed.get_india_vix_with_timestamp = MagicMock(
        return_value=(12.5, _vix_iso(now_iso, minutes_ago=120))
    )
    result = orch._check_market_status()
    assert result.status.value == "holiday"
    orch.feed.get_india_vix_with_timestamp.assert_called_once()
    assert "VIX confirms" in result.reason


def test_holiday_overridden_when_vix_is_fresh(monkeypatch):
    """Candle check says HOLIDAY but VIX updated 2 min ago → UNKNOWN.

    This is the key glitch scenario: a real trading day where the broker
    candle endpoint hiccupped for 10–30 minutes. Fail-open by flipping
    to UNKNOWN so the loop keeps scanning.
    """
    now_iso = "2026-05-28 10:00"
    orch, _ = _orch_with_mocked_now(monkeypatch, now_iso)
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-27 14:55", "2026-05-27 15:00", "2026-05-27 15:25"]
    )
    orch.feed.get_india_vix_with_timestamp = MagicMock(
        return_value=(13.1, _vix_iso(now_iso, minutes_ago=2.0))
    )
    result = orch._check_market_status()
    assert result.status.value == "unknown"
    assert "VIX fresh" in result.reason
    # Caller has not yet latched holiday_abort — UNKNOWN keeps the loop alive.
    assert orch.holiday_abort is False


def test_vix_check_skipped_when_first_check_is_open(monkeypatch):
    """When the candle check says OPEN, the VIX path must not even fire."""
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-29 10:30")
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-29 09:15", "2026-05-29 09:20", "2026-05-29 09:25"]
    )
    orch.feed.get_india_vix_with_timestamp = MagicMock(
        return_value=(13.1, "2026-05-29T10:28:00+05:30")
    )
    result = orch._check_market_status()
    assert result.status.value == "open"
    orch.feed.get_india_vix_with_timestamp.assert_not_called()


def test_vix_check_failure_defaults_to_trusting_first_check(monkeypatch):
    """If the VIX fetch raises, the candle-check verdict (HOLIDAY) stands."""
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-28 10:00")
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-27 14:55", "2026-05-27 15:00", "2026-05-27 15:25"]
    )
    orch.feed.get_india_vix_with_timestamp = MagicMock(
        side_effect=RuntimeError("Kite timeout")
    )
    result = orch._check_market_status()
    assert result.status.value == "holiday"
    assert "VIX confirms" in result.reason
    assert "errored" in result.reason


def test_vix_check_no_timestamp_field_defaults_to_holiday(monkeypatch):
    """If the feed returns ``(value, None)`` for timestamp, HOLIDAY stands.

    Upstox in particular may not expose a usable last-trade-time field;
    in that case the second check has nothing to verify against and must
    not override the candle check.
    """
    orch, _ = _orch_with_mocked_now(monkeypatch, "2026-05-28 10:00")
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-27 14:55", "2026-05-27 15:00", "2026-05-27 15:25"]
    )
    orch.feed.get_india_vix_with_timestamp = MagicMock(
        return_value=(13.1, None)
    )
    result = orch._check_market_status()
    assert result.status.value == "holiday"
    assert "VIX timestamp unavailable" in result.reason


def test_mark_holiday_scans_handles_no_holiday_dates(tmp_path):
    """If gap_log has no today_n=0 evidence, nothing is marked."""
    import json
    from scripts.mark_holiday_scans import main as mark_main

    logs = tmp_path / "logs"
    logs.mkdir()
    gap = logs / "gap_log.jsonl"
    # Normal-day gap log entry — no today_n=0
    gap.write_text(json.dumps({
        "timestamp_ist": "2026-05-27T09:16:00+05:30",
        "per_symbol": {"NIFTY": {"gap_pct": 0.3, "triggers": False}},
    }) + "\n")
    sig = logs / "signals.jsonl"
    sig.write_text(json.dumps({"timestamp_ist": "2026-05-27T10:00:00+05:30"}) + "\n")

    mark_main(tmp_path)

    row = json.loads(sig.read_text().strip())
    assert "is_holiday_scan" not in row
