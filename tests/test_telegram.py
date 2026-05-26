"""Tests for src/alerts/telegram_bot.py.

The ``telegram.Bot`` class is mocked in every test — no live HTTP calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def telegram_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token-1234")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9876543210")


def _make_alerter(monkeypatch, *, async_send_ok: bool = True) -> tuple:
    """Build a TelegramAlerter with a stubbed Bot. Returns (alerter, mock_bot)."""
    from src.alerts.telegram_bot import TelegramAlerter

    mock_bot = MagicMock()

    async def _send_message(**kwargs):
        if not async_send_ok:
            raise RuntimeError("simulated telegram outage")
        return MagicMock()

    mock_bot.send_message = MagicMock(side_effect=_send_message)
    with patch("src.alerts.telegram_bot.Bot", return_value=mock_bot):
        alerter = TelegramAlerter()
    return alerter, mock_bot


def test_telegram_initialized_with_secrets(monkeypatch, telegram_env) -> None:
    alerter, _ = _make_alerter(monkeypatch)
    assert alerter.token == "fake-token-1234"
    assert alerter.chat_id == "9876543210"


def test_telegram_missing_secrets_raises(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    from src.alerts.telegram_bot import TelegramAlerter

    with pytest.raises(RuntimeError, match="missing from secrets.env"):
        TelegramAlerter()


def test_telegram_missing_chat_id_raises(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    from src.alerts.telegram_bot import TelegramAlerter

    with pytest.raises(RuntimeError):
        TelegramAlerter()


def test_telegram_send_returns_true_on_success(
    monkeypatch, telegram_env
) -> None:
    alerter, mock_bot = _make_alerter(monkeypatch, async_send_ok=True)
    assert alerter.send("hello") is True
    mock_bot.send_message.assert_called_once()


def test_telegram_send_returns_false_on_failure_no_raise(
    monkeypatch, telegram_env
) -> None:
    alerter, _ = _make_alerter(monkeypatch, async_send_ok=False)
    # Must not raise even though the underlying send fails.
    result = alerter.send("hello")
    assert result is False


def test_format_startup_includes_broker_name(monkeypatch, telegram_env) -> None:
    alerter, _ = _make_alerter(monkeypatch)
    msg = alerter._format_startup(
        {
            "broker": "kite",
            "alert_mode": True,
            "order_place_mode": False,
            "paper_trade_mode": True,
            "instruments": "NIFTY, BANKNIFTY",
            "vix": 14.2,
            "vix_regime": "Normal",
            "nifty_lot": 65,
            "banknifty_lot": 30,
            "is_gap_day": False,
        }
    )
    assert "kite" in msg
    assert "BOT STARTED" in msg
    assert "NIFTY=65" in msg


def test_format_startup_no_gap_marker_when_not_gap(
    monkeypatch, telegram_env
) -> None:
    alerter, _ = _make_alerter(monkeypatch)
    msg = alerter._format_startup(
        {
            "broker": "kite", "alert_mode": True, "order_place_mode": False,
            "paper_trade_mode": False, "instruments": "NIFTY",
            "vix": 12.0, "vix_regime": "Normal",
            "nifty_lot": 65, "banknifty_lot": 30,
            "is_gap_day": False,
        }
    )
    assert "GAP DAY" not in msg


def test_format_startup_includes_gap_day_marker_when_set(
    monkeypatch, telegram_env
) -> None:
    alerter, _ = _make_alerter(monkeypatch)
    msg = alerter._format_startup(
        {
            "broker": "kite", "alert_mode": True, "order_place_mode": False,
            "paper_trade_mode": False, "instruments": "NIFTY",
            "vix": 12.0, "vix_regime": "Normal",
            "nifty_lot": 65, "banknifty_lot": 30,
            "is_gap_day": True,
        }
    )
    assert "GAP DAY (10:15 start)" in msg


def test_format_signal_includes_all_required_fields(
    monkeypatch, telegram_env
) -> None:
    alerter, _ = _make_alerter(monkeypatch)
    msg = alerter._format_signal(
        {
            "symbol": "NIFTY", "strike": 24050, "option_type": "CE",
            "relation": "ATM", "expiry": "2026-06-02",
            "date": "2026-05-28", "time": "10:35",
            "day_type": "Normal",
            "vix": 14.2, "vix_regime": "Normal", "vix_multiplier": 1.0,
            "spot": 24030.0, "spot_position": "Above VWAP ✓",
            "lot_size": 65,
            "entry": 152.50, "sl": 140.00, "sl_method": 1,
            "tp1": 171.25, "tp1_r": 1.5,
            "tp2": 183.75, "tp2_r": 2.5,
            "risk_per_unit": 12.50, "lots": 3, "total_risk": 2437.50,
        }
    )
    assert "SHORT COVER CASCADE SIGNAL" in msg
    assert "NIFTY 24050 CE" in msg
    assert "ENTRY: ₹152.50" in msg
    assert "SL: ₹140.00" in msg
    assert "TP1: ₹171.25" in msg
    assert "TP2: ₹183.75" in msg
    assert "Lots: 3" in msg
    assert "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓" in msg
    assert "ALERT ONLY" in msg


def test_send_circuit_breaker_includes_reason(monkeypatch, telegram_env) -> None:
    alerter, mock_bot = _make_alerter(monkeypatch)
    alerter.send_circuit_breaker("Daily SL cap reached")
    sent = mock_bot.send_message.call_args.kwargs["text"]
    assert "CIRCUIT BREAKER" in sent
    assert "Daily SL cap reached" in sent


def test_send_eod_summary_includes_counts(monkeypatch, telegram_env) -> None:
    alerter, mock_bot = _make_alerter(monkeypatch)
    alerter.send_eod_summary(
        {
            "date": "2026-05-28",
            "total_scans": 120,
            "alerts_fired": 2,
            "circuit_breaker": "NO",
            "nifty_alerts": 1,
            "banknifty_alerts": 1,
            "vix_close": 14.2,
        }
    )
    sent = mock_bot.send_message.call_args.kwargs["text"]
    assert "END-OF-DAY SUMMARY" in sent
    assert "120" in sent
    assert "NIFTY: 1 alerts" in sent


def test_send_exception_truncates_long_trace(monkeypatch, telegram_env) -> None:
    alerter, mock_bot = _make_alerter(monkeypatch)
    long_trace = "x" * 5000
    alerter.send_exception(long_trace)
    sent = mock_bot.send_message.call_args.kwargs["text"]
    # Body must be no longer than 3000 chars of trace + the header.
    assert "BOT EXCEPTION" in sent
    assert len(sent) < 3500
