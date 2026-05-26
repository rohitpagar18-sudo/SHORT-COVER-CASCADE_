# Phase 5 — Telegram Alerts + Main Orchestrator (Bot Goes Live)

**Goal:** Connect every component built in Phases 0-4 into a running bot.
Every 5 minutes during market hours, the bot scans NIFTY + BANKNIFTY
strikes, checks all 5 conditions, logs everything, and sends Telegram
alerts when a 5/5 signal fires. NO orders placed (alert-only mode).

**Time estimate:** 3 hours code + 1 hour Telegram setup + first live run.

**Output:**
- Telegram integration: signal alerts, EOD summary, startup, exceptions
- Main orchestrator: 5-min candle close loop with full safety logic
- Gap-day detection (>1% open vs prev close → no entry before 10:15)
- Token-date staleness check at startup (refuses to start on stale token)
- signals.jsonl logging — every condition check, even rejections
- alerts.jsonl — only valid 5/5 signals (subset of signals.jsonl)
- check_risk.py input validation (reject entries > ₹2,000)
- CLAUDE.md updated with all Phase 0-4 decisions
- Production-readiness verification on Machine 2

**What Phase 5 does NOT do:**
- No order placement (Phase 8)
- No backtest (Phase 7)
- No paper-trade simulation beyond logging (that's Phase 8)

---

## STEP 1 — Telegram bot setup (Machine 2, ~10 minutes, one-time)

Before any code runs, you need a Telegram bot.

### Create the bot
1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Pick a name (e.g. "Short Cover Cascade Bot") and username ending in `_bot` (e.g. `scc_alerts_bot`)
4. BotFather replies with a **bot token** — looks like `7891234567:AAH...xyz`
5. **Copy the token immediately** — you cannot see it again

### Get your chat ID
1. Search for **@userinfobot** in Telegram
2. Send `/start`
3. It replies with your numeric **chat_id** (e.g. `123456789`)
4. **Copy this number**

### Send the bot a "hello" message first
1. Find your new bot in Telegram search
2. Click Start
3. Send any message (e.g. "hi")

Without this step, the bot can't message you — Telegram blocks unsolicited
contact.

### Fill secrets.env (Machine 2)
```
TELEGRAM_BOT_TOKEN=7891234567:AAH...xyz
TELEGRAM_CHAT_ID=123456789
```

**Test it manually** (10 seconds):
```cmd
curl "https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage?chat_id=<YOUR_CHAT_ID>&text=test"
```
You should receive "test" in Telegram instantly. If not, the bot/chat
setup is wrong — fix before proceeding.

---

## STEP 2 — Paste this prompt into Claude Code (Machine 1)

```cmd
cd C:\trading\short-cover-cascade
claude
```

Paste the entire block below:

````
Read CLAUDE.md fully. Then read docs/ShortCoverCascade_v3_1_FINAL.md
Sections 11 (Order Placement — for the alert format only, no orders yet),
12 (Time Rules — gap day rule is critical), 13 (Re-Entry Rules),
14 (Daily Circuit Breakers), 15 (Blockers), 16 (Entry Execution Flow),
17 (Telegram Alert Format), 18 (Trade Log), 20 (Deployment Phases).

Then read docs/phases/PHASE_5.md fully.

Current phase: Phase 5 — Telegram + Main Orchestrator.

CRITICAL INSTRUCTION: If any file already exists, OVERWRITE it.
Use load_secrets() helper before load_config() in every entry point.

CRITICAL CORRECTNESS RULES:
1. Bot is ALERT-ONLY. NO order placement code in this phase.
   Even paper-trade orders are skipped — those come in Phase 8.
2. Every condition scan (passed or failed) logs to signals.jsonl.
3. Only 5/5 passes log to alerts.jsonl AND fire Telegram.
4. Telegram alert MUST be sent AFTER both JSONL writes — never before.
5. Every JSONL line is a single JSON object with timestamp (IST ISO).
6. State manager (Phase 4) is the single source of truth for all
   re-entry/circuit-breaker decisions.
7. Bot must catch ALL exceptions in the main loop and Telegram the
   trace — never silently die.
8. Hard 3:00 PM square-off cannot be disabled in code (only soft
   square-off and last_entry are configurable).
9. Scan-loop must fire EXACTLY ONCE per closed 5-min candle, even if
   a scan takes 45 seconds. Use the candle_key dedup pattern in TASK 4.
10. Bot REFUSES to start if active broker's token date in secrets.env
    is not today's date (Asia/Kolkata). See TASK 4 setup() step.
11. Gap-day rule MUST be implemented (>1% gap → no entry before 10:15).
    Detect once during setup, store as self.is_gap_day, use in
    _is_scan_time(). See TASK 4.

=========================================================
--- TASK 0: Update CLAUDE.md with Phase 0-4 decisions ---
=========================================================

Add a new section to CLAUDE.md after "Indicator Calculation Standards":

## Strategy Decisions Locked In (Phases 0-4)

These decisions were made during phase-by-phase development. Do NOT
revisit without explicit user approval.

### Strike Selection
- Bot scans 3 strikes per side per scan: ITM + ATM + OTM (one strike each)
- For CE: ITM = ATM - interval, OTM = ATM + interval
- For PE: ITM = ATM + interval, OTM = ATM - interval
- NIFTY strike interval: 50 points
- BankNifty strike interval: 100 points
- config.strike.alert_strikes controls which to ALERT on (default all 3 ON)
- config.strike.order_strikes controls which to AUTO-ORDER on (default ATM only)
- Alert and order are decoupled — alert on more, order on fewer

### Expiry Selection
- Expiries are NEVER hardcoded by day-of-week
- Always pulled from broker instrument dump (Kite or Upstox)
- For NIFTY: nearest Tuesday (weekly) is used
- For BankNifty: nearest last-Tuesday-of-month (monthly only) is used
- If SEBI changes expiry rules, broker reflects it next trading day
- src/data/expiry_resolver.py is the single source of truth

### VWAP Computation
- Session-anchored: resets 09:15 IST daily
- Uses hlc3 = (High + Low + Close) / 3 — NOT close-only
- get_5min_candles() ALWAYS fetches from 09:15 IST to now (full session)
- Never windowed — VWAP requires full session for correctness
- Verified against Kite chart on 26 May 2026: bot ₹194.94 vs Kite ₹194.94

### Risk Math
- check_risk.py is for OPTION PREMIUMS only
- Entries above ₹2,000 are rejected (no real option costs this much)
- This prevents passing index spot value (₹24,000) by accident
- Method 1 (point buffer) is default per strategy doc
- Method 2 (percentage) is available via config.stop_loss.method = 2

### Token Refresh Discipline
- Kite: refresh DAILY before 9:15 AM via scripts/refresh_token_kite.py
- Upstox: refresh ANNUALLY (365-day token via Analytics tab)
- Token-date stored in secrets.env (KITE_TOKEN_DATE / UPSTOX_TOKEN_DATE)
- Bot REFUSES to start at setup() if active feed token-date != today IST

### Two-Machine Workflow
- Machine 1: dev, write code, push to git, never has real secrets
- Machine 2: clone, fill real secrets in secrets.env, run live tests
- secrets.env is gitignored — copy via secrets.env.example template

### Scan Loop Cadence
- Bot fires exactly ONE scan per closed 5-min candle
- Trigger window: 5-30 seconds after each :00 / :05 / :10 / ... boundary
- Dedup via (date, hour, candle_minute) tuple — survives long scans
- If a scan takes 45s, next scan still fires correctly on next candle

### Gap-Day Rule
- Detected at setup(): if open_price diverges >1% from prev_close, gap day
- On gap day: no entries before 10:15 AM (vs normal 9:45 AM)
- Toggle: config.time_rules.gap_day_enabled (default ON)
- Reason: VWAP gets dominated by opening candles on gap days

=========================================================
--- TASK 1: Create src/alerts/telegram_bot.py ---
=========================================================

Thin wrapper around python-telegram-bot.

import asyncio
from telegram import Bot
from loguru import logger
import os

class TelegramAlerter:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token or not self.chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing from secrets.env"
            )
        self._bot = Bot(token=self.token)

    def send(self, message: str) -> bool:
        """
        Synchronous wrapper around async telegram send.
        Returns True on success, False on failure (logs error).
        Never raises — Telegram failure must never crash the main loop.
        
        Uses a fresh event loop per call so it remains safe even if
        we later add async routes elsewhere.
        """
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._bot.send_message(
                    chat_id=self.chat_id, text=message, parse_mode=None
                ))
                return True
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_startup(self, config_summary: dict) -> bool:
        msg = self._format_startup(config_summary)
        return self.send(msg)

    def send_signal(self, signal_data: dict) -> bool:
        msg = self._format_signal(signal_data)
        return self.send(msg)

    def send_circuit_breaker(self, reason: str) -> bool:
        msg = (
            "🛑 CIRCUIT BREAKER TRIGGERED\n"
            "─────────────────────────────\n"
            f"Reason: {reason}\n"
            f"Time: {self._now_ist()}\n"
            "No more trades today."
        )
        return self.send(msg)

    def send_eod_summary(self, summary: dict) -> bool:
        msg = self._format_eod(summary)
        return self.send(msg)

    def send_exception(self, trace: str) -> bool:
        msg = (
            "⚠️ BOT EXCEPTION\n"
            "─────────────────────────────\n"
            f"Time: {self._now_ist()}\n"
            f"Trace:\n{trace[:3000]}"  # Telegram message length cap
        )
        return self.send(msg)

    # Private formatters
    def _format_startup(self, c: dict) -> str:
        gap_str = " | GAP DAY (10:15 start)" if c.get("is_gap_day") else ""
        return (
            "🚀 SHORT COVER CASCADE BOT STARTED\n"
            "─────────────────────────────\n"
            f"Time: {self._now_ist()}\n"
            f"Active broker: {c['broker']}\n"
            f"Mode: alert={c['alert_mode']} | order={c['order_place_mode']} | paper={c['paper_trade_mode']}\n"
            f"Instruments: {c['instruments']}{gap_str}\n"
            f"India VIX: {c['vix']:.2f} ({c['vix_regime']})\n"
            f"Lot sizes: NIFTY={c['nifty_lot']}, BankNifty={c['banknifty_lot']}\n"
            "─────────────────────────────"
        )

    def _format_signal(self, s: dict) -> str:
        """
        Format the strategy doc Section 17 alert template.
        """
        return (
            "🚨 SHORT COVER CASCADE SIGNAL\n"
            "─────────────────────────────\n"
            f"Instrument: {s['symbol']} {s['strike']} {s['option_type']}\n"
            f"Strike relation: {s['relation']} (ITM/ATM/OTM)\n"
            f"Expiry: {s['expiry']}\n"
            f"Date: {s['date']} | Time: {s['time']}\n"
            f"Day Type: {s['day_type']}\n"
            f"VIX: {s['vix']:.2f} ({s['vix_regime']}, {s['vix_multiplier']}×)\n"
            f"Spot: {s['spot']:.2f} ({s['spot_position']})\n"
            f"Lot Size: {s['lot_size']}\n"
            "\n"
            f"ENTRY: ₹{s['entry']:.2f} (LIMIT)\n"
            f"SL: ₹{s['sl']:.2f} (Method {s['sl_method']})\n"
            f"TP1: ₹{s['tp1']:.2f} ({s['tp1_r']}R, exit 50%)\n"
            f"TP2: ₹{s['tp2']:.2f} ({s['tp2_r']}R, exit 50%)\n"
            "\n"
            f"Risk per unit: ₹{s['risk_per_unit']:.2f}\n"
            f"Lots: {s['lots']} → Total Risk: ₹{s['total_risk']:,.2f}\n"
            f"({s['lots']} × {s['lot_size']} × ₹{s['risk_per_unit']:.2f})\n"
            "\n"
            f"C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓\n"
            "─────────────────────────────\n"
            "ALERT ONLY — no order placed"
        )

    def _format_eod(self, s: dict) -> str:
        return (
            "📊 END-OF-DAY SUMMARY\n"
            "─────────────────────────────\n"
            f"Date: {s['date']}\n"
            f"Signals scanned: {s['total_scans']}\n"
            f"Alerts fired: {s['alerts_fired']}\n"
            f"Circuit breaker: {s['circuit_breaker']}\n"
            f"By symbol:\n"
            f"  NIFTY: {s['nifty_alerts']} alerts\n"
            f"  BankNifty: {s['banknifty_alerts']} alerts\n"
            f"VIX at close: {s['vix_close']:.2f}\n"
            "─────────────────────────────"
        )

    def _now_ist(self) -> str:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")

