"""Phase 5 orchestrator — live alert-only scan loop.

One pass per closed 5-min candle: fetch spot/option data, run C0–C4,
log every scan to ``signals.jsonl``, and on a 5/5 pass fire a Telegram
alert (after logging the alert to ``alerts.jsonl`` for durability).

No order placement code lives here — that is Phase 8.

Critical rules (see docs/phases/PHASE_5.md):
  - Alert-only: never places orders.
  - JSONL writes ALWAYS happen before the Telegram send.
  - Scan loop fires exactly once per closed 5-min candle (candle_key
    dedup pattern), even if a scan takes 45s.
  - Bot refuses to start if active broker's token date is not today (IST).
  - Hard 3:00 PM square-off cannot be disabled (only soft + last_entry
    times are configurable).
  - All exceptions in the main loop are caught and Telegrammed.
"""

from __future__ import annotations

import json
import os
import sys
import time as time_mod
import traceback
from dataclasses import dataclass
from datetime import date as date_cls, datetime, time as dt_time
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"

from src.alerts.signal_logger import SignalLogger
from src.alerts.telegram_bot import TelegramAlerter
from src.conditions.all_conditions import check_all_conditions
from src.config_loader import load_config, load_secrets
from src.dashboard.remarks import generate_remark_and_tags, telegram_short_remark
from src.data.expiry_resolver import get_next_expiry, is_expiry_day
from src.data.feed_factory import connect_feed
from src.data.strike_selector import get_alert_strikes
from src.indicators.calculator import get_latest_snapshot
from src.indicators.vwap import compute_session_vwap
from src.risk.lot_sizing import compute_lots
from src.risk.profit_targets import compute_tps
from src.risk.stop_loss import compute_sl_method1, compute_sl_method2
from src.risk.vix_regime import classify_vix
from src.state.state_manager import StateManager

IST = ZoneInfo("Asia/Kolkata")

# Hard 3:00 PM square-off is a strategy invariant (Section 12).
HARD_SQUAREOFF_TIME = dt_time(15, 0)
# Market closes 15:30 IST — bot exits at that wall-clock.
MARKET_CLOSE_TIME = dt_time(15, 30)


class MarketStatus(Enum):
    UNKNOWN = "unknown"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"
    PRE_OPEN = "pre_open"
    OPEN = "open"


@dataclass
class MarketStatusResult:
    status: MarketStatus
    reason: str
    today_candle_count: int
    latest_candle_date: str | None
    checked_at: str


