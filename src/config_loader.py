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


class SmaTrailConfig(_Base):
    """SL Method 3 — 19-SMA trailing knobs.

    Active only when ``stop_loss.method == 3``. Defaults match the
    strategy-doc N=19 / 15-min activate / 15-min update cadence and
    bidirectional follow.
    """

    sma_period: int = Field(default=19, gt=0)
    activate_after_minutes: int = Field(default=15, ge=0)
    update_interval_minutes: int = Field(default=15, gt=0)
    follow_direction: Literal["both", "ratchet"] = Field(default="both")


class StopLossConfig(_Base):
    method: Literal[1, 2, 3]
    use_vix_multiplier: bool
    hard_exit_red_candle_below_vwap: bool
    sma_trail: SmaTrailConfig = Field(default_factory=SmaTrailConfig)

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
        if self.target_risk_per_trade > self.risk_range_max:
            raise ValueError(
                "target_risk_per_trade must be <= risk_range_max "
                "(risk_range_min is informational — lower risk is allowed)"
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
    last_entry_time: str
    soft_squareoff_time: str
    hard_squareoff_time: str
    gap_day_enabled: bool
    gap_day_threshold_pct: float = Field(gt=0)
    gap_day_direction: Literal["both", "up", "down"]

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

    @field_validator("gap_day_enabled", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)

    @field_validator("gap_day_direction", mode="before")
    @classmethod
    def _normalize_direction(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        return v


# ---------- RE-ENTRY ----------


class ReEntryConfig(_Base):
    cooldown_minutes_after_sl: int = Field(gt=0)
    same_strike_kill_after_2_sl: bool

    @field_validator("same_strike_kill_after_2_sl", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- STRIKE ----------


# Per-level strike-depth toggles. Each level is independent — non-contiguous
# combos (e.g. itm1 ON, itm2 OFF, itm3 ON) are allowed.
_ALERT_STRIKE_LEVELS: tuple[str, ...] = (
    "itm3", "itm2", "itm1", "atm", "otm1", "otm2", "otm3",
)


class AlertStrikesConfig(_Base):
    # New defaults: itm2/itm1/atm ON, the rest OFF.
    itm3: bool = False
    itm2: bool = True
    itm1: bool = True
    atm: bool = True
    otm1: bool = False
    otm2: bool = False
    otm3: bool = False

    @field_validator(*_ALERT_STRIKE_LEVELS, mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)

    @model_validator(mode="after")
    def _at_least_one_on(self) -> "AlertStrikesConfig":
        if not any(getattr(self, lvl) for lvl in _ALERT_STRIKE_LEVELS):
            raise ValueError(
                "strike.alert_strikes: at least one of "
                "itm1/itm2/itm3/atm/otm1/otm2/otm3 must be ON "
                "(otherwise the bot would never alert)"
            )
        return self

    def enabled_levels(self) -> list[str]:
        """Levels that are ON, in display order ITM3..ATM..OTM3."""
        return [lvl.upper() for lvl in _ALERT_STRIKE_LEVELS if getattr(self, lvl)]


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


class C5AdxConfig(_Base):
    """C5 ADX trend filter — Phase 6.1 shadow-mode addition.

    The two booleans are deliberately independent:
        enabled  -> compute + log + display the C5 result
        gating   -> include C5 in the all_passed (trigger) computation
    Shadow mode is (enabled=True, gating=False): C5 runs and is logged,
    but never blocks an alert.
    """

    enabled: bool = Field(default=True)
    gating: bool = Field(default=False)
    period: int = Field(default=14, gt=0)
    adx_min: float = Field(default=20.0, ge=0)
    require_rising: bool = Field(default=True)
    use_di_alignment: bool = Field(default=True)
    lookback_candles: int = Field(default=150, gt=0)

    @field_validator(
        "enabled", "gating", "require_rising", "use_di_alignment",
        mode="before",
    )
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


class ConditionsConfig(_Base):
    c3_rsi_min: float = Field(ge=0, le=100)
    c3_rsi_max: float = Field(ge=0, le=100)

    # C0 spot-trend filter toggle. Default False so older configs (without
    # this field) load cleanly AND the new safer default applies: scan
    # both CE and PE on every selected strike, let C1–C4 decide.
    c0_spot_trend_filter_enabled: bool = Field(default=False)

    # Phase 5.2: C1 late-entry filter (configurable + extended zone logging).
    c1_max_distance_pct: float = Field(default=30.0, gt=0)
    c1_extended_zone_enabled: bool = Field(default=True)
    c1_extended_zone_max_pct: float = Field(default=50.0, gt=0)

    # Phase 6.1: C5 ADX trend filter. Default factory keeps older configs
    # (which lack the c5_adx block) loadable without complaint.
    c5_adx: C5AdxConfig = Field(default_factory=C5AdxConfig)

    @field_validator(
        "c0_spot_trend_filter_enabled",
        "c1_extended_zone_enabled",
        mode="before",
    )
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)

    @model_validator(mode="after")
    def _min_lt_max(self) -> "ConditionsConfig":
        if self.c3_rsi_min >= self.c3_rsi_max:
            raise ValueError("c3_rsi_min must be < c3_rsi_max")
        if self.c1_extended_zone_max_pct <= self.c1_max_distance_pct:
            raise ValueError(
                "c1_extended_zone_max_pct must be > c1_max_distance_pct"
            )
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
    log_extended_zone: bool = Field(default=True)

    @field_validator(
        "log_every_signal_check",
        "log_indicator_values",
        "log_extended_zone",
        mode="before",
    )
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- DASHBOARD (Phase 5.2) ----------


class DashboardConfig(_Base):
    auto_trigger_at_1535: bool = Field(default=True)
    excel_rotation: Literal["quarterly"] = Field(default="quarterly")
    parquet_rotation: Literal["monthly"] = Field(default="monthly")
    send_eod_dashboard_link: bool = Field(default=False)
    outcome_categories: list[str] = Field(
        default_factory=lambda: ["TP2_HIT", "TP1_HIT", "SL_HIT", "PARTIAL", "WOULD_SKIP"]
    )
    # Phase 5B-A — post-hoc virtual exit replay. Default OFF.
    auto_outcome_tracking: bool = Field(default=False)

    @field_validator(
        "auto_trigger_at_1535",
        "send_eod_dashboard_link",
        "auto_outcome_tracking",
        mode="before",
    )
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- PAPER TRADING (Phase 5D) ----------


class PaperOrderStrikesConfig(_Base):
    """Phase 5D — paper-trade relation gate.

    Mirrors ``OrderStrikesConfig`` (the Phase 8 auto-order knob) but for
    the paper layer. 3-way bucket: ``itm`` covers ITM1/ITM2/ITM3,
    ``otm`` covers OTM1/OTM2/OTM3.
    """

    itm: bool = True
    atm: bool = True
    otm: bool = False

    @field_validator("itm", "atm", "otm", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)

    @model_validator(mode="after")
    def _at_least_one_on(self) -> "PaperOrderStrikesConfig":
        if not (self.itm or self.atm or self.otm):
            raise ValueError(
                "paper_trading.paper_order_strikes: at least one of "
                "itm/atm/otm must be ON (otherwise no paper trade would "
                "ever be taken)"
            )
        return self

    def allows_relation(self, relation: str | None) -> bool:
        """Map relation label (ITM1/ITM2/ITM3/ATM/OTM1/OTM2/OTM3) to bucket.

        Unknown / missing relations are allowed (fail-safe) — the
        selector still gets to apply the §13/§14 caps.
        """
        if relation is None:
            return True
        r = str(relation).strip().upper()
        if not r:
            return True
        if r == "ATM":
            return self.atm
        if r.startswith("ITM"):
            return self.itm
        if r.startswith("OTM"):
            return self.otm
        return True


class PaperTradingConfig(_Base):
    """Phase 5D — paper-trade tracking & first-alert selection.

    Read-only layer over the alert-only bot. Episode-collapses re-fires,
    runs a deterministic selection gate (§13/§14 caps), then calls the
    Phase 5B-A exit kernel on each TAKEN representative. No order
    placement, no live-scan side effects.
    """

    enabled: bool = Field(default=True)
    episode_key: list[str] = Field(
        default_factory=lambda: ["symbol", "option_type"]
    )
    dedup_window_minutes: int = Field(default=20, gt=0)
    relation_priority: list[str] = Field(
        default_factory=lambda: ["ITM1", "ATM", "ITM2", "ITM3", "OTM1", "OTM2", "OTM3"]
    )
    paper_order_strikes: PaperOrderStrikesConfig = Field(
        default_factory=PaperOrderStrikesConfig
    )
    max_trades_per_day: int = Field(default=3, gt=0)
    circuit_breaker_sl_count: int = Field(default=2, gt=0)
    cooldown_minutes_after_sl: int = Field(default=15, ge=0)
    same_strike_kill_after_2_sl: bool = Field(default=True)
    paper_trades_path: str = Field(default="logs/paper_trades.jsonl")
    paper_overrides_path: str = Field(default="logs/paper_overrides.csv")

    @field_validator(
        "enabled", "same_strike_kill_after_2_sl", mode="before",
    )
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)

    @model_validator(mode="after")
    def _sane_lists(self) -> "PaperTradingConfig":
        if not self.episode_key:
            raise ValueError("paper_trading.episode_key cannot be empty")
        if not self.relation_priority:
            raise ValueError("paper_trading.relation_priority cannot be empty")
        return self


# ---------- SHADOW SL (experimental, read-only lab) ----------


class _ShadowMethodBase(_Base):
    """Common base for shadow_sl per-method blocks. Always has ``enabled``."""

    enabled: bool = Field(default=False)

    @field_validator("enabled", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


class ShadowSlSma19Config(_ShadowMethodBase):
    """SMA-trail baseline. Defaults mirror live Method-3 knobs."""

    sma_period: int = Field(default=19, gt=0)
    activate_after_minutes: int = Field(default=15, ge=0)
    update_interval_minutes: int = Field(default=15, gt=0)
    follow_direction: Literal["both", "ratchet"] = Field(default="both")
    tick: float = Field(default=0.05, gt=0)


class ShadowSlAtrInitialConfig(_ShadowMethodBase):
    """Static ATR-anchored stop. ``SL = entry_vwap - k * ATR``."""

    k: float = Field(default=2.0, gt=0)


class ShadowSlChandelierConfig(_ShadowMethodBase):
    """Chandelier exit. ``SL = highest_high_since_entry - k * ATR``."""

    k: float = Field(default=3.0, gt=0)


class ShadowSlChandelierTimeConfig(_ShadowMethodBase):
    """Chandelier exit + time-stop combo."""

    k: float = Field(default=3.0, gt=0)
    time_stop_minutes: int = Field(default=35, gt=0)
    time_stop_min_r: float = Field(default=1.0, ge=0)


class ShadowSlMethodsConfig(_Base):
    sma19: ShadowSlSma19Config = Field(default_factory=ShadowSlSma19Config)
    atr_initial: ShadowSlAtrInitialConfig = Field(
        default_factory=ShadowSlAtrInitialConfig
    )
    chandelier: ShadowSlChandelierConfig = Field(
        default_factory=ShadowSlChandelierConfig
    )
    chandelier_time: ShadowSlChandelierTimeConfig = Field(
        default_factory=ShadowSlChandelierTimeConfig
    )


class ShadowSlConfig(_Base):
    """Experimental, READ-ONLY shadow stop-loss lab.

    Lives entirely in ``src/shadow_sl/`` and writes only to
    ``logs/shadow_sl.jsonl``. NEVER affects real/paper P&L, the
    Parquet store, or the Excel dashboards. Defaults make the lab safe
    to leave enabled — methods opt in individually.
    """

    enabled: bool = Field(default=False)
    atr_period: int = Field(default=14, gt=0)
    methods: ShadowSlMethodsConfig = Field(default_factory=ShadowSlMethodsConfig)

    @field_validator("enabled", mode="before")
    @classmethod
    def _onoff(cls, v: Any) -> Any:
        return _onoff_to_bool(v)


# ---------- BOT ----------


class BotConfig(_Base):
    scan_buffer_seconds: int = Field(ge=5, le=60)
    api_retry_count: int = Field(ge=0)
    api_retry_delay_seconds: float = Field(ge=0)
    state_persistence_enabled: bool
    # Intraday VIX refresh cadence (minutes). 0 = lock at session start
    # (legacy behaviour). Default 0 keeps backward-compat for any config
    # that predates this knob.
    vix_refresh_minutes: int = Field(ge=0, default=0)

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
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    paper_trading: PaperTradingConfig = Field(default_factory=PaperTradingConfig)
    shadow_sl: ShadowSlConfig = Field(default_factory=ShadowSlConfig)

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