=========================================================
--- TASK 2: Create src/alerts/signal_logger.py ---
=========================================================

JSONL writers for signals.jsonl and alerts.jsonl.

IMPORTANT: Every record MUST include "event_type" so EOD summary can
distinguish actual scans from rejection log entries.

from pathlib import Path
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from loguru import logger

IST = ZoneInfo("Asia/Kolkata")

class SignalLogger:
    def __init__(self, signals_path: str = "logs/signals.jsonl",
                 alerts_path: str = "logs/alerts.jsonl"):
        self.signals_path = Path(signals_path)
        self.alerts_path = Path(alerts_path)
        self.signals_path.parent.mkdir(parents=True, exist_ok=True)

    def log_signal(self, record: dict) -> None:
        """
        Append a full snapshot to signals.jsonl — every scan, pass or fail.
        record must include: timestamp_ist, symbol, strike, option_type,
        expiry, conditions_passed (list), conditions_failed (list),
        indicator_values (dict), spot_price, vwap, vix, lot_size,
        event_type ("scan").
        """
        if "event_type" not in record:
            record["event_type"] = "scan"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_rejection(self, record: dict) -> None:
        """
        Append a rejection record — strikes/sides that didn't get to a
        full condition check (C0 fail, re-entry blocked, etc).
        event_type="rejection" so EOD counter can skip these.
        """
        record["event_type"] = "rejection"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_alert(self, record: dict) -> None:
        """
        Append to alerts.jsonl — only valid 5/5 signals that fired
        a Telegram message. Same shape as log_signal but the bot also
        records the computed SL, TP1, TP2, lots.
        """
        record["event_type"] = "alert"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.alerts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        logger.info(f"Alert logged: {record.get('symbol')} {record.get('strike')} {record.get('option_type')}")

