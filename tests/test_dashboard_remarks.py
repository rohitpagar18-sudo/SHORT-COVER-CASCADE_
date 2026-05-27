"""Phase 5.2 — bot_remark / bot_tags generator tests.

Pure-function tests: no I/O, no orchestrator, no broker.
"""

from __future__ import annotations

import pytest

from src.dashboard.remarks import (
    generate_outcome_remark,
    generate_remark_and_tags,
    telegram_short_remark,
)


def _snap(**overrides) -> dict:
    base = {
        "option_close": 150.0,
        "option_vwap": 140.0,
        "rsi": 65.0,
        "rsi_ma": 55.0,
        "oi": 800_000.0,
        "oi_ma": 1_000_000.0,
        "volume": 3_000.0,
        "volume_ma": 1_500.0,
        "opt_above_vwap_pct": 7.0,
    }
    base.update(overrides)
    return base


def _ctx(**overrides) -> dict:
    base = {
        "time_hhmm": "10:25",
        "vix_regime": "Normal",
        "is_expiry_day": False,
        "daily_sl_count": 0,
        "daily_alert_count": 0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tag-zone unit tests
# ---------------------------------------------------------------------------


def test_fresh_breakout_tag_under_10pct() -> None:
    _, tags = generate_remark_and_tags(_snap(opt_above_vwap_pct=8.0), _ctx())
    assert "fresh_breakout" in tags.split(",")


def test_late_entry_tag_above_22pct() -> None:
    _, tags = generate_remark_and_tags(_snap(opt_above_vwap_pct=27.0), _ctx())
    assert "late_entry" in tags.split(",")


def test_strong_rsi_tag_60_to_74() -> None:
    _, tags = generate_remark_and_tags(_snap(rsi=68.0), _ctx())
    assert "strong_rsi" in tags.split(",")


def test_strong_oi_tag_above_15pct_below_ma() -> None:
    # OI 800k vs MA 1M = 20% below MA → strong_oi
    _, tags = generate_remark_and_tags(
        _snap(oi=800_000.0, oi_ma=1_000_000.0), _ctx()
    )
    assert "strong_oi" in tags.split(",")


def test_explosive_volume_tag_above_2x() -> None:
    _, tags = generate_remark_and_tags(
        _snap(volume=4_000.0, volume_ma=1_500.0), _ctx()  # 2.67×
    )
    assert "explosive_volume" in tags.split(",")


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


def test_verdict_strong_when_all_signals_firm() -> None:
    remark, _ = generate_remark_and_tags(
        _snap(
            opt_above_vwap_pct=8.0,
            rsi=65.0,
            oi=800_000.0,
            oi_ma=1_000_000.0,  # 20% below
            volume=3_000.0,
            volume_ma=1_500.0,  # 2× MA
        ),
        _ctx(),
    )
    assert remark.startswith("5/5 strong")


def test_verdict_borderline_when_any_marginal() -> None:
    remark, _ = generate_remark_and_tags(
        _snap(rsi=52.0),  # below 55 → marginal
        _ctx(),
    )
    assert remark.startswith("5/5 borderline")


# ---------------------------------------------------------------------------
# Length / shape guarantees
# ---------------------------------------------------------------------------


def test_remark_length_under_30_words() -> None:
    remark, _ = generate_remark_and_tags(_snap(), _ctx())
    assert len(remark.split()) < 30


def test_remark_contains_verdict_prefix() -> None:
    remark, _ = generate_remark_and_tags(_snap(), _ctx())
    assert remark.startswith("5/5 ")


def test_tags_comma_separated_no_spaces() -> None:
    _, tags = generate_remark_and_tags(_snap(), _ctx())
    assert "," in tags
    assert " " not in tags
    assert "_" in tags  # tags use snake_case


# ---------------------------------------------------------------------------
# Telegram short
# ---------------------------------------------------------------------------


def test_telegram_short_remark_under_80_chars() -> None:
    remark, _ = generate_remark_and_tags(_snap(), _ctx())
    short = telegram_short_remark(remark)
    assert 0 < len(short) <= 80


def test_telegram_short_remark_handles_empty() -> None:
    assert telegram_short_remark("") == ""


# ---------------------------------------------------------------------------
# Outcome remark generator
# ---------------------------------------------------------------------------


def test_outcome_remark_tp2_for_strong_setup() -> None:
    out = generate_outcome_remark(
        {"bot_remark": "5/5 strong — opt 8% above VWAP"},
        outcome="TP2_HIT",
        exit_price=175.0,
    )
    assert "TP2" in out
    assert "strong setup played out" in out


def test_outcome_remark_sl_for_marginal_setup() -> None:
    out = generate_outcome_remark(
        {"bot_remark": "5/5 borderline — opt 25% above VWAP"},
        outcome="SL_HIT",
        exit_price=130.0,
    )
    assert "marginal entry showed in outcome" in out


# ---------------------------------------------------------------------------
# Sequence context
# ---------------------------------------------------------------------------


def test_first_alert_tag_when_count_zero() -> None:
    _, tags = generate_remark_and_tags(
        _snap(), _ctx(daily_alert_count=0, daily_sl_count=0)
    )
    assert "first_alert" in tags.split(",")


def test_after_sl_tag_when_sl_count_positive() -> None:
    _, tags = generate_remark_and_tags(
        _snap(), _ctx(daily_alert_count=2, daily_sl_count=1)
    )
    assert "after_sl" in tags.split(",")


# ---------------------------------------------------------------------------
# VIX phrase tolerates both enum-name and enum-value forms.
# ---------------------------------------------------------------------------


def test_vix_phrase_accepts_enum_value() -> None:
    _, tags = generate_remark_and_tags(_snap(), _ctx(vix_regime="High Vol"))
    assert "high_vix" in tags.split(",")


def test_vix_phrase_accepts_enum_name() -> None:
    _, tags = generate_remark_and_tags(_snap(), _ctx(vix_regime="HIGH"))
    assert "high_vix" in tags.split(",")
