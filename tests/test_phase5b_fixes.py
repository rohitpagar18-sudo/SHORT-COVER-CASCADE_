"""Tests for the three Phase 5B fixes:

  FIX 1: get_5min_candles must drop the in-progress 5-min candle.
  FIX 1b: _scan_strike logs a STALE_CANDLE data_issue when the last
          fully-closed candle is too old.
  FIX 2: c0_spot_trend_filter_enabled config toggle:
          - default False
          - when False, check_all_conditions appends a SKIPPED C0 with
            passed=True and _scan_symbol scans BOTH CE and PE
          - when True, original C0 fast-fail behavior is preserved
  FIX 3: strike.alert_strikes toggles correctly drop OFF relations and
          the AlertStrikesConfig validator rejects all-OFF.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.conditions.all_conditions import check_all_conditions
from src.config_loader import AppConfig, ConditionsConfig, AlertStrikesConfig
from src.data.kite_feed import KiteFeed
from src.data.upstox_feed import UpstoxFeed
from src.data.strike_selector import get_alert_strikes
from src.indicators.calculator import IndicatorSnapshot

IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(**kw) -> IndicatorSnapshot:
    """IndicatorSnapshot with sensible defaults; override via kwargs."""
    defaults = dict(
        vwap=100.0, rsi=60.0, rsi_ma=55.0,
        oi=1_000_000.0, oi_ma=2_000_000.0,
        volume=10_000.0, volume_ma=5_000.0,
        close=105.0, open=100.0, high=110.0, low=99.0,
        timestamp=pd.Timestamp("2026-05-26 14:55", tz="Asia/Kolkata"),
        is_green=True,
    )
    defaults.update(kw)
    return IndicatorSnapshot(**defaults)


def _current_5min_boundary(now: datetime) -> datetime:
    b = now.replace(second=0, microsecond=0)
    return b - timedelta(minutes=now.minute % 5)


# ---------------------------------------------------------------------------
# FIX 1 — get_5min_candles drops the in-progress candle (both feeds)
# ---------------------------------------------------------------------------


def test_kite_get_5min_candles_drops_in_progress_candle(
    kite_config: AppConfig,
) -> None:
    """Kite returns rows including the just-starting candle. Method must
    drop it so .iloc[-1] is the LAST FULLY CLOSED candle.
    """
    now = datetime.now(IST)
    boundary = _current_5min_boundary(now)
    in_progress_ts = boundary  # ts of the still-forming candle
    closed_ts = boundary - timedelta(minutes=5)

    feed = KiteFeed(kite_config)
    feed._kite = MagicMock()
    # Token map: pretend a digit-string token (skips lookup path).
    feed._kite.historical_data.return_value = [
        {
            "date": closed_ts - timedelta(minutes=5),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 5_000_000.0, "oi": 1_000_000.0,
        },
        {
            "date": closed_ts,
            "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5,
            "volume": 6_000_000.0, "oi": 1_010_000.0,
        },
        {
            "date": in_progress_ts,  # in-progress (volume way too small)
            "open": 101.5, "high": 101.8, "low": 101.3, "close": 101.6,
            "volume": 50_000.0, "oi": 1_010_500.0,
        },
    ]
    df = feed.get_5min_candles("12345", lookback_candles=10)
    assert not df.empty
    last_ts = pd.Timestamp(df["timestamp"].iloc[-1])
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize(IST)
    assert last_ts < boundary
    # Bonus: the partial-volume row must NOT be in the frame.
    volumes = df["volume"].tolist()
    assert 50_000.0 not in volumes


def test_upstox_get_5min_candles_drops_in_progress_candle(
    upstox_config: AppConfig,
) -> None:
    """Upstox version — same invariant."""
    now = datetime.now(IST)
    boundary = _current_5min_boundary(now)
    in_progress_ts = boundary
    closed_ts = boundary - timedelta(minutes=5)

    feed = UpstoxFeed(upstox_config)
    # Patch the inner fetchers so we control the rows fed into the dedup.
    intraday_df = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp(closed_ts - timedelta(minutes=5)),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                "volume": 5_000_000.0, "oi": 1_000_000.0,
            },
            {
                "timestamp": pd.Timestamp(closed_ts),
                "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5,
                "volume": 6_000_000.0, "oi": 1_010_000.0,
            },
            {
                "timestamp": pd.Timestamp(in_progress_ts),
                "open": 101.5, "high": 101.8, "low": 101.3, "close": 101.6,
                "volume": 50_000.0, "oi": 1_010_500.0,
            },
        ]
    )
    feed._fetch_intraday_candles = MagicMock(return_value=intraday_df)
    feed._fetch_historical_candles = MagicMock(
        return_value=pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
        )
    )
    df = feed.get_5min_candles("NSE_INDEX|Nifty 50", lookback_candles=10)
    assert not df.empty
    last_ts = pd.Timestamp(df["timestamp"].iloc[-1])
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize(IST)
    assert last_ts < boundary
    volumes = df["volume"].tolist()
    assert 50_000.0 not in volumes


# ---------------------------------------------------------------------------
# FIX 1b — _scan_strike logs STALE_CANDLE on too-old data
# ---------------------------------------------------------------------------


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _orchestrator_with_stub(tmp_path, config: AppConfig):
    """Build an Orchestrator instance with __init__ bypassed (no real
    config-load, no broker connect, no Telegram). Returns the stub.
    """
    from src.main import Orchestrator

    o = object.__new__(Orchestrator)
    o.config = config
    o.feed = MagicMock()
    o.telegram = MagicMock()
    o.signal_logger = MagicMock()
    o.state = MagicMock()
    o.state.can_re_enter = MagicMock(return_value=(True, ""))
    o.state._state = MagicMock(circuit_breaker_triggered=False)
    o.state.get_daily_sl_count = MagicMock(return_value=0)
    o.state.get_daily_loss = MagicMock(return_value=0.0)
    o.broker_name = "kite"
    o.session_vix = 14.0
    o.session_vix_info = _NS(
        regime=_NS(value="Normal"), method1_multiplier=1.0,
        method2_sl_normal_pct=5.0, method2_sl_expiry_pct=15.0,
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
    o.gap_log_path = tmp_path / "gap_log.jsonl"
    o.gap_info = {}
    return o


def test_scan_strike_logs_stale_candle_when_last_candle_too_old(
    tmp_path, config: AppConfig,
) -> None:
    """When the only candle returned is hours old, _scan_strike must log
    a data_issue with issue_type=STALE_CANDLE and NOT log a rejection.
    """
    orch = _orchestrator_with_stub(tmp_path, config)

    # 30-minute-old timestamp — definitely > 6 min stale.
    now = datetime.now(IST)
    stale_ts = now - timedelta(minutes=30)
    stale_df = pd.DataFrame(
        [{
            "timestamp": pd.Timestamp(stale_ts),
            "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
            "volume": 1000.0, "oi": 1000.0,
        }]
    )
    orch.feed.get_5min_candles = MagicMock(return_value=stale_df)
    # Zero retries so the test runs fast.
    orch.config = config.model_copy(
        update={
            "bot": config.bot.model_copy(
                update={"api_retry_count": 0, "api_retry_delay_seconds": 0}
            )
        }
    )

    strike_choice = _NS(
        strike=24050, relation="ATM",
        instrument_key="DUMMY", trading_symbol="NIFTY24050CE",
    )
    orch._scan_strike(
        "NIFTY", strike_choice, "CE", "2026-05-28", 65,
        spot_close=24050.0, spot_vwap=24000.0, now=now,
    )

    # Rejection logger must NOT have been called.
    orch.signal_logger.log_rejection.assert_not_called()
    # log_signal must have been called once with event_type='data_issue'.
    orch.signal_logger.log_signal.assert_called_once()
    record = orch.signal_logger.log_signal.call_args[0][0]
    assert record["event_type"] == "data_issue"
    assert record["issue_type"] == "STALE_CANDLE"


def test_scan_strike_stale_candle_retries_then_succeeds_when_fresh(
    tmp_path, config: AppConfig,
) -> None:
    """If the first fetch is stale but a retry returns a fresh candle,
    the scan proceeds (no data_issue is logged).
    """
    orch = _orchestrator_with_stub(tmp_path, config)

    now = datetime.now(IST)
    boundary = _current_5min_boundary(now)
    fresh_ts = boundary - timedelta(minutes=5)
    stale_ts = now - timedelta(minutes=30)

    stale_df = pd.DataFrame(
        [{
            "timestamp": pd.Timestamp(stale_ts),
            "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
            "volume": 1000.0, "oi": 1000.0,
        }]
    )
    # Need ENOUGH candles for the indicator calc; the only thing we care
    # about here is that retry consumes the stale frame first.
    fresh_df = pd.DataFrame(
        [{
            "timestamp": pd.Timestamp(fresh_ts),
            "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0,
            "volume": 1000.0, "oi": 1000.0,
        }]
    )
    orch.feed.get_5min_candles = MagicMock(side_effect=[stale_df, fresh_df])
    orch.config = config.model_copy(
        update={
            "bot": config.bot.model_copy(
                update={"api_retry_count": 1, "api_retry_delay_seconds": 0}
            )
        }
    )

    # We don't care if indicator computation later fails (insufficient lookback
    # gets logged as data_issue INSUFFICIENT_LOOKBACK). The STALE_CANDLE
    # data_issue must NOT be logged. So we assert by inspecting all calls.
    strike_choice = _NS(
        strike=24050, relation="ATM",
        instrument_key="DUMMY", trading_symbol="NIFTY24050CE",
    )
    orch._scan_strike(
        "NIFTY", strike_choice, "CE", "2026-05-28", 65,
        spot_close=24050.0, spot_vwap=24000.0, now=now,
    )

    # The feed should have been called twice (stale, then fresh).
    assert orch.feed.get_5min_candles.call_count == 2
    # If any data_issue WAS logged, it must NOT be STALE_CANDLE — the retry
    # found a fresh candle.
    stale_calls = [
        c for c in orch.signal_logger.log_signal.call_args_list
        if c[0][0].get("event_type") == "data_issue"
        and c[0][0].get("issue_type") == "STALE_CANDLE"
    ]
    assert stale_calls == []


# ---------------------------------------------------------------------------
# FIX 2 — C0 toggle behavior
# ---------------------------------------------------------------------------


def test_config_defaults_c0_filter_to_false() -> None:
    """Default ConditionsConfig leaves c0_spot_trend_filter_enabled False
    so older configs (missing the field) load cleanly with the new safe
    default behavior — scan both CE and PE.
    """
    cc = ConditionsConfig.model_validate({"c3_rsi_min": 50, "c3_rsi_max": 80})
    assert cc.c0_spot_trend_filter_enabled is False


def test_c0_disabled_appends_skipped_result_passed_true(
    config: AppConfig,
) -> None:
    """check_all_conditions still produces a C0 result row when the toggle
    is OFF — passed=True with a clear 'SKIPPED' reason.
    """
    cfg = config.model_copy(
        update={
            "conditions": config.conditions.model_copy(
                update={"c0_spot_trend_filter_enabled": False}
            )
        }
    )
    s = _make_snapshot()
    # Spot direction would FAIL real C0 (CE asked, spot below VWAP), but
    # since C0 is skipped, the row passes.
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24400, spot_vwap=24500,
        option_type="CE", config=cfg,
    )
    c0 = result.by_name("C0")
    assert c0 is not None
    assert c0.passed is True
    assert "SKIPPED" in c0.reason


def test_c0_enabled_preserves_current_fast_fail_behavior(
    config: AppConfig,
) -> None:
    """When the toggle is ON, the original C0 spot-trend logic runs
    unchanged: CE requires spot > VWAP, else C0 fails."""
    cfg = config.model_copy(
        update={
            "conditions": config.conditions.model_copy(
                update={"c0_spot_trend_filter_enabled": True}
            )
        }
    )
    s = _make_snapshot()
    result = check_all_conditions(
        option_snapshot=s,
        spot_close=24400, spot_vwap=24500,
        option_type="CE", config=cfg,
    )
    c0 = result.by_name("C0")
    assert c0 is not None
    assert c0.passed is False
    assert "not above VWAP" in c0.reason or "CE needs spot above" in c0.reason


def test_c0_disabled_scans_both_ce_and_pe(tmp_path, config: AppConfig) -> None:
    """With C0 OFF and spot above VWAP, _scan_symbol still scans BOTH
    CE and PE (no spot/VWAP gate). The pre-existing behavior would have
    skipped PE here because spot > VWAP.
    """
    orch = _orchestrator_with_stub(tmp_path, config)
    orch.config = config.model_copy(
        update={
            "conditions": config.conditions.model_copy(
                update={"c0_spot_trend_filter_enabled": False}
            )
        }
    )
    # Spot close (24100) > spot VWAP (24000) — pre-fix would skip PE.
    spot_df = pd.DataFrame(
        [{
            "timestamp": pd.Timestamp(
                datetime.now(IST).replace(second=0, microsecond=0)
            ),
            "open": 24000.0, "high": 24150.0, "low": 23950.0,
            "close": 24100.0, "volume": 1.0, "oi": 0,
        }]
    )
    orch._get_spot_candles = MagicMock(return_value=spot_df)
    # Stub VWAP to a value below spot_close so the OLD behavior would
    # have skipped PE. We don't need real VWAP math here.
    import src.main as main_mod
    real_vwap = main_mod.compute_session_vwap
    main_mod.compute_session_vwap = MagicMock(
        return_value=pd.Series([24000.0])
    )

    # Capture which option_types _scan_strike got called with.
    seen_types: list[str] = []
    def _record(symbol, strike_choice, option_type, *args, **kw):
        seen_types.append(option_type)
    orch._scan_strike = _record

    # Strike selector must return at least one strike, otherwise the
    # symbol's inner loop never reaches _scan_strike.
    import src.main as _mm
    real_strike_selector = _mm.get_alert_strikes
    _mm.get_alert_strikes = MagicMock(
        return_value=[_NS(
            strike=24050, relation="ATM",
            instrument_key="DUMMY", trading_symbol="NIFTY24050X",
        )]
    )
    try:
        orch._scan_symbol("NIFTY", "2026-05-28", 65, datetime.now(IST))
    finally:
        _mm.get_alert_strikes = real_strike_selector
        main_mod.compute_session_vwap = real_vwap

    assert "CE" in seen_types
    assert "PE" in seen_types


def test_c0_enabled_fast_fails_pe_when_spot_above_vwap(
    tmp_path, config: AppConfig,
) -> None:
    """With C0 ON: spot > VWAP must skip PE (logs a C0 rejection)."""
    orch = _orchestrator_with_stub(tmp_path, config)
    orch.config = config.model_copy(
        update={
            "conditions": config.conditions.model_copy(
                update={"c0_spot_trend_filter_enabled": True}
            )
        }
    )
    spot_df = pd.DataFrame(
        [{
            "timestamp": pd.Timestamp(
                datetime.now(IST).replace(second=0, microsecond=0)
            ),
            "open": 24000.0, "high": 24150.0, "low": 23950.0,
            "close": 24100.0, "volume": 1.0, "oi": 0,
        }]
    )
    orch._get_spot_candles = MagicMock(return_value=spot_df)
    import src.main as main_mod
    real_vwap = main_mod.compute_session_vwap
    main_mod.compute_session_vwap = MagicMock(
        return_value=pd.Series([24000.0])
    )

    seen_types: list[str] = []
    def _record(symbol, strike_choice, option_type, *args, **kw):
        seen_types.append(option_type)
    orch._scan_strike = _record

    import src.main as _mm
    real_strike_selector = _mm.get_alert_strikes
    _mm.get_alert_strikes = MagicMock(
        return_value=[_NS(
            strike=24050, relation="ATM",
            instrument_key="DUMMY", trading_symbol="NIFTY24050X",
        )]
    )
    try:
        orch._scan_symbol("NIFTY", "2026-05-28", 65, datetime.now(IST))
    finally:
        _mm.get_alert_strikes = real_strike_selector
        main_mod.compute_session_vwap = real_vwap

    # CE should be scanned, PE should not.
    assert "CE" in seen_types
    assert "PE" not in seen_types
    # A C0 rejection should have been logged for the PE side.
    rejections = [
        c[0][0] for c in orch.signal_logger.log_rejection.call_args_list
    ]
    assert any(
        r.get("option_type") == "PE" and r.get("rejection_blocker") == "C0"
        for r in rejections
    )


# ---------------------------------------------------------------------------
# FIX 3 — alert_strikes toggles
# ---------------------------------------------------------------------------


class _FakeOptionChain:
    """Minimal feed stub returning a synthetic option chain for one expiry."""

    def __init__(self, strikes):
        self._strikes = strikes

    def get_option_chain(self, symbol, expiry):
        rows = []
        for s in self._strikes:
            for typ in ("CE", "PE"):
                rows.append({
                    "strike": float(s),
                    "instrument_type": typ,
                    "instrument_token": int(s * 10 + (1 if typ == "CE" else 2)),
                    "tradingsymbol": f"NIFTY26JUN{s}{typ}",
                    "expiry": expiry,
                    "lot_size": 65,
                })
        return pd.DataFrame(rows)


def test_alert_strikes_otm_off_excludes_otm(config: AppConfig) -> None:
    """alert_strikes otm levels OFF must drop OTM rows from the returned list."""
    feed = _FakeOptionChain([24000, 24050, 24100])
    cfg = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={
                    "alert_strikes": config.strike.alert_strikes.model_copy(
                        update={
                            "itm3": False, "itm2": False, "itm1": True,
                            "atm": True,
                            "otm1": False, "otm2": False, "otm3": False,
                        }
                    )
                }
            )
        }
    )
    choices = get_alert_strikes(
        feed, "NIFTY", spot_price=24030.0, option_type="CE",
        expiry="2026-06-02", config=cfg,
    )
    relations = [c.relation for c in choices]
    assert not any(r.startswith("OTM") for r in relations)
    assert relations == ["ITM1", "ATM"]


def test_alert_strikes_itm_atm_on_otm_off_returns_correct_relations(
    config: AppConfig,
) -> None:
    """CE: ITM1=atm-interval, OTM1=atm+interval; PE: ITM1=atm+interval,
    OTM1=atm-interval. Verify both sides return the right strikes
    when only ITM1+ATM are ON.
    """
    feed = _FakeOptionChain([23950, 24000, 24050, 24100])
    cfg = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={
                    "alert_strikes": config.strike.alert_strikes.model_copy(
                        update={
                            "itm3": False, "itm2": False, "itm1": True,
                            "atm": True,
                            "otm1": False, "otm2": False, "otm3": False,
                        }
                    )
                }
            )
        }
    )
    # ATM for spot 24030 = round(24030/50)*50 = 24050.
    # CE: ITM1 = 24050-50 = 24000, ATM = 24050.
    ce_choices = get_alert_strikes(
        feed, "NIFTY", 24030.0, "CE", "2026-06-02", cfg,
    )
    assert [(c.relation, c.strike) for c in ce_choices] == [
        ("ITM1", 24000), ("ATM", 24050),
    ]
    # PE: ITM1 = 24050+50 = 24100, ATM = 24050.
    pe_choices = get_alert_strikes(
        feed, "NIFTY", 24030.0, "PE", "2026-06-02", cfg,
    )
    assert [(c.relation, c.strike) for c in pe_choices] == [
        ("ITM1", 24100), ("ATM", 24050),
    ]


def test_config_validator_rejects_all_strikes_off() -> None:
    """AlertStrikesConfig validator must reject every level OFF — bot
    would never alert otherwise.
    """
    with pytest.raises(Exception):
        AlertStrikesConfig.model_validate({
            "itm3": False, "itm2": False, "itm1": False,
            "atm": False,
            "otm1": False, "otm2": False, "otm3": False,
        })


# ---------------------------------------------------------------------------
# Per-level strike depth toggles (7-wide ITM3..ATM..OTM3)
# ---------------------------------------------------------------------------


def test_default_toggles_itm1_itm2_atm_on_rest_off(config: AppConfig) -> None:
    """Default config.yaml ships with itm2/itm1/atm ON, every other level OFF."""
    a = config.strike.alert_strikes
    assert (a.itm3, a.itm2, a.itm1, a.atm, a.otm1, a.otm2, a.otm3) == (
        False, True, True, True, False, False, False,
    )
    assert a.enabled_levels() == ["ITM2", "ITM1", "ATM"]


def test_enabled_toggles_generate_matching_relations(config: AppConfig) -> None:
    """Enabling itm3+atm+otm2 must yield exactly those three relations,
    in display order ITM3..ATM..OTM3."""
    feed = _FakeOptionChain([23900, 23950, 24000, 24050, 24100, 24150, 24200])
    cfg = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={
                    "alert_strikes": config.strike.alert_strikes.model_copy(
                        update={
                            "itm3": True, "itm2": False, "itm1": False,
                            "atm": True,
                            "otm1": False, "otm2": True, "otm3": False,
                        }
                    )
                }
            )
        }
    )
    choices = get_alert_strikes(
        feed, "NIFTY", 24030.0, "CE", "2026-06-02", cfg,
    )
    assert [(c.relation, c.strike) for c in choices] == [
        ("ITM3", 23900), ("ATM", 24050), ("OTM2", 24150),
    ]


def test_itm_levels_mirror_correctly_for_ce_vs_pe(config: AppConfig) -> None:
    """CE: ITMn = atm - n*interval, OTMn = atm + n*interval.
    PE mirrors. Verified across all 3 ITM depths and all 3 OTM depths."""
    feed = _FakeOptionChain([23900, 23950, 24000, 24050, 24100, 24150, 24200])
    cfg = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={
                    "alert_strikes": config.strike.alert_strikes.model_copy(
                        update={
                            "itm3": True, "itm2": True, "itm1": True,
                            "atm": True,
                            "otm1": True, "otm2": True, "otm3": True,
                        }
                    )
                }
            )
        }
    )
    ce = get_alert_strikes(feed, "NIFTY", 24030.0, "CE", "2026-06-02", cfg)
    assert [(c.relation, c.strike) for c in ce] == [
        ("ITM3", 23900), ("ITM2", 23950), ("ITM1", 24000),
        ("ATM",  24050),
        ("OTM1", 24100), ("OTM2", 24150), ("OTM3", 24200),
    ]
    pe = get_alert_strikes(feed, "NIFTY", 24030.0, "PE", "2026-06-02", cfg)
    assert [(c.relation, c.strike) for c in pe] == [
        ("ITM3", 24200), ("ITM2", 24150), ("ITM1", 24100),
        ("ATM",  24050),
        ("OTM1", 24000), ("OTM2", 23950), ("OTM3", 23900),
    ]


def test_non_contiguous_toggles_allowed(config: AppConfig) -> None:
    """itm1 ON, itm2 OFF, itm3 ON is a legal combo — validator must not
    reject it, and the selector must return only the enabled levels."""
    cfg = AlertStrikesConfig.model_validate({
        "itm3": True, "itm2": False, "itm1": True,
        "atm": False,
        "otm1": False, "otm2": False, "otm3": False,
    })
    assert cfg.enabled_levels() == ["ITM3", "ITM1"]

    feed = _FakeOptionChain([23900, 23950, 24000, 24050])
    forced = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={"alert_strikes": cfg}
            )
        }
    )
    choices = get_alert_strikes(
        feed, "NIFTY", 24030.0, "CE", "2026-06-02", forced,
    )
    assert [(c.relation, c.strike) for c in choices] == [
        ("ITM3", 23900), ("ITM1", 24000),
    ]


def test_all_toggles_off_rejected_by_validator() -> None:
    """Every toggle OFF must raise — bot would never alert."""
    with pytest.raises(Exception):
        AlertStrikesConfig.model_validate({
            "itm3": False, "itm2": False, "itm1": False,
            "atm": False,
            "otm1": False, "otm2": False, "otm3": False,
        })


def test_strike_interval_read_from_config_not_hardcoded(config: AppConfig) -> None:
    """Strike interval comes from get_strike_interval(symbol). Switching
    symbols must change the spacing without any change to the toggles."""
    from src.data.strike_selector import get_strike_interval

    assert get_strike_interval("NIFTY") == 50
    assert get_strike_interval("BANKNIFTY") == 100

    # All-on toggles, but verify the same toggles produce different strike
    # spacing for the two symbols.
    cfg = config.model_copy(
        update={
            "strike": config.strike.model_copy(
                update={
                    "alert_strikes": config.strike.alert_strikes.model_copy(
                        update={
                            "itm3": False, "itm2": True, "itm1": True,
                            "atm": True,
                            "otm1": True, "otm2": True, "otm3": False,
                        }
                    )
                }
            )
        }
    )
    nifty_feed = _FakeOptionChain([23950, 24000, 24050, 24100, 24150])
    nifty = get_alert_strikes(nifty_feed, "NIFTY", 24030.0, "CE", "2026-06-02", cfg)
    nifty_strikes = [c.strike for c in nifty]

    bn_feed = _FakeOptionChain([50700, 50800, 50900, 51000, 51100])
    bn = get_alert_strikes(bn_feed, "BANKNIFTY", 50930.0, "CE", "2026-06-25", cfg)
    bn_strikes = [c.strike for c in bn]

    # Both lists have the same 5 toggles ON, but NIFTY uses 50-pt and
    # BANKNIFTY uses 100-pt spacing — interval is config-driven, not the toggle.
    nifty_atm = nifty_strikes[nifty_strikes.index(24050)]
    bn_atm = bn_strikes[bn_strikes.index(50900)]
    assert nifty_strikes == [
        nifty_atm - 100, nifty_atm - 50, nifty_atm, nifty_atm + 50, nifty_atm + 100,
    ]
    assert bn_strikes == [
        bn_atm - 200, bn_atm - 100, bn_atm, bn_atm + 100, bn_atm + 200,
    ]


def test_killed_strike_tracks_by_number_across_levels(tmp_path) -> None:
    """Re-entry / kill logic must key off the actual strike NUMBER. So if
    24000 is killed via ITM1, the same number scanned as ITM2 (after spot
    drifts higher) is still killed."""
    from src.state import StateManager

    state_path = tmp_path / "state.json"
    sm = StateManager(state_file=state_path)
    sm.load_state()

    # 24000 stops out twice while it was the ITM1 strike.
    for _ in range(2):
        sm.increment_sl_count("NIFTY", 24000, "CE")

    # Later, spot drifts higher and 24000 is now ITM2 — same number though.
    assert sm.is_strike_killed("NIFTY", 24000, "CE") is True
    # A different strike number must NOT be affected.
    assert sm.is_strike_killed("NIFTY", 23950, "CE") is False