=========================================================
--- TASK 3: Create src/alerts/__init__.py ---
=========================================================

from src.alerts.telegram_bot import TelegramAlerter
from src.alerts.signal_logger import SignalLogger

__all__ = ["TelegramAlerter", "SignalLogger"]

=========================================================
--- TASK 4: Create src/main.py (orchestrator) ---
=========================================================

Complete rewrite — this is the live bot loop.

import json
import os
import sys
import time as time_mod
import traceback
from datetime import datetime, time as dt_time, date as date_cls
from zoneinfo import ZoneInfo
from loguru import logger

from src.config_loader import load_config, load_secrets
from src.data.feed_factory import connect_feed
from src.data.expiry_resolver import get_next_expiry, is_expiry_day
from src.data.strike_selector import get_alert_strikes
from src.indicators.calculator import compute_all_indicators, get_latest_snapshot
from src.indicators.vwap import compute_session_vwap
from src.conditions.all_conditions import check_all_conditions
from src.risk.vix_regime import classify_vix
from src.risk.stop_loss import compute_sl_method1, compute_sl_method2
from src.risk.profit_targets import compute_tps
from src.risk.lot_sizing import compute_lots
from src.state.state_manager import StateManager
from src.alerts.telegram_bot import TelegramAlerter
from src.alerts.signal_logger import SignalLogger

