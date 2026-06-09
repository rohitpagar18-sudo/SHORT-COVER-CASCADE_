"""Tests for src/alerts/telegram_bot.py.

``requests.post`` is mocked in every test — no live HTTP calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests


@pytest.fixture
def telegram_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token-1234")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9876543210")


def _make_alerter(status_code: int = 200, body: str = "ok"):
    """Build a TelegramAlerter with requests.post stubbed.

    Returns (alerter, mock_post).
    """
    from src.alerts.telegram_bot import TelegramAlerter

    mock_resp = MagicMock(status_code=status_code, text=body)
    patcher = patch("src.alerts.telegram_bot.requests.post", return_value=mock_resp)
    mock_post = patcher.start()
    alerter = TelegramAlerter()
    alerter._patcher = patcher  # keep ref so test can stop if needed
    alerter._mock_post = mock_post
    return alerter, mock_post


def test_telegram_initialized_with_secrets(telegram_env) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
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


def test_telegram_send_returns_true_on_2xx(telegram_env) -> None:
    alerter, mock_post = _make_alerter(status_code=200, body="ok")
    try:
        assert alerter.send("hi") is True
        mock_post.assert_called_once()
        # Ensure POST is to the sendMessage URL with chat_id + text.
        call = mock_post.call_args
        assert "sendMessage" in call.args[0]
        assert call.kwargs["data"]["chat_id"] == "9876543210"
        assert call.kwargs["data"]["text"] == "hi"
    finally:
        alerter._patcher.stop()


def test_telegram_send_returns_false_on_non_2xx(telegram_env) -> None:
    alerter, _ = _make_alerter(status_code=400, body="bad request")
    try:
        assert alerter.send("hi") is False
    finally:
        alerter._patcher.stop()


def test_telegram_send_returns_false_on_timeout(telegram_env) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    with patch(
        "src.alerts.telegram_bot.requests.post",
        side_effect=requests.Timeout(),
    ):
        alerter = TelegramAlerter()
        assert alerter.send("hi") is False


def test_telegram_send_returns_false_on_connection_error(telegram_env) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    with patch(
        "src.alerts.telegram_bot.requests.post",
        side_effect=requests.ConnectionError("network down"),
    ):
        alerter = TelegramAlerter()
        assert alerter.send("hi") is False


def _startup_payload(**overrides) -> dict:
    base = {
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
        "gap_info": _gap_info(decision="NORMAL"),
    }
    base.update(overrides)
    return base


def _gap_info(
    *,
    decision: str = "NORMAL",
    enabled: bool = False,
    direction: str = "both",
    threshold: float = 1.0,
    nifty_pct: float | None = 0.25,
    bn_pct: float | None = 0.10,
) -> dict:
    return {
        "enabled": enabled,
        "threshold_pct": threshold,
        "direction": direction,
        "decision": decision,
        "any_triggered": decision != "NORMAL",
        "per_symbol": {
            "NIFTY": {
                "open": 24050.0,
                "prev_close": 24000.0,
                "gap_pct": nifty_pct,
                "triggers": decision != "NORMAL",
                "error": None,
            },
            "BANKNIFTY": {
                "open": 51000.0,
                "prev_close": 50950.0,
                "gap_pct": bn_pct,
                "triggers": False,
                "error": None,
            },
        },
        "timestamp_ist": "2026-05-27T09:16:00+05:30",
    }


def test_format_startup_includes_broker_name(telegram_env) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    msg = alerter._format_startup(_startup_payload())
    assert "kite" in msg
    assert "BOT STARTED" in msg
    assert "NIFTY=65" in msg


def test_format_startup_always_includes_gap_line(telegram_env) -> None:
    """Gap line is in startup message regardless of toggle state."""
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    # Toggle OFF, no gap.
    msg_off = alerter._format_startup(
        _startup_payload(gap_info=_gap_info(decision="NORMAL", enabled=False))
    )
    assert "Gap status" in msg_off
    # Toggle ON, gap up day.
    msg_on = alerter._format_startup(
        _startup_payload(
            gap_info=_gap_info(decision="GAP_UP", enabled=True, nifty_pct=1.5)
        )
    )
    assert "Gap status" in msg_on


def test_format_gap_line_shows_normal_when_under_threshold(telegram_env) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    line = alerter._format_gap_line(
        _gap_info(decision="NORMAL", enabled=True, nifty_pct=0.25)
    )
    assert "Normal day" in line
    assert "9:45 start" in line
    assert "toggle=ON" in line


def test_format_gap_line_shows_gap_up_when_triggered_and_enabled(
    telegram_env,
) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    line = alerter._format_gap_line(
        _gap_info(decision="GAP_UP", enabled=True, nifty_pct=1.5)
    )
    assert "GAP UP" in line
    assert "10:15 start" in line


def test_format_gap_line_shows_gap_down_when_triggered_and_enabled(
    telegram_env,
) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    line = alerter._format_gap_line(
        _gap_info(decision="GAP_DOWN", enabled=True, nifty_pct=-1.5)
    )
    assert "GAP DOWN" in line
    assert "10:15 start" in line


def test_format_gap_line_shows_disabled_warning_when_breached_but_off(
    telegram_env,
) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    line = alerter._format_gap_line(
        _gap_info(
            decision="GAP_UP_DISABLED",
            enabled=False,
            nifty_pct=1.5,
        )
    )
    assert "rule OFF" in line
    assert "9:45 start" in line
    assert "toggle=OFF" in line


def test_format_signal_includes_all_required_fields(telegram_env) -> None:
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
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
    assert "MAIN SIGNAL" in msg
    assert "NIFTY 24050 CE" in msg
    assert "ENTRY: ₹152.50" in msg
    assert "SL: ₹140.00" in msg
    assert "TP1: ₹171.25" in msg
    assert "TP2: ₹183.75" in msg
    assert "Lots: 3" in msg
    assert "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓" in msg
    assert "ALERT ONLY" in msg


def test_send_signal_passes_formatted_message_to_send(telegram_env) -> None:
    """_format_signal routes through send() with the full formatted message."""
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    with patch.object(alerter, "send", return_value=True) as spy:
        signal_data = {
            "symbol": "NIFTY", "strike": 24050, "option_type": "CE",
            "relation": "ATM", "expiry": "2026-06-02",
            "date": "2026-05-29", "time": "10:35", "day_type": "Normal",
            "vix": 14.2, "vix_regime": "Normal", "vix_multiplier": 1.0,
            "spot": 24030.0, "spot_position": "Above VWAP ✓",
            "lot_size": 65, "entry": 152.50, "sl": 140.00,
            "sl_method": 1, "tp1": 171.25, "tp2": 183.75,
            "tp1_r": 1.5, "tp2_r": 2.5,
            "risk_per_unit": 12.50, "lots": 3, "total_risk": 2437.50,
            "telegram_short_remark": "",
        }
        alerter.send_signal(signal_data)
        spy.assert_called_once()
        msg = spy.call_args[0][0]
        assert "NIFTY 24050 CE" in msg
        assert "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓" in msg


def test_send_circuit_breaker_includes_reason(telegram_env) -> None:
    alerter, mock_post = _make_alerter()
    try:
        alerter.send_circuit_breaker("Daily SL cap reached")
        sent = mock_post.call_args.kwargs["data"]["text"]
        assert "CIRCUIT BREAKER" in sent
        assert "Daily SL cap reached" in sent
    finally:
        alerter._patcher.stop()


def test_send_eod_summary_includes_counts(telegram_env) -> None:
    alerter, mock_post = _make_alerter()
    try:
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
        sent = mock_post.call_args.kwargs["data"]["text"]
        assert "END-OF-DAY SUMMARY" in sent
        assert "120" in sent
        assert "NIFTY: 1 alerts" in sent
    finally:
        alerter._patcher.stop()


def test_send_exception_truncates_long_trace(telegram_env) -> None:
    alerter, mock_post = _make_alerter()
    try:
        long_trace = "x" * 5000
        alerter.send_exception(long_trace)
        sent = mock_post.call_args.kwargs["data"]["text"]
        # Body must be no longer than 3000 chars of trace + the header.
        assert "BOT EXCEPTION" in sent
        assert len(sent) < 3500
    finally:
        alerter._patcher.stop()


# ---------------------------------------------------------------------------
# Phase 6.1 follow-up — combined Spot DI + Opt DI in C5 alert line
# ---------------------------------------------------------------------------


def _signal_dict_with_di(**overrides) -> dict:
    """Build a signal dict containing the full set of fields _format_signal
    consumes. Tests override only the C5/DI bits.
    """
    base = {
        "symbol": "NIFTY", "strike": 24050, "option_type": "CE",
        "relation": "ATM", "expiry": "2026-06-02",
        "date": "2026-05-28", "time": "10:35", "day_type": "Normal",
        "vix": 14.2, "vix_regime": "Normal", "vix_multiplier": 1.0,
        "spot": 24030.0, "spot_position": "Above VWAP ✓",
        "lot_size": 65,
        "entry": 152.50, "sl": 140.00, "sl_method": 1,
        "tp1": 171.25, "tp1_r": 1.5,
        "tp2": 183.75, "tp2_r": 2.5,
        "risk_per_unit": 12.50, "lots": 3, "total_risk": 2437.50,
        "telegram_short_remark": "",
        # C5 / DI fields default to the "passing CE" case from the report.
        "adx": 24.1, "adx_prev": 22.3,
        "di_plus": 22.3, "di_minus": 18.7,
        "c5_passed": True, "c5_reason": "C5 PASS",
        "option_di_plus": 31.2, "option_di_minus": 14.1,
        "option_di_aligned": True,
    }
    base.update(overrides)
    return base


def test_c5_alert_line_combined_spot_and_option_di_ce_pass(telegram_env) -> None:
    """Exact-report example: CE, ADX 24.1 ↑, ↳ sub-lines for Spot and Opt DI."""
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    msg = alerter._format_signal(_signal_dict_with_di())
    assert "↳" in msg
    assert "C5 ✓  ADX 24.1 ↑" in msg
    assert "↳ Spot DI  +22.3 / −18.7  ✓ aligned" in msg
    assert "↳ Opt  DI  +31.2 / −14.1  ✓ trending up" in msg


def test_c5_alert_line_opt_di_misaligned_shows_cross(telegram_env) -> None:
    """Same CE/Spot setup, but Option +DI < −DI → ✗ not trending sub-line."""
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    msg = alerter._format_signal(_signal_dict_with_di(
        option_di_plus=14.1, option_di_minus=31.2,
        option_di_aligned=False,
    ))
    assert "↳ Opt  DI  +14.1 / −31.2  ✗ not trending" in msg
    # Spot side unchanged — still aligned for CE.
    assert "↳ Spot DI  +22.3 / −18.7  ✓ aligned" in msg


def test_c5_alert_line_opt_di_na_when_insufficient_candles(telegram_env) -> None:
    """option_di_aligned=None → 'Opt N/A'; no crash, no missing fields."""
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    msg = alerter._format_signal(_signal_dict_with_di(
        option_di_plus=None, option_di_minus=None,
        option_di_aligned=None,
    ))
    assert "↳ Opt  DI  N/A" in msg
    # C5 + Spot still render with the available ADX data.
    assert "C5 ✓  ADX 24.1 ↑" in msg
    assert "↳ Spot DI  +22.3 / −18.7  ✓ aligned" in msg


def test_c5_alert_line_pe_uses_minus_di_label(telegram_env) -> None:
    """PE alignment is −DI > +DI. Label must flip accordingly."""
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    msg = alerter._format_signal(_signal_dict_with_di(
        option_type="PE",
        di_plus=18.7, di_minus=22.3,  # -DI > +DI -> aligned for PE
    ))
    assert "↳ Spot DI  +18.7 / −22.3  ✓ aligned" in msg


def test_c5_alert_line_failing_c5_shows_cross_mark(telegram_env) -> None:
    """C5 fails (ADX below min, falling): line begins 'C5 ❌'."""
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    msg = alerter._format_signal(_signal_dict_with_di(
        adx=16.1, adx_prev=17.0,
        di_plus=18.0, di_minus=22.0,
        c5_passed=False,
    ))
    assert "C5 ❌  ADX 16.1 ↓" in msg
    # CE but +DI < −DI → not aligned sub-line.
    assert "↳ Spot DI  +18.0 / −22.0  ✗ not aligned" in msg


def test_c5_alert_line_absent_when_adx_inputs_missing(telegram_env) -> None:
    """When ADX inputs are None (c5_adx disabled in config), no C5 suffix
    is appended — the alert line is exactly the pre-Phase-6.1 form.
    """
    from src.alerts.telegram_bot import TelegramAlerter
    alerter = TelegramAlerter()
    msg = alerter._format_signal(_signal_dict_with_di(
        adx=None, adx_prev=None,
        di_plus=None, di_minus=None,
        option_di_plus=None, option_di_minus=None,
        option_di_aligned=None,
        c5_passed=None,
    ))
    assert "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓\n" in msg
    # No C5 block at all.
    assert "C5" not in msg


# ---------------------------------------------------------------------------
# Episode tracking — MAIN / Follow-up labeling
# ---------------------------------------------------------------------------


def test_send_signal_labels_followup_within_window(telegram_env) -> None:
    """Second send_signal for same (date, symbol, option_type) within the
    episode window must produce a Follow-up message, not another MAIN."""
    from unittest.mock import patch
    from src.alerts.telegram_bot import TelegramAlerter

    alerter = TelegramAlerter(episode_window_minutes=20)
    signal = {
        "symbol": "NIFTY", "strike": 24050, "option_type": "CE",
        "relation": "ATM", "expiry": "2026-06-02",
        "date": "2026-05-28", "time": "09:30", "day_type": "Normal",
        "vix": 14.2, "vix_regime": "Normal", "vix_multiplier": 1.0,
        "spot": 24030.0, "spot_position": "Above VWAP ✓",
        "lot_size": 65, "entry": 152.50, "sl": 140.00, "sl_method": 1,
        "tp1": 171.25, "tp1_r": 1.5, "tp2": 183.75, "tp2_r": 2.5,
        "risk_per_unit": 12.50, "lots": 3, "total_risk": 2437.50,
    }
    captured: list[str] = []
    with patch.object(alerter, "send", side_effect=lambda m: captured.append(m) or True):
        alerter.send_signal(signal)
        alerter.send_signal(signal)

    assert len(captured) == 2
    assert "MAIN SIGNAL" in captured[0]
    assert "Follow-up" in captured[1]
    assert "Follow-up #2" in captured[1]