class Orchestrator:
    """Glue layer that runs Phase 5: scan -> log -> alert.

    Construct, then call ``run_forever()`` from ``main()``. The class is
    designed to be friendly to tests too: every external dependency is
    a private attribute set in ``setup()`` so tests can construct an
    instance, swap them out, and call individual methods directly.
    """

    def __init__(self) -> None:
        load_secrets(SECRETS_PATH)
        self.config = load_config(CONFIG_PATH)
        self.feed = None
        self.telegram: TelegramAlerter | None = None
        self.signal_logger: SignalLogger | None = None
        self.state: StateManager | None = None
        self.broker_name: str | None = None
        self.session_vix: float | None = None
        self.session_vix_info = None
        self.is_gap_day: bool = False
        self.gap_info: dict = {}
        self.gap_log_path: Path = PROJECT_ROOT / "logs" / "gap_log.jsonl"
        self.market_status: MarketStatusResult | None = None
        self.holiday_abort: bool = False
        self.nifty_lot: int = 0
        self.banknifty_lot: int = 0
        self.nifty_expiry = None
        self.banknifty_expiry = None
        # In-memory counters — EOD reads these (never re-walks JSONL).
        self.session_scan_count = 0
        self.session_alert_count = 0
        self.session_nifty_alerts = 0
        self.session_bn_alerts = 0
        # Phase 5.2: 15:35 auto-trigger guard (set once per session).
        self.dashboard_synced = False

    # =====================================================================
    # Setup
    # =====================================================================

    def setup(self) -> None:
        """Pre-market setup. Runs once at bot startup."""
        log_file = PROJECT_ROOT / "logs" / "bot.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(log_file, rotation="10 MB", level=self.config.logging.log_level)

        # 1. Connect feed.
        self.feed = connect_feed(self.config)
        self.broker_name = self.feed.get_broker_name()
        logger.info(f"Feed connected: {self.broker_name}")

        # 2. Refuse to start on stale token.
        self._verify_token_freshness()

        # 3. Verify lot sizes match config (warn but trust broker).
        nifty_lot = self.feed.get_lot_size("NIFTY")
        bn_lot = self.feed.get_lot_size("BANKNIFTY")
        if nifty_lot != self.config.instruments.nifty_lot_size:
            logger.warning(
                f"NIFTY lot mismatch: config={self.config.instruments.nifty_lot_size}, "
                f"broker={nifty_lot}. USING BROKER VALUE."
            )
        if bn_lot != self.config.instruments.banknifty_lot_size:
            logger.warning(
                f"BANKNIFTY lot mismatch: config={self.config.instruments.banknifty_lot_size}, "
                f"broker={bn_lot}. USING BROKER VALUE."
            )
        self.nifty_lot = nifty_lot
        self.banknifty_lot = bn_lot

        # 4. Lock VIX for the session.
        self.session_vix = self.feed.get_india_vix()
        self.session_vix_info = classify_vix(self.session_vix)
        logger.info(
            f"Session VIX: {self.session_vix:.2f} → "
            f"{self.session_vix_info.regime.value} "
            f"({self.session_vix_info.method1_multiplier}× multiplier)"
        )

        # 5a. Detect market status (weekend / holiday / pre-open / open).
        #     Uses candle data as the single source of truth — no hardcoded
        #     calendars. On WEEKEND/HOLIDAY we set holiday_abort and skip
        #     gap detection entirely (no point computing gap on a non-trading
        #     day; today_n=0 would also pollute gap_log.jsonl).
        self.market_status = self._check_market_status()
        status = self.market_status.status

        if status in (MarketStatus.WEEKEND, MarketStatus.HOLIDAY):
            logger.warning(
                f"{status.value.upper()} — {self.market_status.reason}. "
                "All scans suppressed. Bot will idle until 15:30 / Ctrl+C."
            )
            self.holiday_abort = True
        elif status == MarketStatus.PRE_OPEN:
            logger.info("Pre-open — will recheck market status each polling loop.")
        else:
            logger.info(f"Market status: {status.value}")

        # 5b. Detect gap day (must run after 09:15 — open candle exists).
        #     Skipped on holidays to keep gap_log.jsonl clean.
        if self.holiday_abort:
            self.is_gap_day = False
            self.gap_info = {
                "decision": "SKIPPED_HOLIDAY",
                "reason": self.market_status.reason,
            }
        else:
            self.is_gap_day, self.gap_info = self._detect_gap_day()
            if self.is_gap_day:
                logger.warning(
                    f"GAP DAY ACTIVE — no entries before "
                    f"{self.config.time_rules.gap_day_start_time}"
                )
            elif self.gap_info.get("any_triggered"):
                logger.info(
                    "Gap threshold breached but gap_day_enabled=false — "
                    "normal 9:45 start will be used."
                )

        # 6. Initialize alerters and state.
        self.telegram = TelegramAlerter()
        self.signal_logger = SignalLogger()
        self.state = StateManager()
        self.state.load_state()

        # 7. Resolve expiries for the session.
        self.nifty_expiry = get_next_expiry(self.feed, "NIFTY")
        self.banknifty_expiry = get_next_expiry(self.feed, "BANKNIFTY")
        logger.info(f"Today's NIFTY expiry: {self.nifty_expiry}")
        logger.info(f"Today's BankNifty expiry: {self.banknifty_expiry}")

        # 8. Send startup Telegram.
        if self.config.telegram.send_startup_alert:
            self.telegram.send_startup(
                {
                    "broker": self.broker_name,
                    "alert_mode": self.config.mode.alert_mode,
                    "order_place_mode": self.config.mode.order_place_mode,
                    "paper_trade_mode": self.config.mode.paper_trade_mode,
                    "instruments": self._enabled_instruments_str(),
                    "vix": self.session_vix,
                    "vix_regime": self.session_vix_info.regime.value,
                    "nifty_lot": self.nifty_lot,
                    "banknifty_lot": self.banknifty_lot,
                    "is_gap_day": self.is_gap_day,
                    "gap_info": self.gap_info,
                    "market_status": self.market_status.status.value,
                }
            )

    def _verify_token_freshness(self) -> None:
        """Refuse to start if active broker's token date is not today (IST)."""
        today_str = datetime.now(IST).date().isoformat()
        if self.broker_name == "kite":
            token_date = os.getenv("KITE_TOKEN_DATE")
            if token_date != today_str:
                raise RuntimeError(
                    f"Kite access token is stale "
                    f"(KITE_TOKEN_DATE={token_date}, today={today_str}). "
                    f"Run: python scripts/refresh_token_kite.py"
                )
        elif self.broker_name == "upstox":
            token_date = os.getenv("UPSTOX_TOKEN_DATE")
            if not token_date:
                raise RuntimeError(
                    "UPSTOX_TOKEN_DATE missing in secrets.env. "
                    "Run: python scripts/refresh_token_upstox.py"
                )
            try:
                token_d = date_cls.fromisoformat(token_date)
            except ValueError:
                raise RuntimeError(
                    f"UPSTOX_TOKEN_DATE format invalid: {token_date}"
                )
            age_days = (datetime.now(IST).date() - token_d).days
            if age_days > 350:
                logger.warning(
                    f"Upstox token is {age_days} days old. "
                    "Refresh soon to avoid expiry."
                )
            if age_days > 365:
                raise RuntimeError(
                    f"Upstox token is {age_days} days old (>365). "
                    "Refresh required: scripts/refresh_token_upstox.py"
                )
        logger.info(f"Token freshness OK for {self.broker_name}")

    def _detect_gap_day(self) -> tuple[bool, dict]:
        """Compute per-symbol gap % vs previous close.

        Returns:
            (is_gap_day, gap_info)

            - is_gap_day: True only if threshold breached AND
              gap_day_enabled is True. When gap_day_enabled is False,
              always returns False regardless of gap size (but math is
              still computed and logged).
            - gap_info: dict with enabled, threshold_pct, direction,
              per_symbol math, any_triggered flag, and final decision.
        """
        enabled = self.config.time_rules.gap_day_enabled
        threshold = float(self.config.time_rules.gap_day_threshold_pct)
        direction = self.config.time_rules.gap_day_direction.lower()

        gap_info: dict = {
            "enabled": enabled,
            "threshold_pct": threshold,
            "direction": direction,
            "per_symbol": {},
            "any_triggered": False,
            "decision": "NORMAL",
            "timestamp_ist": datetime.now(IST).isoformat(),
        }

        today_d = datetime.now(IST).date()
        any_triggered = False

        for symbol in ("NIFTY", "BANKNIFTY"):
            sym_info: dict = {
                "open": None,
                "prev_close": None,
                "gap_pct": None,
                "triggers": False,
                "error": None,
            }
            try:
                # 600 candles ≈ 7 trading days — enough so that a mid-session
                # bot start still sees prev day's close even if today's
                # session contains all the recent candles.
                candles = self._get_spot_candles(symbol, lookback_candles=600)
                if candles is None or len(candles) < 2:
                    sym_info["error"] = (
                        f"insufficient candle data: total_n={0 if candles is None else len(candles)}"
                    )
                    logger.warning(
                        f"Gap detection: {symbol} has fewer than 2 candles "
                        f"(got {0 if candles is None else len(candles)}). "
                        "Cannot compute gap."
                    )
                    gap_info["per_symbol"][symbol] = sym_info
                    continue

                ts_dates = pd.to_datetime(candles["timestamp"]).dt.date
                today_candles = candles[ts_dates == today_d]
                prev_candles = candles[ts_dates < today_d]
                if len(today_candles) == 0 or len(prev_candles) == 0:
                    ts_min = candles["timestamp"].min()
                    ts_max = candles["timestamp"].max()
                    sym_info["error"] = (
                        f"insufficient_data: today_n={len(today_candles)}, "
                        f"prev_n={len(prev_candles)}"
                    )
                    logger.warning(
                        f"Gap detection: {symbol} has {len(today_candles)} today candles, "
                        f"{len(prev_candles)} prev-day candles. "
                        f"Date range: {ts_min} to {ts_max}"
                    )
                    gap_info["per_symbol"][symbol] = sym_info
                    continue

                today_open = float(today_candles["open"].iloc[0])
                prev_close = float(prev_candles["close"].iloc[-1])
                gap_pct = (today_open - prev_close) / prev_close * 100.0

                if direction == "both":
                    triggers = abs(gap_pct) >= threshold
                elif direction == "up":
                    triggers = gap_pct >= threshold
                elif direction == "down":
                    triggers = gap_pct <= -threshold
                else:
                    logger.warning(
                        f"Unknown gap_day_direction: {direction}. "
                        "Defaulting to 'both'."
                    )
                    triggers = abs(gap_pct) >= threshold

                sym_info.update({
                    "open": today_open,
                    "prev_close": prev_close,
                    "gap_pct": round(gap_pct, 4),
                    "triggers": triggers,
                })
                if triggers:
                    any_triggered = True
            except Exception as e:
                sym_info["error"] = str(e)
                logger.warning(f"Gap detection error for {symbol}: {e}")

            gap_info["per_symbol"][symbol] = sym_info

        gap_info["any_triggered"] = any_triggered

        # Phase 5.2: directional labels. The per-symbol ``triggers`` flag
        # already honours ``direction`` ("both" / "up" / "down"), so we
        # use *that* to gate which side counts — a -1.2% gap with
        # direction="up" leaves triggers=False and produces NORMAL.
        any_up = any(
            info.get("triggers")
            and (info.get("gap_pct") or 0.0) >= threshold
            for info in gap_info["per_symbol"].values()
        )
        any_down = any(
            info.get("triggers")
            and (info.get("gap_pct") or 0.0) <= -threshold
            for info in gap_info["per_symbol"].values()
        )

        if any_up and enabled:
            gap_info["decision"] = "GAP_UP"
        elif any_down and enabled:
            gap_info["decision"] = "GAP_DOWN"
        elif any_up:
            gap_info["decision"] = "GAP_UP_DISABLED"
        elif any_down:
            gap_info["decision"] = "GAP_DOWN_DISABLED"
        else:
            gap_info["decision"] = "NORMAL"
        is_gap_day = gap_info["decision"] in ("GAP_UP", "GAP_DOWN")

        # Always log gap math, regardless of toggle state.
        self._log_gap(gap_info)

        return is_gap_day, gap_info

    def _log_gap(self, gap_info: dict) -> None:
        """Append gap math to ``logs/gap_log.jsonl`` (one line per startup)."""
        path = self.gap_log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(gap_info) + "\n")
            per_sym = gap_info.get("per_symbol", {})
            logger.info(
                f"Gap decision: {gap_info['decision']} | "
                f"NIFTY {per_sym.get('NIFTY', {}).get('gap_pct')}% | "
                f"BANKNIFTY {per_sym.get('BANKNIFTY', {}).get('gap_pct')}%"
            )
        except Exception as e:
            logger.error(f"Failed to write gap_log.jsonl: {e}")

    def _check_market_status(self) -> MarketStatusResult:
        """Decide whether NSE is open today, using candle data as primary truth.

        Decision tree (first match wins):
          A. Weekend (Sat/Sun) → WEEKEND (no API call)
          B. Weekday before 09:15 → PRE_OPEN (no API call)
          C. Candle check (API):
             - today_count > 0           → OPEN
             - today_count == 0, ≥ 09:30 → HOLIDAY (candidate)
             - today_count == 0, < 09:30 → PRE_OPEN (opening window)
          D. Any exception in candle fetch → UNKNOWN (fail-open)

        Second-source confirmation: when the candle check yields HOLIDAY,
        we cross-check with India VIX's last-trade timestamp. A fresh VIX
        tick means market is live and the candle fetch glitched — we
        downgrade to UNKNOWN (fail-open) so scans resume.

        UNKNOWN never aborts scans — it just marks the check as inconclusive
        so run_forever() will retry. Never raises.
        """
        now = datetime.now(IST)
        today_d = now.date()
        checked_at = now.isoformat()

        status: MarketStatus
        reason: str
        today_count: int = 0
        latest_date: str | None = None

        if now.weekday() >= 5:
            status = MarketStatus.WEEKEND
            reason = f"weekday={now.strftime('%A')}"
            logger.info(f"Market status: WEEKEND ({reason}) — no candle fetch.")
        elif now.time() < dt_time(9, 15):
            status = MarketStatus.PRE_OPEN
            reason = f"time={now.strftime('%H:%M')} before 09:15"
            logger.info(f"Market status: PRE_OPEN ({reason}).")
        else:
            try:
                candles = self._get_spot_candles("NIFTY", lookback_candles=10)
                if candles is None or len(candles) == 0:
                    status = MarketStatus.UNKNOWN
                    reason = "candle fetch returned no data"
                    logger.warning(f"Market status: UNKNOWN ({reason}).")
                else:
                    ts_dates = pd.to_datetime(candles["timestamp"]).dt.date
                    today_count = int((ts_dates == today_d).sum())
                    latest_date = str(ts_dates.max()) if len(candles) else None

                    if today_count > 0:
                        status = MarketStatus.OPEN
                        reason = f"today_n={today_count}, latest={latest_date}"
                        logger.info(f"Market status: OPEN ({reason}).")
                    elif now.time() >= dt_time(9, 30):
                        status = MarketStatus.HOLIDAY
                        reason = (
                            f"today_n=0 at {now.strftime('%H:%M')} (>=09:30); "
                            f"latest candle date={latest_date}"
                        )
                        logger.info(f"Market status: HOLIDAY ({reason}).")
                    else:
                        status = MarketStatus.PRE_OPEN
                        reason = (
                            f"today_n=0 at {now.strftime('%H:%M')} (<09:30); "
                            "opening window, will recheck"
                        )
                        logger.info(f"Market status: PRE_OPEN ({reason}).")
            except Exception as e:
                status = MarketStatus.UNKNOWN
                reason = f"candle fetch error: {e}"
                logger.warning(f"Market status: UNKNOWN ({reason}).")

        # Second-source check: confirm via VIX timestamp ONLY when the
        # candle check yielded HOLIDAY. All other statuses pass through
        # untouched so the second check stays cheap on normal trading days.
        if status == MarketStatus.HOLIDAY:
            confirmed, vix_reason = self._confirm_holiday_via_vix(now)
            if not confirmed:
                logger.warning(
                    f"Candle check said HOLIDAY but VIX is fresh ({vix_reason}). "
                    "Likely a candle-fetch glitch. Falling back to UNKNOWN — "
                    "scans will proceed."
                )
                status = MarketStatus.UNKNOWN
                reason = f"Candles stale but VIX fresh: {vix_reason}"
            else:
                logger.info(f"HOLIDAY confirmed by VIX check: {vix_reason}")
                reason = f"{reason} | VIX confirms: {vix_reason}"

        return MarketStatusResult(
            status=status,
            reason=reason,
            today_candle_count=today_count,
            latest_candle_date=latest_date,
            checked_at=checked_at,
        )

    def _confirm_holiday_via_vix(self, now: datetime) -> tuple[bool, str]:
        """Second-source holiday confirmation using India VIX timestamp.

        Returns ``(is_holiday_confirmed, reason)``.

        - VIX timestamp < 10 minutes old → market is live → NOT holiday.
        - VIX timestamp >= 10 minutes old → confirms holiday.
        - VIX fetch fails or timestamp is None → trust the first check
          (returns ``(True, ...)``).
        """
        try:
            vix_value, vix_ts_iso = self.feed.get_india_vix_with_timestamp()
        except Exception as e:
            logger.warning(f"VIX confirmation check errored: {e}")
            return True, f"VIX check errored, trusting candle check: {e}"

        if vix_ts_iso is None:
            return True, "VIX timestamp unavailable, trusting candle check"

        try:
            vix_ts = datetime.fromisoformat(vix_ts_iso)
            if vix_ts.tzinfo is None:
                vix_ts = vix_ts.replace(tzinfo=IST)
            age_minutes = (now - vix_ts).total_seconds() / 60.0
        except Exception as e:
            return True, f"VIX timestamp parse failed: {e}"

        if age_minutes < 10:
            return False, (
                f"VIX updated {age_minutes:.1f} min ago "
                f"(value={vix_value:.2f}) — market is live"
            )
        return True, (
            f"VIX last updated {age_minutes:.1f} min ago "
            f"(value={vix_value:.2f}) — confirms holiday"
        )

    def _enabled_instruments_str(self) -> str:
        out = []
        if self.config.instruments.nifty_enabled:
            out.append("NIFTY")
        if self.config.instruments.banknifty_enabled:
            out.append("BANKNIFTY")
        return ", ".join(out) if out else "NONE"

    # =====================================================================
    # Time helpers
    # =====================================================================

    def _is_market_hours(self, now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        return dt_time(9, 15) <= now.time() <= MARKET_CLOSE_TIME

    def _is_scan_time(self, now: datetime) -> bool:
        """Scan window: normal_start (or gap_day_start) to last_entry_time."""
        if not self._is_market_hours(now):
            return False
        if self.is_gap_day:
            start = dt_time.fromisoformat(self.config.time_rules.gap_day_start_time)
        else:
            start = dt_time.fromisoformat(self.config.time_rules.normal_start_time)
        last = dt_time.fromisoformat(self.config.time_rules.last_entry_time)
        return start <= now.time() <= last

    def _is_hard_squareoff_time(self, now: datetime) -> bool:
        """Hard 3:00 PM check — INVARIANT, not config-driven."""
        return now.time() >= HARD_SQUAREOFF_TIME

    # =====================================================================
    # Scan loop
    # =====================================================================

    def scan_once(self) -> None:
        """One scan pass — runs after each 5-min candle closes."""
        if self.holiday_abort:
            status_val = (
                self.market_status.status.value if self.market_status else "unknown"
            )
            logger.debug(f"Scan suppressed — status={status_val}")
            return

        now = datetime.now(IST)

        # Hot-reload config every scan (allows runtime tuning of thresholds).
        # Broker / order_place_mode changes still require a full restart.
        self.config = load_config(CONFIG_PATH)

        if not self._is_scan_time(now):
            logger.debug(f"Not scan time: {now.time()}")
            return

        if self.state._state.circuit_breaker_triggered:
            logger.info(
                f"Circuit breaker active: {self.state._state.circuit_breaker_reason}"
            )
            return

        if (
            self.config.circuit_breakers.daily_sl_count_breaker
            and self.state.get_daily_sl_count()
            >= self.config.circuit_breakers.max_sl_per_day
        ):
            self._trigger_circuit_breaker(
                f"Daily SL count reached {self.state.get_daily_sl_count()}"
            )
            return

        if (
            self.config.circuit_breakers.daily_loss_breaker
            and self.state.get_daily_loss()
            >= self.config.circuit_breakers.max_loss_per_day_rupees
        ):
            self._trigger_circuit_breaker(
                f"Daily loss ₹{self.state.get_daily_loss():,.2f} >= cap"
            )
            return

        symbols: list[tuple[str, Any, int]] = []
        if self.config.instruments.nifty_enabled:
            symbols.append(("NIFTY", self.nifty_expiry, self.nifty_lot))
        if self.config.instruments.banknifty_enabled:
            symbols.append(("BANKNIFTY", self.banknifty_expiry, self.banknifty_lot))

        for symbol, expiry, lot_size in symbols:
            self._scan_symbol(symbol, expiry, lot_size, now)

    def _scan_symbol(
        self, symbol: str, expiry: Any, lot_size: int, now: datetime
    ) -> None:
        """Scan one symbol — both CE and PE direction."""
        try:
            spot_candles = self._get_spot_candles(symbol)
            spot_vwap = float(compute_session_vwap(spot_candles).iloc[-1])
            spot_close = float(spot_candles["close"].iloc[-1])
        except Exception as e:
            logger.error(f"Failed to fetch spot data for {symbol}: {e}")
            return

        for option_type in ("CE", "PE"):
            # C0 fast-fail — saves an option chain fetch when spot/VWAP disagree.
            if option_type == "CE" and spot_close <= spot_vwap:
                self._log_rejection(
                    symbol, None, option_type, "C0",
                    f"spot {spot_close:.2f} not above VWAP {spot_vwap:.2f}", now,
                )
                continue
            if option_type == "PE" and spot_close >= spot_vwap:
                self._log_rejection(
                    symbol, None, option_type, "C0",
                    f"spot {spot_close:.2f} not below VWAP {spot_vwap:.2f}", now,
                )
                continue

            try:
                strikes = get_alert_strikes(
                    self.feed, symbol, spot_close, option_type,
                    str(expiry), self.config,
                )
            except Exception as e:
                logger.error(
                    f"Strike selection failed for {symbol} {option_type}: {e}"
                )
                continue

            for strike_choice in strikes:
                self._scan_strike(
                    symbol, strike_choice, option_type, expiry,
                    lot_size, spot_close, spot_vwap, now,
                )

    def _scan_strike(
        self,
        symbol: str,
        strike_choice,
        option_type: str,
        expiry: Any,
        lot_size: int,
        spot_close: float,
        spot_vwap: float,
        now: datetime,
    ) -> None:
        """Run all 5 conditions on one strike. If 5/5, fire alert."""
        allowed, reason = self.state.can_re_enter(
            self.config, symbol, strike_choice.strike, option_type
        )
        if not allowed:
            self._log_rejection(
                symbol, strike_choice.strike, option_type,
                "RE_ENTRY_BLOCKED", reason, now,
            )
            return

        try:
            df = self.feed.get_5min_candles(strike_choice.instrument_key, 100)
            snapshot = get_latest_snapshot(df)
        except (ValueError, RuntimeError) as e:
            err_msg = str(e)
            if "insufficient" in err_msg.lower():
                # Technical data issue — NOT a strategy rejection. Keeps
                # rejection analytics clean on mid-session bot starts where
                # RSI MA hasn't had time to warm up.
                logger.warning(
                    f"Data insufficient for "
                    f"{symbol} {strike_choice.strike}{option_type}: {err_msg}"
                )
                self._log_data_issue(
                    symbol, strike_choice.strike, option_type,
                    "INSUFFICIENT_LOOKBACK", err_msg, now,
                )
                return
            logger.error(
                f"Indicator computation failed: "
                f"{symbol} {strike_choice.strike}{option_type}: {e}"
            )
            return
        except Exception as e:
            logger.error(
                f"Indicator computation failed: "
                f"{symbol} {strike_choice.strike}{option_type}: {e}"
            )
            return

        result = check_all_conditions(
            option_snapshot=snapshot,
            spot_close=spot_close,
            spot_vwap=spot_vwap,
            option_type=option_type,
            config=self.config,
        )

        self.session_scan_count += 1

        signal_record = {
            "timestamp_ist": now.isoformat(),
            "event_type": "scan",
            "symbol": symbol,
            "strike": strike_choice.strike,
            "relation": strike_choice.relation,
            "option_type": option_type,
            "expiry": str(expiry),
            "trading_symbol": strike_choice.trading_symbol,
            "spot_price": spot_close,
            "spot_vwap": spot_vwap,
            "option_close": snapshot.close,
            "option_vwap": snapshot.vwap,
            "rsi": snapshot.rsi,
            "rsi_ma": snapshot.rsi_ma,
            "oi": snapshot.oi,
            "oi_ma": snapshot.oi_ma,
            "volume": snapshot.volume,
            "volume_ma": snapshot.volume_ma,
            "is_green": snapshot.is_green,
            "vix": self.session_vix,
            "vix_regime": self.session_vix_info.regime.value,
            "conditions_passed": result.passed_conditions(),
            "conditions_failed": result.failed_conditions(),
            "all_passed": result.all_passed,
            "summary": result.short_summary(),
            "reasons": {r.name: r.reason for r in result.results},
            # Phase 5.2: option distance above its own VWAP at this candle.
            "opt_above_vwap_pct": float(result.opt_above_vwap_pct),
        }
        self.signal_logger.log_signal(signal_record)

        # Phase 5.2: if the only failing condition is C1 because the option
        # sits in the extended zone (between c1_max_distance_pct and
        # c1_extended_zone_max_pct above VWAP), log a "would_alert_extended"
        # event so we can study these signals later. We do NOT fire alerts.
        self._maybe_log_extended_zone(signal_record, result)

        if not result.all_passed:
            return

        self._fire_alert(
            symbol, strike_choice, option_type, expiry,
            lot_size, snapshot, signal_record, now,
        )

    def _maybe_log_extended_zone(self, signal_record: dict, result) -> None:
        """Phase 5.2: capture 4/5 scans where C1's late-entry filter is the
        only blocker AND the option is within the extended zone window.
        """
        cfg = self.config
        try:
            log_enabled = cfg.logging.log_extended_zone
            zone_enabled = cfg.conditions.c1_extended_zone_enabled
            max_pct = cfg.conditions.c1_max_distance_pct
            ext_max = cfg.conditions.c1_extended_zone_max_pct
        except AttributeError:
            return

        if not (log_enabled and zone_enabled):
            return
        if result.all_passed:
            return
        if result.failed_conditions() != ["C1"]:
            return

        pct = float(signal_record.get("opt_above_vwap_pct") or 0.0)
        if not (max_pct < pct <= ext_max):
            return

        extended = dict(signal_record)
        extended["event_type"] = "would_alert_extended"
        self.signal_logger.log_signal(extended)

    def _fire_alert(
        self,
        symbol: str,
        strike_choice,
        option_type: str,
        expiry: Any,
        lot_size: int,
        snapshot,
        signal_record: dict,
        now: datetime,
    ) -> None:
        """Compute SL/TP/lots, log to alerts.jsonl, then send Telegram."""
        try:
            entry = snapshot.close
            is_expiry = is_expiry_day(self.feed, symbol, now.date())

            if self.config.stop_loss.method == 1:
                sl_result = compute_sl_method1(
                    vwap_at_entry=snapshot.vwap,
                    option_price=entry,
                    symbol=symbol,
                    is_expiry_day=is_expiry,
                    vix_info=self.session_vix_info,
                    use_vix_multiplier=self.config.stop_loss.use_vix_multiplier,
                )
            else:
                sl_result = compute_sl_method2(
                    vwap_at_entry=snapshot.vwap,
                    is_expiry_day=is_expiry,
                    vix_info=self.session_vix_info,
                )

            tp_result = compute_tps(entry, sl_result.sl_price, is_expiry, self.config)
            lot_result = compute_lots(
                entry, sl_result.sl_price, symbol, lot_size, self.config
            )

            alert_data = {
                **signal_record,
                "event_type": "alert",
                "entry": entry,
                "sl": sl_result.sl_price,
                "sl_method": sl_result.method,
                "tp1": tp_result.tp1,
                "tp2": tp_result.tp2,
                "tp1_r": tp_result.risk_to_tp1_ratio,
                "tp2_r": tp_result.risk_to_tp2_ratio,
                "risk_per_unit": lot_result.risk_per_unit,
                "lots": lot_result.lots,
                "total_risk": lot_result.total_risk_rupees,
                "lot_size": lot_size,
                "day_type": "Expiry" if is_expiry else "Normal",
                "vix_multiplier": self.session_vix_info.method1_multiplier,
                "spot": signal_record["spot_price"],
                "spot_position": (
                    "Above VWAP ✓" if option_type == "CE" else "Below VWAP ✓"
                ),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M"),
                "strike": strike_choice.strike,
                "relation": strike_choice.relation,
            }

            # Phase 5.2: generate the human-readable remark and structured
            # ML tags. The Telegram short form is derived from the remark.
            try:
                context = {
                    "time_hhmm": now.strftime("%H:%M"),
                    "vix_regime": self.session_vix_info.regime.value,
                    "is_expiry_day": is_expiry,
                    "daily_sl_count": self.state.get_daily_sl_count(),
                    "daily_alert_count": self.session_alert_count,
                }
                snapshot_dict = {
                    "option_close": snapshot.close,
                    "option_vwap": snapshot.vwap,
                    "rsi": snapshot.rsi,
                    "rsi_ma": snapshot.rsi_ma,
                    "oi": snapshot.oi,
                    "oi_ma": snapshot.oi_ma,
                    "volume": snapshot.volume,
                    "volume_ma": snapshot.volume_ma,
                    "opt_above_vwap_pct": signal_record.get(
                        "opt_above_vwap_pct", 0.0
                    ),
                }
                bot_remark, bot_tags = generate_remark_and_tags(
                    snapshot_dict, context
                )
                alert_data["bot_remark"] = bot_remark
                alert_data["bot_tags"] = bot_tags
                alert_data["telegram_short_remark"] = telegram_short_remark(bot_remark)
            except Exception as e:
                logger.warning(f"Bot remark generation failed: {e}")
                alert_data.setdefault("bot_remark", "")
                alert_data.setdefault("bot_tags", "")
                alert_data.setdefault("telegram_short_remark", "")

            # Durability first: JSONL line lands on disk before Telegram fires.
            self.signal_logger.log_alert(alert_data)

            self.session_alert_count += 1
            if symbol == "NIFTY":
                self.session_nifty_alerts += 1
            elif symbol == "BANKNIFTY":
                self.session_bn_alerts += 1

            if self.config.telegram.send_signal_alerts:
                self.telegram.send_signal(alert_data)
                logger.info(
                    f"ALERT FIRED: {symbol} {strike_choice.strike}{option_type}"
                )

        except Exception as e:
            logger.error(f"Alert generation failed: {e}")
            logger.exception(e)

    def _log_rejection(
        self,
        symbol: str,
        strike: int | None,
        option_type: str,
        blocker: str,
        reason: str,
        now: datetime,
    ) -> None:
        """Log silent rejections (toggle: config.logging.log_every_signal_check)."""
        if not self.config.logging.log_every_signal_check:
            return
        self.signal_logger.log_rejection(
            {
                "timestamp_ist": now.isoformat(),
                "symbol": symbol,
                "strike": strike,
                "option_type": option_type,
                "rejection_blocker": blocker,
                "rejection_reason": reason,
                "all_passed": False,
            }
        )

    def _log_data_issue(
        self,
        symbol: str,
        strike: int | None,
        option_type: str,
        issue_type: str,
        msg: str,
        now: datetime,
    ) -> None:
        """Record a technical data-availability issue in signals.jsonl.

        These are NOT strategy rejections — they get their own
        ``event_type='data_issue'`` so the Phase 5.2 dashboard can show
        them in a separate bucket without polluting rejection counts.
        """
        if not self.config.logging.log_every_signal_check:
            return
        self.signal_logger.log_signal(
            {
                "timestamp_ist": now.isoformat(),
                "event_type": "data_issue",
                "symbol": symbol,
                "strike": strike,
                "option_type": option_type,
                "issue_type": issue_type,
                "issue_message": msg,
            }
        )

    def _trigger_circuit_breaker(self, reason: str) -> None:
        logger.warning(f"CIRCUIT BREAKER: {reason}")
        self.state.trigger_circuit_breaker(reason)
        if self.config.telegram.send_circuit_breaker_alerts:
            self.telegram.send_circuit_breaker(reason)

    def _get_spot_candles(
        self, symbol: str, lookback_candles: int = 100
    ) -> pd.DataFrame:
        """Fetch spot index 5-min candles. Defaults to ~1.5 days lookback;
        callers like gap detection pass a larger value for multi-day history.
        """
        if self.broker_name == "kite":
            tokens = {"NIFTY": "256265", "BANKNIFTY": "260105"}
            return self.feed.get_5min_candles(tokens[symbol], lookback_candles)
        keys = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank"}
        return self.feed.get_5min_candles(keys[symbol], lookback_candles)

    # =====================================================================
    # End-of-day summary
    # =====================================================================

    def send_eod(self) -> None:
        if not self.config.telegram.send_eod_summary:
            return
        self.telegram.send_eod_summary(self._compute_eod_summary())

    def _run_dashboard_sync_on_exit(self) -> None:
        """Phase 5.2.1: Run dashboard sync when bot exits. Best-effort, idempotent."""
        try:
            auto_trigger = self.config.dashboard.auto_trigger_at_1535
        except AttributeError:
            return
        if not auto_trigger or self.dashboard_synced or datetime.now(IST).weekday() >= 5:
            return
        try:
            logger.info("Bot exiting — running dashboard auto-sync...")
            from src.dashboard import (
                sync_excel_notes_to_parquet,
                sync_jsonl_to_parquet,
                update_dashboard,
            )
            sync_jsonl_to_parquet()
            update_dashboard()
            sync_excel_notes_to_parquet()
            self.dashboard_synced = True
            logger.info("Dashboard auto-sync complete on bot exit")
        except Exception as e:
            logger.exception(f"Dashboard auto-sync on exit failed: {e}")
            try:
                self.telegram.send_exception(
                    f"Dashboard auto-sync failed on exit:\n{e}"
                )
            except Exception:
                pass

    def _compute_eod_summary(self) -> dict:
        """Build EOD summary from in-memory counters (never re-reads JSONL)."""
        today_str = datetime.now(IST).date().isoformat()
        return {
            "date": today_str,
            "total_scans": self.session_scan_count,
            "alerts_fired": self.session_alert_count,
            "nifty_alerts": self.session_nifty_alerts,
            "banknifty_alerts": self.session_bn_alerts,
            "circuit_breaker": (
                "YES" if self.state._state.circuit_breaker_triggered else "NO"
            ),
            "vix_close": self.session_vix,
        }

    # =====================================================================
    # Main loop
    # =====================================================================

    def run_forever(self) -> None:
        """Main loop until 15:30 IST or Ctrl+C."""
        self.setup()
        logger.info("Bot entered main loop")

        eod_sent = False
        last_scan_candle: tuple | None = None
        last_status_check: datetime | None = None
        STATUS_RECHECK_SECONDS = 300

        try:
            while True:
                now = datetime.now(IST)

                if self._is_hard_squareoff_time(now) and not eod_sent:
                    self.send_eod()
                    eod_sent = True
                    logger.info("EOD summary sent. Bot will exit at market close.")

                if now.time() >= MARKET_CLOSE_TIME:
                    logger.info(
                        "Market closed (15:30 IST). Bot exiting, dashboard sync will run."
                    )
                    break

                # Dynamic status re-check: only while still PRE_OPEN/UNKNOWN.
                # Once we land on OPEN, we stop polling (mid-day halts will
                # surface through normal candle-fetch errors). On HOLIDAY we
                # latch holiday_abort and never re-check.
                needs_recheck = (
                    not self.holiday_abort
                    and self.market_status is not None
                    and self.market_status.status
                    in (MarketStatus.PRE_OPEN, MarketStatus.UNKNOWN)
                    and (
                        last_status_check is None
                        or (now - last_status_check).total_seconds()
                        >= STATUS_RECHECK_SECONDS
                    )
                )
                if needs_recheck:
                    self.market_status = self._check_market_status()
                    last_status_check = now
                    if self.market_status.status == MarketStatus.HOLIDAY:
                        self.holiday_abort = True
                        logger.warning(
                            "Status upgraded to HOLIDAY after recheck. "
                            "Suppressing scans."
                        )
                        try:
                            self.telegram.send(
                                f"⛔ NSE HOLIDAY DETECTED at "
                                f"{now.strftime('%H:%M')} — bot was started "
                                "early. All scans suppressed."
                            )
                        except Exception:
                            pass
                    elif self.market_status.status == MarketStatus.OPEN:
                        logger.info(
                            "Status upgraded to OPEN — scan loop is now live."
                        )

                candle_minute = (now.minute // 5) * 5
                candle_key = (now.date(), now.hour, candle_minute)
                seconds_into_candle = (now.minute % 5) * 60 + now.second
                in_trigger_window = 5 <= seconds_into_candle <= 30

                if (
                    in_trigger_window
                    and candle_key != last_scan_candle
                    and self._is_scan_time(now)
                ):
                    try:
                        self.scan_once()
                    except Exception as e:
                        logger.exception(f"Scan failed: {e}")
                        try:
                            self.telegram.send_exception(traceback.format_exc())
                        except Exception:
                            pass
                    # Mark the candle as scanned whether scan_once raised or
                    # not — prevents a retry storm inside the trigger window.
                    last_scan_candle = candle_key

                time_mod.sleep(2)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C)")
        except Exception as e:
            logger.exception("FATAL error in main loop")
            try:
                if self.telegram is not None:
                    self.telegram.send_exception(traceback.format_exc())
            except Exception:
                pass
            sys.exit(1)
        finally:
            # Phase 5.2.1: Auto-sync dashboard on bot exit (clean exit,
            # Ctrl+C, or exception). Runs exactly once per session.
            self._run_dashboard_sync_on_exit()


def main() -> None:
    print("=" * 60)
    print("  SHORT COVER CASCADE — Phase 5 Live Bot")
    print("=" * 60)
    orch = Orchestrator()
    orch.run_forever()


if __name__ == "__main__":
    main()