IST = ZoneInfo("Asia/Kolkata")


class Orchestrator:
    def __init__(self):
        load_secrets()
        self.config = load_config("config/config.yaml")
        self.feed = None
        self.telegram = None
        self.signal_logger = None
        self.state = None
        self.broker_name = None
        self.session_vix = None
        self.session_vix_info = None
        self.is_gap_day = False
        # In-memory scan counter (so EOD doesn't re-read JSONL)
        self.session_scan_count = 0
        self.session_alert_count = 0
        self.session_nifty_alerts = 0
        self.session_bn_alerts = 0

    def setup(self) -> None:
        """Pre-market setup. Runs once at bot startup."""
        logger.add("logs/bot.log", rotation="10 MB",
                   level=self.config.logging.log_level)
        
        # 1. Connect feed
        self.feed = connect_feed(self.config)
        self.broker_name = self.feed.get_broker_name()
        logger.info(f"Feed connected: {self.broker_name}")

        # 2. Refuse to start on stale token
        self._verify_token_freshness()

        # 3. Verify lot sizes match config
        nifty_lot = self.feed.get_lot_size("NIFTY")
        bn_lot = self.feed.get_lot_size("BANKNIFTY")
        if nifty_lot != self.config.instruments.nifty_lot_size:
            logger.warning(
                f"NIFTY lot mismatch: config={self.config.instruments.nifty_lot_size}, "
                f"broker={nifty_lot}. USING BROKER VALUE."
            )
        # Always use broker value going forward
        self.nifty_lot = nifty_lot
        self.banknifty_lot = bn_lot

        # 4. Lock VIX for the session
        self.session_vix = self.feed.get_india_vix()
        self.session_vix_info = classify_vix(self.session_vix)
        logger.info(
            f"Session VIX: {self.session_vix:.2f} → {self.session_vix_info.regime.value} "
            f"({self.session_vix_info.method1_multiplier}× multiplier)"
        )

        # 5. Detect gap day (must happen AFTER 9:15 — open candle exists)
        self.is_gap_day = self._detect_gap_day()
        if self.is_gap_day:
            logger.warning("GAP DAY detected — no entries before 10:15 AM")

        # 6. Initialize alerters and state
        self.telegram = TelegramAlerter()
        self.signal_logger = SignalLogger()
        self.state = StateManager()
        self.state.load_state()

        # 7. Resolve expiries for the session
        self.nifty_expiry = get_next_expiry(self.feed, "NIFTY")
        self.banknifty_expiry = get_next_expiry(self.feed, "BANKNIFTY")
        logger.info(f"Today's NIFTY expiry: {self.nifty_expiry}")
        logger.info(f"Today's BankNifty expiry: {self.banknifty_expiry}")

        # 8. Send startup Telegram
        if self.config.telegram.send_startup_alert:
            self.telegram.send_startup({
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
            })

    def _verify_token_freshness(self) -> None:
        """
        Refuse to start if active broker's token date in secrets.env
        is not today's date (Asia/Kolkata). Prevents cryptic auth errors
        from forgetting to refresh.
        """
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
            # Upstox tokens are 365-day; warn if older than 350 days
            try:
                token_d = date_cls.fromisoformat(token_date)
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
            except ValueError:
                raise RuntimeError(
                    f"UPSTOX_TOKEN_DATE format invalid: {token_date}"
                )
        logger.info(f"Token freshness OK for {self.broker_name}")

    def _detect_gap_day(self) -> bool:
        """
        Returns True if today's open diverges >1% from previous close
        on either NIFTY or BankNifty.
        Toggle: config.time_rules.gap_day_enabled (default True).
        """
        if not self.config.time_rules.gap_day_enabled:
            return False
        try:
            # Fetch enough candles to include yesterday's last + today's first
            for symbol in ("NIFTY", "BANKNIFTY"):
                candles = self._get_spot_candles(symbol)
                if candles is None or len(candles) < 2:
                    continue
                # Find last candle of previous trading day (its close)
                # and first candle of today (its open).
                today_d = datetime.now(IST).date()
                today_candles = candles[
                    candles.index.map(lambda ts: ts.date() == today_d)
                ]
                prev_candles = candles[
                    candles.index.map(lambda ts: ts.date() < today_d)
                ]
                if len(today_candles) == 0 or len(prev_candles) == 0:
                    continue
                today_open = today_candles["open"].iloc[0]
                prev_close = prev_candles["close"].iloc[-1]
                gap_pct = abs(today_open - prev_close) / prev_close * 100
                logger.info(
                    f"{symbol} gap: open={today_open:.2f} prev_close={prev_close:.2f} "
                    f"({gap_pct:.2f}%)"
                )
                if gap_pct > 1.0:
                    return True
        except Exception as e:
            logger.warning(f"Gap-day detection failed: {e}. Assuming non-gap.")
            return False
        return False

    def _enabled_instruments_str(self) -> str:
        out = []
        if self.config.instruments.nifty_enabled:
            out.append("NIFTY")
        if self.config.instruments.banknifty_enabled:
            out.append("BANKNIFTY")
        return ", ".join(out) if out else "NONE"

    def _is_market_hours(self, now: datetime) -> bool:
        """Returns True if now is between 09:15 and 15:30 IST on a weekday."""
        if now.weekday() >= 5:   # 5=Saturday, 6=Sunday
            return False
        return dt_time(9, 15) <= now.time() <= dt_time(15, 30)

    def _is_scan_time(self, now: datetime) -> bool:
        """
        Returns True if we should scan for entries at this moment.
        Strategy doc: no entry before 9:45 (or 10:15 on gap day),
        no entry after 14:30.
        """
        if not self._is_market_hours(now):
            return False
        if self.is_gap_day:
            start = dt_time.fromisoformat(self.config.time_rules.gap_day_start_time)
        else:
            start = dt_time.fromisoformat(self.config.time_rules.normal_start_time)
        last = dt_time.fromisoformat(self.config.time_rules.last_entry_time)
        return start <= now.time() <= last

    def _is_hard_squareoff_time(self, now: datetime) -> bool:
        hard = dt_time.fromisoformat(self.config.time_rules.hard_squareoff_time)
        return now.time() >= hard

    def scan_once(self) -> None:
        """One scan pass — runs after each 5-min candle closes."""
        now = datetime.now(IST)
        
        # Reload config every scan (allows hot config changes)
        self.config = load_config("config/config.yaml")
        
        if not self._is_scan_time(now):
            logger.debug(f"Not scan time: {now.time()}")
            return

        # Check circuit breakers BEFORE doing any work
        if self.state._state.circuit_breaker_triggered:
            logger.info(f"Circuit breaker active: {self.state._state.circuit_breaker_reason}")
            return

        if self.state.get_daily_sl_count() >= self.config.circuit_breakers.max_sl_per_day:
            self._trigger_circuit_breaker(
                f"Daily SL count reached {self.state.get_daily_sl_count()}"
            )
            return

        if self.state.get_daily_loss() >= self.config.circuit_breakers.max_loss_per_day_rupees:
            self._trigger_circuit_breaker(
                f"Daily loss ₹{self.state.get_daily_loss():,.2f} >= cap"
            )
            return

        # Scan each enabled symbol
        symbols = []
        if self.config.instruments.nifty_enabled:
            symbols.append(("NIFTY", self.nifty_expiry, self.nifty_lot))
        if self.config.instruments.banknifty_enabled:
            symbols.append(("BANKNIFTY", self.banknifty_expiry, self.banknifty_lot))

        for symbol, expiry, lot_size in symbols:
            self._scan_symbol(symbol, expiry, lot_size, now)

    def _scan_symbol(self, symbol: str, expiry, lot_size: int, now: datetime) -> None:
        """Scan one symbol — both CE and PE direction."""
        # 1. Get spot price + spot VWAP
        try:
            spot_candles = self._get_spot_candles(symbol)
            spot_vwap = compute_session_vwap(spot_candles).iloc[-1]
            spot_close = spot_candles["close"].iloc[-1]
        except Exception as e:
            logger.error(f"Failed to fetch spot data for {symbol}: {e}")
            return

        # 2. For each option_type, determine direction and scan strikes
        for option_type in ["CE", "PE"]:
            # C0 check first — fail fast
            if option_type == "CE" and spot_close <= spot_vwap:
                self._log_rejection(symbol, None, option_type, "C0", 
                    f"spot {spot_close:.2f} not above VWAP {spot_vwap:.2f}", now)
                continue
            if option_type == "PE" and spot_close >= spot_vwap:
                self._log_rejection(symbol, None, option_type, "C0",
                    f"spot {spot_close:.2f} not below VWAP {spot_vwap:.2f}", now)
                continue

            # C0 passes — get eligible strikes
            try:
                strikes = get_alert_strikes(
                    self.feed, symbol, spot_close, option_type,
                    str(expiry), self.config
                )
            except Exception as e:
                logger.error(f"Strike selection failed for {symbol} {option_type}: {e}")
                continue

            for strike_choice in strikes:
                self._scan_strike(
                    symbol, strike_choice, option_type, expiry,
                    lot_size, spot_close, spot_vwap, now
                )

    def _scan_strike(self, symbol, strike_choice, option_type, expiry,
                     lot_size, spot_close, spot_vwap, now):
        """Run all 5 conditions on one strike. If 5/5, fire alert."""
        # Re-entry check
        allowed, reason = self.state.can_re_enter(
            self.config, symbol, strike_choice.strike, option_type
        )
        if not allowed:
            self._log_rejection(symbol, strike_choice.strike, option_type,
                "RE_ENTRY_BLOCKED", reason, now)
            return

        # Fetch option candles + compute snapshot
        try:
            df = self.feed.get_5min_candles(strike_choice.instrument_key, 100)
            snapshot = get_latest_snapshot(df)
        except Exception as e:
            logger.error(f"Indicator computation failed: {symbol} {strike_choice.strike}{option_type}: {e}")
            return

        # Run all 5 conditions
        result = check_all_conditions(
            option_snapshot=snapshot,
            spot_close=spot_close,
            spot_vwap=spot_vwap,
            option_type=option_type,
            config=self.config,
        )

        # Increment in-memory scan counter (drives EOD summary)
        self.session_scan_count += 1

        # Log every scan to signals.jsonl (event_type="scan")
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
        }
        self.signal_logger.log_signal(signal_record)

        if not result.all_passed:
            return  # No alert — only logged

        # 5/5 — compute risk and fire alert
        self._fire_alert(symbol, strike_choice, option_type, expiry,
                        lot_size, snapshot, signal_record, now)

    def _fire_alert(self, symbol, strike_choice, option_type, expiry,
                    lot_size, snapshot, signal_record, now):
        """Computes SL/TP/lots and sends Telegram alert."""
        try:
            entry = snapshot.close
            is_expiry = is_expiry_day(self.feed, symbol, now.date())
            
            # Compute SL based on configured method
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
            lot_result = compute_lots(entry, sl_result.sl_price, symbol, lot_size, self.config)

            # Build alert payload
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
                "spot_position": "Above VWAP ✓" if option_type == "CE" else "Below VWAP ✓",
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M"),
                "strike": strike_choice.strike,
                "relation": strike_choice.relation,
            }

            # Log alert FIRST (durable record before Telegram)
            self.signal_logger.log_alert(alert_data)

            # Track in-memory counters for EOD
            self.session_alert_count += 1
            if symbol == "NIFTY":
                self.session_nifty_alerts += 1
            elif symbol == "BANKNIFTY":
                self.session_bn_alerts += 1

            # Send Telegram (after JSONL durability)
            if self.config.telegram.send_signal_alerts:
                self.telegram.send_signal(alert_data)
                logger.info(f"ALERT FIRED: {symbol} {strike_choice.strike}{option_type}")

        except Exception as e:
            logger.error(f"Alert generation failed: {e}")
            logger.exception(e)

    def _log_rejection(self, symbol, strike, option_type, blocker, reason, now):
        """Log silent rejections (when enabled in config)."""
        if not self.config.logging.log_every_signal_check:
            return
        self.signal_logger.log_rejection({
            "timestamp_ist": now.isoformat(),
            "symbol": symbol,
            "strike": strike,
            "option_type": option_type,
            "rejection_blocker": blocker,
            "rejection_reason": reason,
            "all_passed": False,
        })

    def _trigger_circuit_breaker(self, reason: str) -> None:
        logger.warning(f"CIRCUIT BREAKER: {reason}")
        self.state.trigger_circuit_breaker(reason)
        if self.config.telegram.send_circuit_breaker_alerts:
            self.telegram.send_circuit_breaker(reason)

    def _get_spot_candles(self, symbol: str):
        """Fetch spot index 5-min candles for the session."""
        if self.broker_name == "kite":
            tokens = {"NIFTY": "256265", "BANKNIFTY": "260105"}
            return self.feed.get_5min_candles(tokens[symbol], 100)
        else:  # upstox
            keys = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank"}
            return self.feed.get_5min_candles(keys[symbol], 100)

    def send_eod(self):
        """Send end-of-day summary."""
        if not self.config.telegram.send_eod_summary:
            return
        summary = self._compute_eod_summary()
        self.telegram.send_eod_summary(summary)

    def _compute_eod_summary(self) -> dict:
        """
        Uses in-memory counters — never re-reads JSONL files (avoids
        double-counting rejections as scans).
        """
        today_str = datetime.now(IST).date().isoformat()
        return {
            "date": today_str,
            "total_scans": self.session_scan_count,
            "alerts_fired": self.session_alert_count,
            "nifty_alerts": self.session_nifty_alerts,
            "banknifty_alerts": self.session_bn_alerts,
            "circuit_breaker": "YES" if self.state._state.circuit_breaker_triggered else "NO",
            "vix_close": self.session_vix,
        }

    def run_forever(self):
        """
        Main loop — runs until market closes or Ctrl+C.
        
        Scan cadence: exactly ONE scan per closed 5-min candle.
        Dedup key = (date, hour, candle_minute). This survives long
        scans (>10s) and missed wall-clock ticks.
        """
        self.setup()
        logger.info("Bot entered main loop")
        
        eod_sent = False
        last_scan_candle = None
        
        try:
            while True:
                now = datetime.now(IST)

                # Hard square-off check
                if self._is_hard_squareoff_time(now) and not eod_sent:
                    self.send_eod()
                    eod_sent = True
                    logger.info("EOD summary sent. Bot will exit when market closes.")

                # End of day — exit
                if now.time() >= dt_time(15, 30):
                    logger.info("Market closed. Bot exiting.")
                    break

                # Determine which 5-min candle window we're in
                candle_minute = (now.minute // 5) * 5
                candle_key = (now.date(), now.hour, candle_minute)
                
                # Seconds since the candle boundary
                seconds_into_candle = (now.minute % 5) * 60 + now.second
                
                # Fire 5-30 seconds after candle close, exactly once per candle
                in_trigger_window = 5 <= seconds_into_candle <= 30
                
                if (in_trigger_window 
                    and candle_key != last_scan_candle 
                    and self._is_scan_time(now)):
                    try:
                        self.scan_once()
                        last_scan_candle = candle_key
                    except Exception as e:
                        logger.exception(f"Scan failed: {e}")
                        try:
                            self.telegram.send_exception(traceback.format_exc())
                        except Exception:
                            pass
                        # Still mark as scanned to avoid retry storm
                        last_scan_candle = candle_key

                time_mod.sleep(2)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C)")
        except Exception as e:
            logger.exception("FATAL error in main loop")
            try:
                self.telegram.send_exception(traceback.format_exc())
            except Exception:
                pass
            sys.exit(1)


