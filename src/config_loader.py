"""Config loader for Short Cover Cascade bot.

Parses config/config.yaml into a validated AppConfig pydantic model.
ON/OFF strings in YAML are automatically converted to bool.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfigError(Exception):
    """Raised when the configuration is missing fields, malformed, or fails validation."""


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _onoff_to_bool(v: Any) -> Any:
    """Convert ON/OFF (case-insensitive) strings to bool. Passthrough for already-bool values."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s == "on":
            return True
        if s == "off":
            return False
    return v


class _Base(BaseModel):
    """Shared base: forbid extras so typos in config.yaml fail loudly."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- FEEDS ----------


class UpstoxFeedConfig(_Base):
    enabled: bool
    token_validity_days: int = Field(gt=0)

    @field_validator("enabled", mode="before")
    @classmethod
    def _enabled_onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


class KiteFeedConfig(_Base):
    enabled: bool
    token_validity_days: int = Field(gt=0)

    @field_validator("enabled", mode="before")
    @classmethod
    def _enabled_onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


class FeedsConfig(_Base):
    active_feed: Literal["kite", "upstox"]
    healthcheck_timeout_seconds: int = Field(gt=0)
    upstox: UpstoxFeedConfig
    kite: KiteFeedConfig

    @model_validator(mode="after")
    def _active_feed_must_be_enabled(self) -> "FeedsConfig":
        if self.active_feed == "kite" and not self.kite.enabled:
            raise ValueError("feeds.active_feed='kite' but feeds.kite.enabled is OFF")
        if self.active_feed == "upstox" and not self.upstox.enabled:
            raise ValueError("feeds.active_feed='upstox' but feeds.upstox.enabled is OFF")
        return self


# ---------- MODE ----------


class ModeConfig(_Base):
    alert_mode: bool
    order_place_mode: bool
    paper_trade_mode: bool

    @field_validator("alert_mode", "order_place_mode", "paper_trade_mode", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- INSTRUMENTS ----------


class InstrumentsConfig(_Base):
    nifty_enabled: bool
    banknifty_enabled: bool
    nifty_lot_size: int = Field(gt=0)
    banknifty_lot_size: int = Field(gt=0)

    @field_validator("nifty_enabled", "banknifty_enabled", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- STOP LOSS ----------


class StopLossConfig(_Base):
    method: Literal[1, 2]
    use_vix_multiplier: bool
    hard_exit_red_candle_below_vwap: bool

    @field_validator("use_vix_multiplier", "hard_exit_red_candle_below_vwap", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- RISK / REWARD ----------


class RiskRewardConfig(_Base):
    target_risk_per_trade: float = Field(gt=0)
    risk_range_min: float = Field(gt=0)
    risk_range_max: float = Field(gt=0)
    normal_day_tp1_r: float = Field(gt=0)
    normal_day_tp2_r: float = Field(gt=0)
    expiry_day_tp1_r: float = Field(gt=0)
    expiry_day_tp2_r: float = Field(gt=0)
    move_sl_to_breakeven_after_tp1: bool
    trail_sl_after_tp1: bool

    @field_validator("move_sl_to_breakeven_after_tp1", "trail_sl_after_tp1", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)

    @model_validator(mode="after")
    def _sanity(self) -> "RiskRewardConfig":
        if self.risk_range_min > self.risk_range_max:
            raise ValueError("risk_range_min must be <= risk_range_max")
        if not (self.risk_range_min <= self.target_risk_per_trade <= self.risk_range_max):
            raise ValueError(
                "target_risk_per_trade must fall within [risk_range_min, risk_range_max]"
            )
        if self.normal_day_tp2_r <= self.normal_day_tp1_r:
            raise ValueError("normal_day_tp2_r must be > normal_day_tp1_r")
        if self.expiry_day_tp2_r <= self.expiry_day_tp1_r:
            raise ValueError("expiry_day_tp2_r must be > expiry_day_tp1_r")
        return self


# ---------- POSITION SIZING ----------


class PositionSizingConfig(_Base):
    lot_cap_enabled: bool
    nifty_max_lots: int = Field(gt=0)
    banknifty_max_lots: int = Field(gt=0)

    @field_validator("lot_cap_enabled", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- CIRCUIT BREAKERS ----------


class CircuitBreakersConfig(_Base):
    daily_sl_count_breaker: bool
    max_sl_per_day: int = Field(gt=0)
    daily_loss_breaker: bool
    max_loss_per_day_rupees: float = Field(gt=0)

    @field_validator("daily_sl_count_breaker", "daily_loss_breaker", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- ORDERS ----------


class OrdersConfig(_Base):
    order_type: Literal["limit", "market"]
    cancel_if_price_touches_tp1: bool
    fallback_to_market_if_limit_disabled: bool

    @field_validator(
        "cancel_if_price_touches_tp1", "fallback_to_market_if_limit_disabled", mode="before"
    )
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- TIME RULES ----------


def _validate_hhmm(v: Any) -> str:
    if not isinstance(v, str) or not _TIME_RE.match(v):
        raise ValueError(f"expected HH:MM 24-hour time string, got: {v!r}")
    return v


class TimeRulesConfig(_Base):
    normal_start_time: str
    gap_day_start_time: str
    gap_day_filter_enabled: bool
    gap_threshold_percent: float = Field(gt=0)
    last_entry_time: str
    soft_squareoff_time: str
    hard_squareoff_time: str

    @field_validator(
        "normal_start_time",
        "gap_day_start_time",
        "last_entry_time",
        "soft_squareoff_time",
        "hard_squareoff_time",
        mode="before",
    )
    @classmethod
    def _hhmm(cls, v: Any) -> str:
        return _validate_hhmm(v)

    @field_validator("gap_day_filter_enabled", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- RE-ENTRY ----------


class ReEntryConfig(_Base):
    cooldown_minutes_after_sl: int = Field(gt=0)
    same_strike_kill_after_2_sl: bool

    @field_validator("same_strike_kill_after_2_sl", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- STRIKE ----------


class AlertStrikesConfig(_Base):
    itm: bool
    atm: bool
    otm: bool

    @field_validator("itm", "atm", "otm", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)

    @model_validator(mode="after")
    def _at_least_one_on(self) -> "AlertStrikesConfig":
        if not (self.itm or self.atm or self.otm):
            raise ValueError(
                "strike.alert_strikes: at least one of itm/atm/otm must be ON "
                "(otherwise the bot would never alert)"
            )
        return self


class OrderStrikesConfig(_Base):
    itm: bool
    atm: bool
    otm: bool

    @field_validator("itm", "atm", "otm", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)

    def any_on(self) -> bool:
        return self.itm or self.atm or self.otm


class StrikeConfig(_Base):
    max_deviation_from_atm: int = Field(ge=0)
    late_entry_threshold_percent: float = Field(gt=0)
    alert_strikes: AlertStrikesConfig
    order_strikes: OrderStrikesConfig


# ---------- CONDITIONS ----------


class ConditionsConfig(_Base):
    c3_rsi_min: float = Field(ge=0, le=100)
    c3_rsi_max: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _min_lt_max(self) -> "ConditionsConfig":
        if self.c3_rsi_min >= self.c3_rsi_max:
            raise ValueError("c3_rsi_min must be < c3_rsi_max")
        return self


# ---------- TELEGRAM ----------


class TelegramConfig(_Base):
    send_signal_alerts: bool
    send_rejection_alerts: bool
    send_eod_summary: bool
    send_circuit_breaker_alerts: bool
    send_startup_alert: bool

    @field_validator(
        "send_signal_alerts",
        "send_rejection_alerts",
        "send_eod_summary",
        "send_circuit_breaker_alerts",
        "send_startup_alert",
        mode="before",
    )
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- LOGGING ----------


class LoggingConfig(_Base):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    log_every_signal_check: bool
    log_indicator_values: bool

    @field_validator("log_every_signal_check", "log_indicator_values", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- BOT ----------


class BotConfig(_Base):
    scan_buffer_seconds: int = Field(ge=0)
    api_retry_count: int = Field(ge=0)
    api_retry_delay_seconds: float = Field(ge=0)
    state_persistence_enabled: bool

    @field_validator("state_persistence_enabled", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- TOP-LEVEL ----------


class AppConfig(_Base):
    feeds: FeedsConfig
    mode: ModeConfig
    instruments: InstrumentsConfig
    stop_loss: StopLossConfig
    risk_reward: RiskRewardConfig
    position_sizing: PositionSizingConfig
    circuit_breakers: CircuitBreakersConfig
    orders: OrdersConfig
    time_rules: TimeRulesConfig
    re_entry: ReEntryConfig
    strike: StrikeConfig
    conditions: ConditionsConfig
    telegram: TelegramConfig
    logging: LoggingConfig
    bot: BotConfig

    @model_validator(mode="after")
    def _order_strikes_require_when_order_place_on(self) -> "AppConfig":
        if self.mode.order_place_mode and not self.strike.order_strikes.any_on():
            raise ValueError(
                "mode.order_place_mode is ON but strike.order_strikes has all "
                "ITM/ATM/OTM set to OFF — bot would never place an order"
            )
        return self


def load_config(path: str | Path) -> AppConfig:
    """Load and validate config.yaml.

    Raises:
        ConfigError: file missing, YAML malformed, or validation fails.
    """
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"Top-level YAML in {p} must be a mapping, got {type(raw).__name__}")
    try:
        return AppConfig.model_validate(raw)
    except Exception as e:
        raise ConfigError(f"Config validation failed for {p}: {e}") from e


def load_secrets(secrets_path: str | Path = "config/secrets.env") -> None:
    """Load secrets.env into the process environment. Idempotent.

    Single source of truth for secrets loading. Every script (and main.py)
    should call this before ``load_config`` so any code path that later
    calls ``os.getenv`` for broker tokens / API keys sees them.

    Raises:
        FileNotFoundError: secrets file is missing.
    """
    from dotenv import load_dotenv

    p = Path(secrets_path)
    if not p.exists():
        raise FileNotFoundError(f"Secrets file not found: {secrets_path}")
    load_dotenv(p, override=True)
