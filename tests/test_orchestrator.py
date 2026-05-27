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


def test_scan_loop_trigger_window_5_to_30_seconds() -> None:
    """The (5,30) trigger window covers all samples 5-30s into a candle.

    Outside that window the loop must NOT fire — this is the gate that
    keeps long scans from re-triggering inside the same candle.
    """
    def seconds_into_candle(now: datetime) -> int:
        return (now.minute % 5) * 60 + now.second

    inside = datetime(2026, 5, 26, 9, 45, 10, tzinfo=IST)
    just_after = datetime(2026, 5, 26, 9, 45, 31, tzinfo=IST)
    boundary = datetime(2026, 5, 26, 9, 45, 0, tzinfo=IST)
    well_past = datetime(2026, 5, 26, 9, 48, 0, tzinfo=IST)

    def in_window(now: datetime) -> bool:
        s = seconds_into_candle(now)
        return 5 <= s <= 30

    assert in_window(inside) is True
    assert in_window(just_after) is False
    assert in_window(boundary) is False  # exactly at candle close — too early
    assert in_window(well_past) is False


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
    orch.feed.get_5min_candles = MagicMock(return_value=pd.DataFrame())

    def _raise_insufficient(_df):
        raise ValueError(
            "Insufficient lookback for indicators ['rsi_ma']; need 33 candles."
        )

    monkeypatch.setattr(main_mod, "get_latest_snapshot", _raise_insufficient)
    orch._scan_strike(
        "NIFTY", strike_choice, "CE", "2026-05-28", 65,
        spot_close=24050.0, spot_vwap=24000.0, now=_dt(11, 30),
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