def main():
    """Entry point."""
    print("=" * 60)
    print("  SHORT COVER CASCADE — Phase 5 Live Bot")
    print("=" * 60)
    orch = Orchestrator()
    orch.run_forever()


if __name__ == "__main__":
    main()

=========================================================
--- TASK 5: BUG FIX — check_risk.py input validation ---
=========================================================

Add at top of main() in scripts/check_risk.py, BEFORE any computation:

if args.entry > 2000 and not args.force_entry:
    print("ERROR: --entry value looks like an index spot price, not an option premium.")
    print(f"Got --entry {args.entry}, expected something like 50-1000.")
    print("Real NIFTY/BankNifty option premiums rarely exceed ₹1000.")
    print("If you really meant this value, pass --force-entry.")
    sys.exit(1)

Add a --force-entry boolean flag (action="store_true", default=False)
that skips this check for power users testing edge cases.

=========================================================
--- TASK 6: Update config.yaml with new toggles ---
=========================================================

Add to config.yaml under time_rules section:

time_rules:
  normal_start_time: "09:45"
  gap_day_start_time: "10:15"
  last_entry_time: "14:30"
  soft_squareoff_time: "14:55"
  hard_squareoff_time: "15:00"
  gap_day_enabled: true   # Toggle gap-day rule (>1% open → 10:15 start)

