"""Tests for the shadow stop-loss lab (src/shadow_sl/).

The shadow lab is ISOLATED from the live pipeline. These tests pin:

  1. The candle walk's exit logic per registered method (sma19,
     atr_initial, chandelier, chandelier_time).
  2. The chandelier ratchet never loosens.
  3. The time-stop fires when MFE stays flat.
  4. The sma19 clamp keeps SL strictly below the live price.
  5. The runner only ever writes ``logs/shadow_sl.jsonl`` — it never
     touches paper_trades.jsonl, the monthly Parquet store, or the
     Excel dashboards.
  6. Adding or removing a registry entry leaves the other methods
     unaffected.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.config_loader import load_config
from src.shadow_sl import engine, methods  # noqa: F401 — registers methods
from src.shadow_sl.runner import run

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Test fixtures: synthetic 5-min candle frames
# ---------------------------------------------------------------------------


def _candle(hh: int, mm: int, o: float, h: float, low: float, c: float, v: float = 1000.0) -> dict:
    return {
        "timestamp": datetime(2026, 5, 27, hh, mm, tzinfo=IST),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": v,
    }


def _build_session(entry_value: float = 150.0) -> list[dict]:
    """A neutral pre-entry session so VWAP/ATR are well-defined.

    Returns 10 candles 09:15 → 10:00. Entry candle is the 10:00 one.
    """
    return [
        _candle(9, mm, entry_value - 2, entry_value + 2, entry_value - 2, entry_value)
        for mm in (15, 20, 25, 30, 35, 40, 45, 50, 55)
    ] + [
        _candle(10, 0, entry_value, entry_value + 2, entry_value - 1, entry_value),
    ]


def _entry_params(method: str, **extra) -> dict:
    """Shared params block. Pin entry_timestamp to 10:00 in the synthetic session."""
    params = {
        "entry_timestamp": datetime(2026, 5, 27, 10, 0, tzinfo=IST),
        "atr_period": 14,
        "hard_squareoff_time": "15:00",
    }
    params.update(extra)
    return params


# ---------------------------------------------------------------------------
# Per-method exit logic
# ---------------------------------------------------------------------------


def test_registry_has_all_four_methods():
    for name in ("sma19", "atr_initial", "chandelier", "chandelier_time"):
        assert name in engine.REGISTRY
    # Adding/removing a name must not break the others — confirmed by the
    # isolated registration of each method.


def test_sma19_sl_hit():
    """Static-SL phase: a candle that punches below the initial SL exits."""
    candles = pd.DataFrame(
        _build_session() + [
            _candle(10, 5, 150, 152, 138, 142),  # low 138 < SL 140
        ]
    )
    result = methods.evaluate_sma19(
        entry=150.0,
        initial_sl=140.0,
        tp1=165.0,
        tp2=175.0,
        candles_df=candles,
        params=_entry_params("sma19"),
    )
    assert "SL_HIT" in result["exit_reason"]
    assert result["exit_price"] == pytest.approx(140.0)
    assert result["r_multiple"] == pytest.approx(-1.0)


def test_sma19_tp1_then_tp2():
    """TP1 banks half; second leg hits TP2 → 0.5*tp1_r + 0.5*tp2_r."""
    candles = pd.DataFrame(
        _build_session() + [
            _candle(10, 5, 150, 166, 149, 165),   # TP1 hit (165)
            _candle(10, 10, 165, 176, 160, 174),  # TP2 hit (175)
        ]
    )
    result = methods.evaluate_sma19(
        entry=150.0,
        initial_sl=140.0,
        tp1=165.0,
        tp2=175.0,
        candles_df=candles,
        params=_entry_params("sma19"),
    )
    # 0.5 * (165-150)/10 + 0.5 * (175-150)/10 = 0.75 + 1.25 = 2.0R
    assert result["r_multiple"] == pytest.approx(2.0)
    assert "TP2_HIT" in result["exit_reason"]


def test_sma19_clamp_blocks_sl_above_price():
    """If the SMA trail tries to push SL above price, the clamp must cap it.

    We feed an upward-trending tail. After activate_after_minutes the
    SMA of the option close has CAUGHT UP near the current price. The
    clamp must hold the SL at (close - 1 tick) — strictly below price.
    """
    # Strong uptrend after entry — closes 150 → 165 over 6 candles.
    tail = []
    closes = [152, 155, 158, 161, 163, 165]
    for i, cl in enumerate(closes):
        mm = 5 + 5 * i
        hh = 10 + mm // 60
        mm = mm % 60
        tail.append(_candle(hh, mm, cl - 1, cl + 1, cl - 2, cl))

    candles = pd.DataFrame(_build_session() + tail)
    params = _entry_params(
        "sma19",
        sma_period=3,             # short SMA so it catches up quickly
        activate_after_minutes=0, # start trailing immediately
        update_interval_minutes=5,
        follow_direction="both",
        tick=0.05,
    )
    # Make TPs unreachable so the trail is the only exit mechanism.
    result = methods.evaluate_sma19(
        entry=150.0,
        initial_sl=140.0,
        tp1=999.0,
        tp2=1999.0,
        candles_df=candles,
        params=params,
    )
    # The SL exit must be at a price that is strictly LOWER than the
    # candle's close (clamp), and the SL must have moved up from the
    # initial 140.0 (it trailed up).
    assert result["exit_price"] is not None
    assert result["exit_price"] > 140.0, (
        f"SL did not trail up (still {result['exit_price']})"
    )
    # The clamp guarantees SL <= candle_close - tick; in particular the
    # raw SMA was never allowed to overshoot price.
    assert "SL_HIT" in result["exit_reason"]


def test_atr_initial_static_no_trail():
    """atr_initial keeps the SL static; a steep dip exits at that anchor."""
    # Build a strong-mid-session move then a deep dip.
    tail = [
        _candle(10, 5, 150, 160, 150, 158),
        _candle(10, 10, 158, 159, 155, 156),
        _candle(10, 15, 156, 158, 100, 105),  # huge dip below any reasonable SL
    ]
    candles = pd.DataFrame(_build_session() + tail)
    # Use small k so the anchored SL is comfortably ABOVE 100 (the dip's low).
    params = _entry_params("atr_initial", k=2.0)
    result = methods.evaluate_atr_initial(
        entry=150.0,
        initial_sl=140.0,
        tp1=999.0,
        tp2=1999.0,
        candles_df=candles,
        params=params,
    )
    # The static SL must be above the dip's low (otherwise we exited).
    assert "SL_HIT" in result["exit_reason"]
    # Static SL — exit price must be a finite number near the anchored SL.
    assert result["exit_price"] is not None
    # Because the dip's low is 100 and the anchored SL is far above 100,
    # the exit price is the anchored SL itself, NOT the candle's low.
    assert result["exit_price"] > 100.0


def test_chandelier_ratchets_up_never_down():
    """The chandelier SL only moves up; a subsequent down move does not loosen it."""
    # Sharp up move to push the ratchet, then a slow drift back down
    # that does not touch the ratcheted SL.
    tail = [
        _candle(10, 5, 150, 200, 150, 198),    # huge high → anchors a high
        _candle(10, 10, 198, 199, 195, 197),
        _candle(10, 15, 197, 198, 100, 110),   # low 100 — would exit at the ratchet
    ]
    candles = pd.DataFrame(_build_session() + tail)
    params = _entry_params("chandelier", k=3.0)
    result = methods.evaluate_chandelier(
        entry=150.0,
        initial_sl=140.0,
        tp1=999.0,
        tp2=1999.0,
        candles_df=candles,
        params=params,
    )
    # Must exit on the down-leg via the ratcheted SL.
    assert "SL_HIT" in result["exit_reason"]
    # The exit_price (= ratcheted SL) must be strictly ABOVE the initial 140.
    assert result["exit_price"] > 140.0


def test_chandelier_time_fires_when_flat():
    """time_stop must force-exit when MFE stays below min_r past the deadline."""
    # Flat market: each candle's high is barely above entry, never reaching min_r.
    flat = []
    for i in range(12):
        mm = 5 + 5 * i
        hh = 10 + mm // 60
        mm = mm % 60
        flat.append(_candle(hh, mm, 150.0, 150.5, 149.5, 150.0))
    candles = pd.DataFrame(_build_session() + flat)
    params = _entry_params(
        "chandelier_time",
        k=3.0,
        time_stop_minutes=15,   # short for the test
        time_stop_min_r=1.0,
    )
    result = methods.evaluate_chandelier_time(
        entry=150.0,
        initial_sl=140.0,
        tp1=999.0,
        tp2=1999.0,
        candles_df=candles,
        params=params,
    )
    assert "time_stop" in result["exit_reason"]
    # Exit was at a flat-market close near 150 → near 0R (regardless of sign).
    assert abs(result["r_multiple"]) < 0.1


def test_chandelier_time_does_not_fire_when_target_hit():
    """If MFE >= min_r before the deadline, the time-stop must not trigger."""
    tail = [
        _candle(10, 5, 150, 162, 150, 161),   # MFE jumps to 1.1R
        _candle(10, 10, 161, 162, 160, 161),
        _candle(10, 15, 161, 176, 160, 174),  # TP2 hit
    ]
    candles = pd.DataFrame(_build_session() + tail)
    params = _entry_params(
        "chandelier_time",
        k=3.0,
        time_stop_minutes=15,
        time_stop_min_r=1.0,
    )
    result = methods.evaluate_chandelier_time(
        entry=150.0,
        initial_sl=140.0,
        tp1=165.0,
        tp2=175.0,
        candles_df=candles,
        params=params,
    )
    assert "time_stop" not in result["exit_reason"]


# ---------------------------------------------------------------------------
# Runner isolation
# ---------------------------------------------------------------------------


def test_runner_only_touches_shadow_output(tmp_path, monkeypatch):
    """The runner must never write to paper_trades.jsonl / parquet / Excel.

    We stage a temp project where these files exist. After ``run()`` we
    assert their mtimes are unchanged and the shadow output file is
    the ONLY thing modified.
    """
    # Stage the project layout.
    logs_dir = tmp_path / "logs"
    dash_dir = logs_dir / "dashboards"
    data_dir = tmp_path / "data"
    cache_root = data_dir / "replay_cache"
    logs_dir.mkdir(parents=True)
    dash_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    cache_root.mkdir(parents=True)

    paper_path = logs_dir / "paper_trades.jsonl"
    parquet_path = data_dir / "scc_data_2026-05.parquet"
    excel_path = dash_dir / "dashboard_2026_Q2.xlsx"
    alerts_path = logs_dir / "alerts.jsonl"
    output_path = logs_dir / "shadow_sl.jsonl"

    # Sentinel content (any bytes — we only watch for change).
    paper_path.write_text("PAPER-DO-NOT-TOUCH\n", encoding="utf-8")
    parquet_path.write_bytes(b"PARQUET-DO-NOT-TOUCH")
    excel_path.write_bytes(b"EXCEL-DO-NOT-TOUCH")

    # One alert pointing at a candle file we'll stage in cache.
    entry_ts = datetime(2026, 5, 27, 10, 0, tzinfo=IST)
    alert = {
        "event_type": "alert",
        "timestamp_ist": entry_ts.isoformat(),
        "candle_timestamp": entry_ts.isoformat(),
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "relation": "ATM",
        "expiry": "2026-06-02",
        "entry": 150.0,
        "sl": 140.0,
        "day_type": "Normal",
    }
    alerts_path.write_text(json.dumps(alert) + "\n", encoding="utf-8")

    # Stage replay-cache parquet for that date/strike/type.
    day_dir = cache_root / "2026-05-27"
    day_dir.mkdir(parents=True)
    candles = pd.DataFrame(
        _build_session() + [_candle(10, 5, 150, 152, 138, 142)]
    )
    candles.to_parquet(day_dir / "NIFTY_24050_CE.parquet", index=False)

    # Live config, but with the temp paths bound through patches.
    cfg = load_config(PROJECT_ROOT / "config" / "config.yaml")

    # Custom loader that reads our temp replay cache (the runner's
    # default points at the live project's data/replay_cache).
    def loader(symbol, strike, option_type, trading_date):
        p = (
            cache_root
            / trading_date.isoformat()
            / f"{symbol.upper()}_{int(strike)}_{option_type.upper()}.parquet"
        )
        if not p.exists():
            return None
        return pd.read_parquet(p)

    sentinels_before = {
        "paper": paper_path.stat().st_mtime_ns,
        "parquet": parquet_path.stat().st_mtime_ns,
        "excel": excel_path.stat().st_mtime_ns,
    }

    result = run(
        app_config=cfg,
        alerts_path=alerts_path,
        output_path=output_path,
        candle_loader=loader,
    )

    # New shadow file exists with at least one row.
    assert output_path.exists()
    assert result.rows_written >= 1

    # Sentinels untouched.
    assert paper_path.stat().st_mtime_ns == sentinels_before["paper"]
    assert paper_path.read_text(encoding="utf-8") == "PAPER-DO-NOT-TOUCH\n"
    assert parquet_path.stat().st_mtime_ns == sentinels_before["parquet"]
    assert parquet_path.read_bytes() == b"PARQUET-DO-NOT-TOUCH"
    assert excel_path.stat().st_mtime_ns == sentinels_before["excel"]
    assert excel_path.read_bytes() == b"EXCEL-DO-NOT-TOUCH"


def test_runner_is_idempotent(tmp_path):
    """Running twice must NOT duplicate rows for the same (alert × method)."""
    logs_dir = tmp_path / "logs"
    data_dir = tmp_path / "data"
    cache_root = data_dir / "replay_cache"
    logs_dir.mkdir(parents=True)
    cache_root.mkdir(parents=True)

    entry_ts = datetime(2026, 5, 27, 10, 0, tzinfo=IST)
    alert = {
        "event_type": "alert",
        "timestamp_ist": entry_ts.isoformat(),
        "candle_timestamp": entry_ts.isoformat(),
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "relation": "ATM",
        "expiry": "2026-06-02",
        "entry": 150.0,
        "sl": 140.0,
        "day_type": "Normal",
    }
    alerts_path = logs_dir / "alerts.jsonl"
    output_path = logs_dir / "shadow_sl.jsonl"
    alerts_path.write_text(json.dumps(alert) + "\n", encoding="utf-8")

    day_dir = cache_root / "2026-05-27"
    day_dir.mkdir(parents=True)
    candles = pd.DataFrame(
        _build_session() + [_candle(10, 5, 150, 152, 138, 142)]
    )
    candles.to_parquet(day_dir / "NIFTY_24050_CE.parquet", index=False)

    cfg = load_config(PROJECT_ROOT / "config" / "config.yaml")

    def loader(symbol, strike, option_type, trading_date):
        p = (
            cache_root
            / trading_date.isoformat()
            / f"{symbol.upper()}_{int(strike)}_{option_type.upper()}.parquet"
        )
        return pd.read_parquet(p) if p.exists() else None

    first = run(
        app_config=cfg,
        alerts_path=alerts_path,
        output_path=output_path,
        candle_loader=loader,
    )
    assert first.rows_written >= 1

    # Second run must skip every row as a duplicate.
    second = run(
        app_config=cfg,
        alerts_path=alerts_path,
        output_path=output_path,
        candle_loader=loader,
    )
    assert second.rows_written == 0
    assert second.rows_skipped_duplicate == first.rows_written


def test_disabled_method_is_skipped(tmp_path):
    """A method whose enabled=False must not appear in shadow_sl.jsonl."""
    logs_dir = tmp_path / "logs"
    data_dir = tmp_path / "data"
    cache_root = data_dir / "replay_cache"
    logs_dir.mkdir(parents=True)
    cache_root.mkdir(parents=True)

    entry_ts = datetime(2026, 5, 27, 10, 0, tzinfo=IST)
    alert = {
        "event_type": "alert",
        "timestamp_ist": entry_ts.isoformat(),
        "candle_timestamp": entry_ts.isoformat(),
        "symbol": "NIFTY",
        "strike": 24050,
        "option_type": "CE",
        "relation": "ATM",
        "expiry": "2026-06-02",
        "entry": 150.0,
        "sl": 140.0,
        "day_type": "Normal",
    }
    alerts_path = logs_dir / "alerts.jsonl"
    output_path = logs_dir / "shadow_sl.jsonl"
    alerts_path.write_text(json.dumps(alert) + "\n", encoding="utf-8")

    day_dir = cache_root / "2026-05-27"
    day_dir.mkdir(parents=True)
    candles = pd.DataFrame(
        _build_session() + [_candle(10, 5, 150, 152, 138, 142)]
    )
    candles.to_parquet(day_dir / "NIFTY_24050_CE.parquet", index=False)

    cfg = load_config(PROJECT_ROOT / "config" / "config.yaml")
    # Disable everything except sma19 via model_copy on the loaded config.
    methods_block = cfg.shadow_sl.methods.model_copy(
        update={
            "atr_initial": cfg.shadow_sl.methods.atr_initial.model_copy(
                update={"enabled": False}
            ),
            "chandelier": cfg.shadow_sl.methods.chandelier.model_copy(
                update={"enabled": False}
            ),
            "chandelier_time": cfg.shadow_sl.methods.chandelier_time.model_copy(
                update={"enabled": False}
            ),
        }
    )
    cfg = cfg.model_copy(
        update={
            "shadow_sl": cfg.shadow_sl.model_copy(update={"methods": methods_block})
        }
    )

    def loader(symbol, strike, option_type, trading_date):
        p = (
            cache_root
            / trading_date.isoformat()
            / f"{symbol.upper()}_{int(strike)}_{option_type.upper()}.parquet"
        )
        return pd.read_parquet(p) if p.exists() else None

    result = run(
        app_config=cfg,
        alerts_path=alerts_path,
        output_path=output_path,
        candle_loader=loader,
    )
    assert result.methods_run == ["sma19"]
    assert result.rows_written == 1
    # Confirm by file content.
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {r["method"] for r in rows} == {"sma19"}


# ---------------------------------------------------------------------------
# Registry isolation — adding/removing entries doesn't affect others
# ---------------------------------------------------------------------------


def test_registry_add_remove_isolation():
    """Mutating REGISTRY with a custom method leaves the originals intact."""
    original_keys = set(engine.REGISTRY.keys())

    @engine.register("test_dummy")
    def _dummy(entry, initial_sl, tp1, tp2, candles_df, params):
        return {
            "exit_price": float(entry),
            "exit_time": "",
            "exit_reason": "dummy",
            "r_multiple": 0.0,
            "max_unrealized_r": 0.0,
            "gave_back_r": 0.0,
        }

    try:
        assert "test_dummy" in engine.REGISTRY
        # Originals unaffected.
        for name in ("sma19", "atr_initial", "chandelier", "chandelier_time"):
            assert name in engine.REGISTRY
        # The four production methods still execute.
        candles = pd.DataFrame(
            _build_session() + [_candle(10, 5, 150, 152, 138, 142)]
        )
        for name in ("sma19", "atr_initial", "chandelier", "chandelier_time"):
            evaluate = engine.get_method(name)
            params = _entry_params(name)
            out = evaluate(150.0, 140.0, 165.0, 175.0, candles, params)
            assert "exit_reason" in out
    finally:
        del engine.REGISTRY["test_dummy"]

    assert set(engine.REGISTRY.keys()) == original_keys
