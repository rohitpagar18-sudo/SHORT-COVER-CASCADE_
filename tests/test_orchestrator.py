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
    gap_threshold_percent: float = 1.0,
) -> _NS:
    return _NS(
        normal_start_time=normal_start,
        gap_day_start_time=gap_day_start,
        last_entry_time=last_entry,
        soft_squareoff_time=soft_squareoff,
        hard_squareoff_time=hard_squareoff,
        gap_day_enabled=gap_day_enabled,
        gap_day_filter_enabled=gap_day_enabled,
        gap_threshold_percent=gap_threshold_percent,
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
def orch() -> Orchestrator:
    """Orchestrator instance with __init__ bypassed (no real config load)."""
    o = object.__new__(Orchestrator)
    o.config = _make_config()
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


def test_gap_day_detection_disabled_returns_false(orch) -> None:
    orch.config = _make_config(time_rules=_make_time_rules(gap_day_enabled=False))
    assert orch._detect_gap_day() is False


def test_gap_day_detection_under_1pct_returns_false(orch) -> None:
    today = datetime.now(IST).date()
    prev = today.replace(day=max(1, today.day - 1))
    df = _make_candle_df(
        [
            (datetime(prev.year, prev.month, prev.day, 15, 25, tzinfo=IST), 24000, 24010),
            (datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST), 24050, 24055),
        ]
    )
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    assert orch._detect_gap_day() is False


def test_gap_day_detection_over_1pct_returns_true(orch) -> None:
    today = datetime.now(IST).date()
    prev = today.replace(day=max(1, today.day - 1))
    df = _make_candle_df(
        [
            (datetime(prev.year, prev.month, prev.day, 15, 25, tzinfo=IST), 24000, 24000),
            # 2% gap up
            (datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST), 24480, 24500),
        ]
    )
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    assert orch._detect_gap_day() is True


def test_gap_day_detection_today_only_data_returns_false(orch) -> None:
    """Active feed returning today-only candles (Kite default) → no gap."""
    today = datetime.now(IST).date()
    df = _make_candle_df(
        [
            (datetime(today.year, today.month, today.day, 9, 15, tzinfo=IST), 24000, 24010),
            (datetime(today.year, today.month, today.day, 9, 20, tzinfo=IST), 24010, 24020),
        ]
    )
    orch.feed.get_5min_candles = MagicMock(return_value=df)
    assert orch._detect_gap_day() is False


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