If the section already has some fields, only ADD missing ones — do not
overwrite existing user-tuned values.

=========================================================
--- TASK 7: Unit tests ---
=========================================================

Create tests/test_orchestrator.py with these tests (all mocked):

def test_is_market_hours_weekday_open():
def test_is_market_hours_weekend_closed():
def test_is_market_hours_before_open():
def test_is_market_hours_after_close():
def test_is_scan_time_before_945_normal_day():
def test_is_scan_time_before_1015_gap_day():
def test_is_scan_time_during_window():
def test_is_scan_time_after_1430():
def test_is_hard_squareoff_after_3pm():
def test_trigger_circuit_breaker_at_2_sl():
def test_trigger_circuit_breaker_at_6k_loss():
def test_circuit_breaker_blocks_further_scans():
def test_token_freshness_kite_stale_raises():
def test_token_freshness_kite_today_ok():
def test_gap_day_detection_under_1pct_returns_false():
def test_gap_day_detection_over_1pct_returns_true():
def test_scan_loop_fires_exactly_once_per_candle():

Create tests/test_telegram.py (mock the Bot class):
def test_telegram_initialized_with_secrets():
def test_telegram_missing_secrets_raises():
def test_telegram_send_returns_true_on_success():
def test_telegram_send_returns_false_on_failure_no_raise():
def test_format_startup_includes_broker_name():
def test_format_startup_includes_gap_day_marker_when_set():
def test_format_signal_includes_all_required_fields():

Create tests/test_signal_logger.py:
def test_log_signal_appends_to_jsonl():
def test_log_signal_default_event_type_is_scan():
def test_log_rejection_writes_event_type_rejection():
def test_log_alert_appends_to_alerts_jsonl():
def test_log_creates_directory_if_missing():
def test_each_line_is_valid_json():
def test_timestamps_are_ist_iso():

Run pytest tests/ -v. Target: 170+ tests passing.

=========================================================
--- TASK 8: Update run.bat for live mode ---
=========================================================

run.bat should:
1. Activate venv (existing)
2. Print warning: "Bot will run continuously until market close or Ctrl+C"
3. Print active broker
4. Confirm token date
5. Run python -m src.main

DO NOT auto-run during testing — only run when user explicitly invokes.

=========================================================
--- TASK 9: Create scripts/test_telegram.py ---
=========================================================

User-facing utility to verify Telegram setup BEFORE running the bot.

Usage: python scripts/test_telegram.py

1. load_secrets()
2. Initialize TelegramAlerter
3. Send a test message: "🧪 Telegram test from Short Cover Cascade Bot.
   If you see this, your setup works."
4. Print success/failure
5. If failure, print troubleshooting tips:
   - Check TELEGRAM_BOT_TOKEN value
   - Check TELEGRAM_CHAT_ID is numeric
   - Did you send /start to the bot first?

After completing everything, run:
  pytest tests/ -v

Report:
1. Test count (target 170+)
2. List of files created
3. Confirm run.bat updated
4. Confirm config.yaml gained gap_day_enabled toggle
5. Any tricky decisions you made on the orchestrator timing/loop
````

---

## STEP 3 — Verification Checklist (Machine 2 — pre-market)

### Pre-market (anytime before 9:15 AM IST tomorrow)
```cmd
git pull
call venv\Scripts\activate.bat

:: Test Telegram works
python scripts\test_telegram.py
:: → you should receive a test message in your Telegram chat

:: Verify all tests pass
pytest tests\ -v
:: → 170+ tests passing
```

### Market open day (9:14 AM — bot startup ritual)
```cmd
:: 1. Refresh Kite token first (writes KITE_TOKEN_DATE=today to secrets.env)
python scripts\refresh_token_kite.py

:: 2. Pre-market healthcheck
python scripts\feed_healthcheck.py
:: → confirms feed + spot prices + VIX

:: 3. Start the bot
run.bat
:: Bot enters main loop, sends Telegram startup alert
:: Runs continuously until 3:30 PM, scans every 5 min
```

### What you should see during market hours
- **9:15 AM**: Telegram message: "🚀 SHORT COVER CASCADE BOT STARTED" with config summary, including gap-day marker if applicable
- **9:45 AM (or 10:15 on gap day)**: Bot begins scanning every 5 minutes
- **logs/signals.jsonl**: growing — every condition check logged (event_type="scan" or "rejection")
- **logs/alerts.jsonl**: only valid 5/5 alerts (likely 0-3 per day)
- **15:00 PM**: Telegram EOD summary message
- **15:30 PM**: Bot exits cleanly

### What happens on a real alert
You receive a Telegram message like:
```
🚨 SHORT COVER CASCADE SIGNAL
─────────────────────────────
Instrument: NIFTY 24050 CE
Strike relation: ATM (ITM/ATM/OTM)
Expiry: 2026-06-02
Date: 2026-05-28 | Time: 10:35
Day Type: Normal
VIX: 14.2 (Normal Regime, 1.0×)
Spot: 24030.00 (Above VWAP ✓)
Lot Size: 65

ENTRY: ₹152.50 (LIMIT)
SL: ₹140.00 (Method 1)
TP1: ₹171.25 (1.5R, exit 50%)
TP2: ₹183.75 (2.5R, exit 50%)

Risk per unit: ₹12.50
Lots: 3 → Total Risk: ₹2,437.50
(3 × 65 × ₹12.50)

C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓
─────────────────────────────
ALERT ONLY — no order placed
```

### First day specifically — what to check after market close
1. `signals.jsonl` should have plenty of lines, split between event_type="scan" and event_type="rejection"
2. `alerts.jsonl` should have 0-3 lines (rare for all 5 to align)
3. Compare any alerts against Kite chart manually — verify the trade would have been valid
4. Telegram EOD summary received — `signals scanned` should match `wc -l` of event_type=scan records only
5. If today was a gap day, confirm no alerts fired before 10:15 AM

### Sanity check — EOD scan count vs JSONL
```cmd
:: Count actual scans (excluding rejections)
findstr /c:"\"event_type\": \"scan\"" logs\signals.jsonl | find /c /v ""
:: This number should equal the "Signals scanned" line in your Telegram EOD
```

---

## STEP 4 — When you confirm Phase 5 done, report

1. Pytest count (target 170+)
2. Did Telegram test message arrive successfully?
3. First day live run output (Telegram screenshots if comfortable)
4. signals.jsonl line count for the day, split by event_type
5. alerts.jsonl content (paste any 5/5 alerts that fired)
6. Was today a gap day? Did the 10:15 rule trigger correctly?
7. Token-freshness check: did bot refuse to start when you tried without refreshing?
8. Any errors in bot.log

---

## What Phase 6 looks like

**Phase 6 is the 30-day patience phase. No coding.**

Just run the bot every market day. Each morning:
1. Refresh Kite token
2. Run healthcheck
3. Start run.bat
4. Let it run until 3:30 PM
5. Review alerts.jsonl that evening — would each alert have been a real trade?

After 30 days you have ~30 daily logs and ~10-50 alerts. That's your dataset for Phase 7 backtesting.

**End of Phase 5.**
