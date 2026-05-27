# Phase 5A — Telegram Alerts + Main Orchestrator (Alert-Only Bot)

**Goal:** Connect every component built in Phases 0-4 into a running bot.
Every 5 minutes during market hours, the bot scans NIFTY + BankNifty
strikes, checks all 5 conditions, logs everything to JSONL, and sends
Telegram alerts when a 5/5 signal fires. NO orders placed (alert-only).

This document is the **single self-contained reference** for the
alert-only bot. It absorbs the original Phase 5 work and the Phase
5.1.5 mid-session robustness hotfixes (multi-day candle fetch, VWAP
today-filter, `data_issue` event type, robust gap detection). The
**dashboard / ML data / outcome remarks layer is in `PHASE_5B.md`** —
recreate 5A first, then 5B sits on top.

**Time estimate:** 3 hours code + 1 hour Telegram setup + first live run.

## Deliverables

- Telegram integration: signal alerts, EOD summary, startup, exceptions
- Main orchestrator: 5-min candle close loop with full safety logic
- Gap-day detection (>1% open vs prev close → no entry before 10:15) with
  multi-day candle lookback so mid-session bot restarts work
- VWAP filters multi-day input to today's session before computing
- `INSUFFICIENT_LOOKBACK` errors routed to a new `data_issue` event_type
  so analytics stay clean
- Token-date staleness check at startup (refuses to start on stale token)
- `signals.jsonl` logging — every scan, rejection, and data_issue
- `alerts.jsonl` — only valid 5/5 signals
- `gap_log.jsonl` — one row per bot startup with directional gap math
- `check_risk.py` input validation (reject entries > ₹2,000)
- Lot-size verification at startup (broker value wins on mismatch)
- Production-readiness verification on Machine 2

## What Phase 5A does NOT do

- No order placement (Phase 8)
- No backtest (Phase 7)
- No dashboard, no Parquet ML store, no `bot_remark` / `bot_tags`,
  no `would_alert_extended` event, no Telegram "Insight:" line, no
  directional gap labels — all of that is **Phase 5B**.

> A handful of Phase 5B hooks appear in the orchestrator (clearly marked
> with `# Phase 5.2:` comments). They are inert when the dashboard
> module isn't built yet, so the alert-only bot still runs end-to-end
> from 5A alone if you skip those lines on a clean rebuild.

---

## STEP 1 — Telegram bot setup (Machine 2, ~10 minutes, one-time)

Before any code runs, you need a Telegram bot.

### Create the bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Pick a name (e.g. "Short Cover Cascade Bot") and a username ending
   in `_bot` (e.g. `scc_alerts_bot`)
4. BotFather replies with a **bot token** — looks like `7891234567:AAH...xyz`
5. **Copy the token immediately** — you cannot see it again

### Get your chat ID

1. Search for **@userinfobot** in Telegram
2. Send `/start`
3. It replies with your numeric **chat_id** (e.g. `123456789`)

### Send the bot a "hello" message first

1. Find your new bot in Telegram search
2. Click Start
3. Send any message (e.g. "hi")

Without this step Telegram blocks unsolicited messages from the bot.

### Fill `secrets.env`

Add these two lines to `config/secrets.env` (which stays gitignored):

```
TELEGRAM_BOT_TOKEN=7891234567:AAH...xyz
TELEGRAM_CHAT_ID=123456789
```

### Smoke test (10 seconds)

```cmd
curl "https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage?chat_id=<YOUR_CHAT_ID>&text=test"
```

You should receive "test" in Telegram instantly. If not, the bot/chat
setup is wrong — fix it before running the Python code.

---

## STEP 2 — Code modules

### 2.1 — `src/alerts/telegram_bot.py`

Thin synchronous wrapper around `python-telegram-bot`. Every public
`send_*` method returns True/False; failures are logged but never raised
— a Telegram outage must not crash the live scan loop. Token and
`chat_id` are read from the environment (`load_secrets()` populates them
at process start).

```python
"""Telegram alert sender.

Thin synchronous wrapper around ``python-telegram-bot``. Every public
``send_*`` method returns True/False; failures are logged but never
raised — Telegram outages must not crash the live scan loop.

Token and chat id are read from environment (``load_secrets`` populates
them at process start).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger
from telegram import Bot

IST = ZoneInfo("Asia/Kolkata")


class TelegramAlerter:
    """Send formatted alerts to a single Telegram chat.

    Construct once at bot startup; reuse for the whole session.
    """

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token or not self.chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing from secrets.env"
            )
        self._bot = Bot(token=self.token)

    # ----- public sending API -----

    def send(self, message: str) -> bool:
        """Send a raw message. Returns True on success, False on failure."""
        try:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    self._bot.send_message(
                        chat_id=self.chat_id,
                        text=message,
                        parse_mode=None,
                    )
                )
                return True
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_startup(self, config_summary: dict) -> bool:
        return self.send(self._format_startup(config_summary))

    def send_signal(self, signal_data: dict) -> bool:
        return self.send(self._format_signal(signal_data))

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
        return self.send(self._format_eod(summary))

    def send_exception(self, trace: str) -> bool:
        msg = (
            "⚠️ BOT EXCEPTION\n"
            "─────────────────────────────\n"
            f"Time: {self._now_ist()}\n"
            f"Trace:\n{trace[:3000]}"
        )
        return self.send(msg)

    # ----- private formatters -----

    def _format_startup(self, c: dict) -> str:
        gap_line = self._format_gap_line(c.get("gap_info", {}))
        return (
            "🚀 SHORT COVER CASCADE BOT STARTED\n"
            "─────────────────────────────\n"
            f"Time: {self._now_ist()}\n"
            f"Active broker: {c['broker']}\n"
            f"Mode: alert={c['alert_mode']} | order={c['order_place_mode']} | "
            f"paper={c['paper_trade_mode']}\n"
            f"Instruments: {c['instruments']}\n"
            f"India VIX: {c['vix']:.2f} ({c['vix_regime']})\n"
            f"Lot sizes: NIFTY={c['nifty_lot']}, BankNifty={c['banknifty_lot']}\n"
            f"\n{gap_line}\n"
            "─────────────────────────────"
        )

    def _format_gap_line(self, gap_info: dict) -> str:
        """Format the gap status block — always shown at startup.

        In Phase 5A the decisions are NORMAL / GAP_DAY / GAP_DETECTED_BUT_DISABLED.
        Phase 5B replaces those with directional GAP_UP / GAP_DOWN variants
        and updates this function to render them — see PHASE_5B.md §2.4.
        """
        if not gap_info:
            return "Gap status: unknown"

        per_sym = gap_info.get("per_symbol", {})
        nifty_pct = per_sym.get("NIFTY", {}).get("gap_pct")
        bn_pct = per_sym.get("BANKNIFTY", {}).get("gap_pct")
        threshold = gap_info.get("threshold_pct", 1.0)
        direction = gap_info.get("direction", "both")
        enabled = gap_info.get("enabled", False)
        decision = gap_info.get("decision", "NORMAL")

        nifty_str = f"{nifty_pct:+.2f}%" if nifty_pct is not None else "N/A"
        bn_str = f"{bn_pct:+.2f}%" if bn_pct is not None else "N/A"

        if decision == "GAP_DAY":
            verdict = "⚠️ GAP DAY — 10:15 start"
        elif decision == "GAP_DETECTED_BUT_DISABLED":
            verdict = f"⚠ Gap >{threshold}% but rule OFF — 9:45 start"
        else:
            verdict = "✓ Normal day — 9:45 start"

        toggle_str = "ON" if enabled else "OFF"
        return (
            f"📈 Gap status (threshold {threshold}%, dir={direction}, "
            f"toggle={toggle_str}):\n"
            f"  NIFTY: {nifty_str} | BankNifty: {bn_str}\n"
            f"  {verdict}"
        )

    def _format_signal(self, s: dict) -> str:
        # Phase 5B adds an "Insight:" line populated from
        # s["telegram_short_remark"]. In Phase 5A that key is empty and
        # the alert is rendered without it.
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
            "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓\n"
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
        return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
```

### 2.2 — `src/alerts/signal_logger.py`

Append-only JSONL writer for both `signals.jsonl` and `alerts.jsonl`.
Every record carries an `event_type`. Phase 5A uses four values:
`scan`, `rejection`, `alert`, `data_issue`. (`gap` rows are written by
the orchestrator directly to `gap_log.jsonl`, not through this class.
`would_alert_extended` arrives in Phase 5B.)

```python
"""JSONL writers for signals.jsonl and alerts.jsonl.

Two parallel logs:

  - ``signals.jsonl``  — every scan, every rejection, and every data_issue.
  - ``alerts.jsonl``   — only valid 5/5 signals that fired a Telegram.

Every record carries an ``event_type`` ("scan" / "rejection" / "alert" /
"data_issue") so the EOD counter / backtest harness / verification
scripts can distinguish real condition checks from short-circuit
rejections and from technical data-availability problems.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

IST = ZoneInfo("Asia/Kolkata")


class SignalLogger:
    """Append-only JSONL logger for scans, rejections, and alerts."""

    def __init__(
        self,
        signals_path: str | Path = "logs/signals.jsonl",
        alerts_path: str | Path = "logs/alerts.jsonl",
    ) -> None:
        self.signals_path = Path(signals_path)
        self.alerts_path = Path(alerts_path)
        self.signals_path.parent.mkdir(parents=True, exist_ok=True)
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)

    def log_signal(self, record: dict) -> None:
        """Append one record to signals.jsonl.

        Defaults event_type to "scan" if missing. Any caller-supplied
        event_type ("scan" / "rejection" / "alert" / "data_issue") is
        preserved as-is.
        """
        if "event_type" not in record:
            record["event_type"] = "scan"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_rejection(self, record: dict) -> None:
        """Append a rejection record (event_type forced to "rejection")."""
        record["event_type"] = "rejection"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_alert(self, record: dict) -> None:
        """Append one alert record to alerts.jsonl (event_type "alert")."""
        record["event_type"] = "alert"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.alerts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            "Alert logged: {} {} {}",
            record.get("symbol"),
            record.get("strike"),
            record.get("option_type"),
        )
```

### 2.3 — `src/alerts/__init__.py`

```python
from src.alerts.signal_logger import SignalLogger
from src.alerts.telegram_bot import TelegramAlerter

__all__ = ["TelegramAlerter", "SignalLogger"]
```

### 2.4 — `src/main.py` (orchestrator)

Full source. The handful of Phase 5B hooks are clearly marked
(`# Phase 5.2:` comments). They are inert without the dashboard
module — i.e. `bot_remark` is generated only if `from src.dashboard.remarks`
imports succeed and the orchestrator silently records an empty remark
otherwise. On a clean rebuild you can leave those lines in place; they
only become active once Phase 5B's dashboard module exists.

The 5.1.5 robustness fixes are baked in:

- `_get_spot_candles` accepts a `lookback_candles` parameter and the
  gap-detector passes `600` for ~7 trading days of history
- `_detect_gap_day` filters multi-day candles by IST date, logs a
  clear warning if either today's or prev-day data is missing
- `_scan_strike` catches `Insufficient lookback` separately and routes
  it to `_log_data_issue` instead of polluting rejection counts

```python
"""Phase 5 orchestrator — live alert-only scan loop.

One pass per closed 5-min candle: fetch spot/option data, run C0–C4,
log every scan to ``signals.jsonl``, and on a 5/5 pass fire a Telegram
alert (after logging the alert to ``alerts.jsonl`` for durability).

No order placement code lives here — that is Phase 8.

Critical rules:
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
from datetime import date as date_cls, datetime, time as dt_time
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
# Phase 5.2: bot remark helpers — see PHASE_5B.md §3.1
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


class Orchestrator:
    """Glue layer that runs Phase 5: scan -> log -> alert."""

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
        self.nifty_lot: int = 0
        self.banknifty_lot: int = 0
        self.nifty_expiry = None
        self.banknifty_expiry = None
        # In-memory counters — EOD reads these (never re-walks JSONL).
        self.session_scan_count = 0
        self.session_alert_count = 0
        self.session_nifty_alerts = 0
        self.session_bn_alerts = 0
        # Phase 5.2: dashboard sync guard (set once per session). Inert in 5A.
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
                f"BANKNIFTY lot mismatch: "
                f"config={self.config.instruments.banknifty_lot_size}, "
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

        # 5. Detect gap day (must run after 09:15 — open candle exists).
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
                "gap_info": self.gap_info,
            })

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

        Phase 5.1.5: fetches 600 candles (~7 trading days) so a mid-session
        bot start still sees prev day's close even when today's session
        already contains the recent candles. Returns is_gap_day=False on
        any failure (with sym_info['error'] set for visibility).

        Decision labels in Phase 5A: NORMAL / GAP_DAY / GAP_DETECTED_BUT_DISABLED.
        Phase 5B replaces these with directional GAP_UP / GAP_DOWN variants —
        see PHASE_5B.md §2.4.
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
                # 600 candles ≈ 7 trading days — Phase 5.1.5 fix.
                candles = self._get_spot_candles(symbol, lookback_candles=600)
                if candles is None or len(candles) < 2:
                    sym_info["error"] = (
                        f"insufficient candle data: total_n="
                        f"{0 if candles is None else len(candles)}"
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
                        f"Gap detection: {symbol} has {len(today_candles)} "
                        f"today candles, {len(prev_candles)} prev-day candles. "
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

        # Phase 5A label set.
        if any_triggered and enabled:
            gap_info["decision"] = "GAP_DAY"
            is_gap_day = True
        elif any_triggered:
            gap_info["decision"] = "GAP_DETECTED_BUT_DISABLED"
            is_gap_day = False
        else:
            gap_info["decision"] = "NORMAL"
            is_gap_day = False

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

        # Phase 5.1.5: route INSUFFICIENT_LOOKBACK to data_issue, not rejection.
        try:
            df = self.feed.get_5min_candles(strike_choice.instrument_key, 100)
            snapshot = get_latest_snapshot(df)
        except (ValueError, RuntimeError) as e:
            err_msg = str(e)
            if "insufficient" in err_msg.lower():
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
            # Phase 5.2: option distance above its own VWAP (see PHASE_5B.md §2.3).
            "opt_above_vwap_pct": float(result.opt_above_vwap_pct),
        }
        self.signal_logger.log_signal(signal_record)

        # Phase 5.2: would_alert_extended logging — see PHASE_5B.md §4.3.
        self._maybe_log_extended_zone(signal_record, result)

        if not result.all_passed:
            return

        self._fire_alert(
            symbol, strike_choice, option_type, expiry,
            lot_size, snapshot, signal_record, now,
        )

    def _maybe_log_extended_zone(self, signal_record: dict, result) -> None:
        """Phase 5.2 hook. Inert in Phase 5A — config keys don't exist yet."""
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

            # Phase 5.2: bot_remark / bot_tags / telegram_short_remark
            # generation — see PHASE_5B.md §4.1. Wrapped in try/except so
            # 5A bot still works if the dashboard module is absent.
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
        self.signal_logger.log_rejection({
            "timestamp_ist": now.isoformat(),
            "symbol": symbol,
            "strike": strike,
            "option_type": option_type,
            "rejection_blocker": blocker,
            "rejection_reason": reason,
            "all_passed": False,
        })

    def _log_data_issue(
        self,
        symbol: str,
        strike: int | None,
        option_type: str,
        issue_type: str,
        msg: str,
        now: datetime,
    ) -> None:
        """Phase 5.1.5: record a technical data-availability issue in signals.jsonl.

        These are NOT strategy rejections — they get their own
        ``event_type='data_issue'`` so dashboard analytics can isolate
        them (mid-session restart with cold RSI MA history etc.).
        """
        if not self.config.logging.log_every_signal_check:
            return
        self.signal_logger.log_signal({
            "timestamp_ist": now.isoformat(),
            "event_type": "data_issue",
            "symbol": symbol,
            "strike": strike,
            "option_type": option_type,
            "issue_type": issue_type,
            "issue_message": msg,
        })

    def _trigger_circuit_breaker(self, reason: str) -> None:
        logger.warning(f"CIRCUIT BREAKER: {reason}")
        self.state.trigger_circuit_breaker(reason)
        if self.config.telegram.send_circuit_breaker_alerts:
            self.telegram.send_circuit_breaker(reason)

    def _get_spot_candles(
        self, symbol: str, lookback_candles: int = 100
    ) -> pd.DataFrame:
        """Fetch spot index 5-min candles. Default ~1.5 days lookback;
        gap-day detection calls with 600 for multi-day history.
        """
        if self.broker_name == "kite":
            tokens = {"NIFTY": "256265", "BANKNIFTY": "260105"}
            return self.feed.get_5min_candles(tokens[symbol], lookback_candles)
        keys = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank"}
        return self.feed.get_5min_candles(keys[symbol], lookback_candles)

    # =====================================================================
    # End-of-day
    # =====================================================================

    def send_eod(self) -> None:
        if not self.config.telegram.send_eod_summary:
            return
        self.telegram.send_eod_summary(self._compute_eod_summary())

    def _run_dashboard_sync_on_exit(self) -> None:
        """Phase 5.2.1 hook. Inert in Phase 5A — config key doesn't exist yet.
        See PHASE_5B.md §4.4 for the full implementation.
        """
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

        try:
            while True:
                now = datetime.now(IST)

                if self._is_hard_squareoff_time(now) and not eod_sent:
                    self.send_eod()
                    eod_sent = True
                    logger.info("EOD summary sent. Bot will exit at market close.")

                if now.time() >= MARKET_CLOSE_TIME:
                    logger.info(
                        "Market closed (15:30 IST). Bot exiting, "
                        "dashboard sync will run."
                    )
                    break

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
            # Phase 5.2.1: auto-sync dashboard on exit (no-op in pure 5A).
            self._run_dashboard_sync_on_exit()


def main() -> None:
    print("=" * 60)
    print("  SHORT COVER CASCADE — Phase 5 Live Bot")
    print("=" * 60)
    orch = Orchestrator()
    orch.run_forever()


if __name__ == "__main__":
    main()
```

### 2.5 — `src/indicators/vwap.py` (Phase 5.1.5 multi-day filter)

`compute_session_vwap` filters its input to the calendar date of the
most recent candle BEFORE computing VWAP. This makes it safe for a
caller to pass a multi-day DataFrame (which Phase 5.1.5 needs so RSI
MA has enough warmup history). The session anchor remains 09:15 IST.

```python
"""Session-anchored VWAP using hlc3.

Confirmed source: Upstox chart label "VWAP hlc3 Session".
Many internet examples use close-only; that is WRONG for this strategy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_vwap_hlc3(df: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP using hlc3 = (high + low + close) / 3."""
    if len(df) == 0:
        return pd.Series([], dtype=float, index=df.index)

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    volume = df["volume"].astype(float)

    hlc3 = (high + low + close) / 3.0

    cum_pv = (hlc3 * volume).cumsum()
    cum_v = volume.cumsum()

    vwap = np.where(cum_v > 0, cum_pv / cum_v.replace(0, np.nan), hlc3)
    return pd.Series(vwap, index=df.index, dtype=float)


def compute_session_vwap(
    df: pd.DataFrame,
    session_start_hour: int = 9,
    session_start_minute: int = 15,
) -> pd.Series:
    """VWAP for today's session only, anchored at 09:15 IST.

    Multi-day input is safe (Phase 5.1.5): this function filters to the
    calendar date of the most recent candle BEFORE computing VWAP, so a
    multi-day frame (now returned by ``get_5min_candles`` to satisfy RSI
    MA lookback) does not pollute today's VWAP with prior-day data.
    """
    if len(df) == 0:
        return pd.Series([], dtype=float, index=df.index)

    ts = pd.to_datetime(df["timestamp"])
    minutes_since_midnight = ts.dt.hour * 60 + ts.dt.minute
    session_open_minutes = session_start_hour * 60 + session_start_minute
    pre_session_mask = minutes_since_midnight < session_open_minutes
    session_date = ts.dt.date.where(
        ~pre_session_mask, (ts - pd.Timedelta(days=1)).dt.date
    )

    latest_session_date = session_date.iloc[-1]
    today_mask = session_date.values == latest_session_date

    out = pd.Series(np.nan, index=df.index, dtype=float)
    today_idx = df.index[today_mask]
    if len(today_idx) == 0:
        return out
    today_df = df.loc[today_idx]
    out.loc[today_idx] = compute_vwap_hlc3(today_df).values
    return out
```

### 2.6 — Multi-day candle fetch in `src/data/kite_feed.py` and `upstox_feed.py`

**Contract change (Phase 5.1.5):**

```
get_5min_candles(instrument_token, lookback_candles: int = 100) -> pd.DataFrame
```

- Compute days back: `days_back = max(2, ceil(lookback_candles / 75) + 1)`
  — 75 candles per trading day, +1 buffer.
- Fetch from `(today - days_back) at 09:15 IST` to now.
- Return a DataFrame with full multi-day history.
- Caller `compute_session_vwap` filters to today (§2.5); RSI / OI MA /
  Volume MA use the whole window for warmup.

This is the single change required in both `kite_feed.py` and
`upstox_feed.py` — replace any "fetch only today" logic with the
multi-day path above.

### 2.7 — `scripts/check_risk.py` input validation

Add at the top of `main()`, BEFORE any computation:

```python
if args.entry > 2000 and not args.force_entry:
    print("ERROR: --entry value looks like an index spot price, not an option premium.")
    print(f"Got --entry {args.entry}, expected something like 50-1000.")
    print("Real NIFTY/BankNifty option premiums rarely exceed ₹1000.")
    print("If you really meant this value, pass --force-entry.")
    sys.exit(1)
```

Also add a `--force-entry` boolean flag
(`action="store_true", default=False`) so a power user can bypass for
edge-case testing.

### 2.8 — `config/config.yaml` additions (Phase 5A)

Add to `time_rules` (preserve existing fields):

```yaml
time_rules:
  normal_start_time: "09:45"
  gap_day_start_time: "10:15"
  last_entry_time: "14:30"
  soft_squareoff_time: "14:55"
  hard_squareoff_time: "15:00"
  gap_day_enabled: true          # Toggle gap-day rule (>1% open → 10:15 start)
  gap_day_threshold_pct: 1.0     # Threshold % for gap detection
  gap_day_direction: "both"      # "both" / "up" / "down"
```

Add to `logging`:

```yaml
logging:
  log_level: "INFO"
  log_every_signal_check: true  # logs rejections + data_issues
```

Add a `telegram` section:

```yaml
telegram:
  send_startup_alert: true
  send_signal_alerts: true
  send_circuit_breaker_alerts: true
  send_eod_summary: true
```

### 2.9 — `scripts/test_telegram.py`

User-facing utility to verify Telegram setup BEFORE running the bot.

```python
#!/usr/bin/env python
"""Verify Telegram setup. Run once on Machine 2 before the first live bot run."""

from src.config_loader import load_secrets
from src.alerts.telegram_bot import TelegramAlerter


def main() -> None:
    load_secrets()
    try:
        alerter = TelegramAlerter()
    except RuntimeError as e:
        print(f"FAIL: {e}")
        return
    ok = alerter.send(
        "🧪 Telegram test from Short Cover Cascade Bot. "
        "If you see this, your setup works."
    )
    if ok:
        print("SUCCESS — check your Telegram chat.")
    else:
        print("FAILED — see logs above. Common causes:")
        print("  - Wrong TELEGRAM_BOT_TOKEN value")
        print("  - TELEGRAM_CHAT_ID is not numeric")
        print("  - You forgot to send /start to the bot first")


if __name__ == "__main__":
    main()
```

### 2.10 — `run.bat`

```bat
@echo off
call venv\Scripts\activate.bat
echo Short Cover Cascade Bot — Live Mode
echo Bot will run continuously until market close (15:30 IST) or Ctrl+C
echo.
python -m src.main
```

---

## STEP 3 — Unit tests

Aim for **170+ tests passing** after Phase 5A. Add the following files
on top of the Phase 0-4 test suite.

### `tests/test_telegram.py` (mock the `Bot` class)

```
test_telegram_initialized_with_secrets
test_telegram_missing_secrets_raises
test_telegram_send_returns_true_on_success
test_telegram_send_returns_false_on_failure_no_raise
test_format_startup_includes_broker_name
test_format_startup_includes_gap_day_marker_when_set
test_format_signal_includes_all_required_fields
```

### `tests/test_signal_logger.py`

```
test_log_signal_appends_to_jsonl
test_log_signal_default_event_type_is_scan
test_log_rejection_writes_event_type_rejection
test_log_alert_appends_to_alerts_jsonl
test_log_creates_directory_if_missing
test_each_line_is_valid_json
test_timestamps_are_ist_iso
test_log_signal_accepts_data_issue_event_type     # Phase 5.1.5
```

### `tests/test_orchestrator.py`

```
test_is_market_hours_weekday_open
test_is_market_hours_weekend_closed
test_is_market_hours_before_open
test_is_market_hours_after_close
test_is_scan_time_before_945_normal_day
test_is_scan_time_before_1015_gap_day
test_is_scan_time_during_window
test_is_scan_time_after_1430
test_is_hard_squareoff_after_3pm
test_trigger_circuit_breaker_at_2_sl
test_trigger_circuit_breaker_at_6k_loss
test_circuit_breaker_blocks_further_scans
test_token_freshness_kite_stale_raises
test_token_freshness_kite_today_ok
test_gap_day_detection_under_1pct_returns_false
test_gap_day_detection_over_1pct_returns_true
test_scan_loop_fires_exactly_once_per_candle
# Phase 5.1.5
test_scan_strike_logs_data_issue_not_rejection_on_insufficient_lookback
test_data_issue_recorded_with_correct_issue_type
test_gap_detection_succeeds_with_multi_day_candles
test_gap_detection_logs_clear_warning_on_no_prev_day_data
```

### `tests/test_vwap.py` / `tests/test_indicators.py`

```
# Phase 5.1.5
test_vwap_filters_to_today_when_multi_day_df_passed
test_vwap_value_unchanged_whether_input_is_today_only_or_multi_day
```

Run: `pytest tests/ -v` — target ~210 tests.

---

## STEP 4 — Verification checklist

### Pre-market (anytime before 9:15 AM IST tomorrow)

```cmd
git pull
call venv\Scripts\activate.bat

:: Test Telegram works (one-time)
python scripts\test_telegram.py
:: → you should receive a test message in your Telegram chat

:: Verify all tests pass
pytest tests\ -v
:: → 170+ tests passing
```

### Market-open ritual (9:14 AM)

```cmd
:: 1. Refresh Kite token (writes KITE_TOKEN_DATE=today to secrets.env)
python scripts\refresh_token_kite.py

:: 2. Pre-market healthcheck
python scripts\feed_healthcheck.py

:: 3. Start the bot
run.bat
```

### What you should see during market hours

- **9:15 AM**: Telegram message "🚀 SHORT COVER CASCADE BOT STARTED"
  with config summary and gap-status block
- **9:45 AM** (or 10:15 on gap day): bot begins scanning every 5 min
- **`logs/signals.jsonl`**: growing — every condition check logged
  (`event_type` = `scan`, `rejection`, or `data_issue`)
- **`logs/alerts.jsonl`**: only valid 5/5 alerts (likely 0-3 per day)
- **`logs/gap_log.jsonl`**: one row written at startup with the
  morning's gap math
- **15:00 PM**: Telegram EOD summary message
- **15:30 PM**: Bot exits cleanly

### What a real alert looks like

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

### After market close — what to check

1. `signals.jsonl` should be plenty of lines, split between
   `event_type=scan`, `event_type=rejection`, and (occasionally)
   `event_type=data_issue`.
2. `alerts.jsonl` should have 0-3 lines.
3. Compare any alerts against Kite chart manually — verify the trade
   would have been valid.
4. Telegram EOD summary received — `Signals scanned` should equal the
   count of `event_type=scan` lines only (rejections/data_issues are
   tracked separately by in-memory counters).
5. If today was a gap day, confirm no alerts fired before 10:15 AM.
6. `gap_log.jsonl` should have one row for today's startup with
   `decision`, per-symbol `gap_pct`, `any_triggered`, and the toggle
   state.

### Token-freshness sanity

Try to start the bot without refreshing the token — it should refuse
to start and tell you which script to run.

### Sanity check — EOD scan count vs JSONL

```cmd
findstr /c:"\"event_type\": \"scan\"" logs\signals.jsonl | find /c /v ""
:: should equal the "Signals scanned" line in your Telegram EOD
```

---

## Phase 5.1.5 — what's baked in vs the original Phase 5

The original Phase 5 had three failure modes that surfaced on the first
live run (2026-05-27). Phase 5.1.5 fixed all three; this 5A document
shows the corrected code already integrated. Quick map:

| Symptom in original 5 | Phase 5.1.5 fix (now in 5A) |
|---|---|
| `Insufficient lookback for indicators ['rsi_ma']` floods `signals.jsonl` as rejections on mid-session start | `get_5min_candles(lookback_candles=100)` multi-day fetch (§2.6); `_scan_strike` routes `ValueError("Insufficient...")` to `_log_data_issue` (§2.4); new `event_type='data_issue'` (§2.2) |
| Gap detection returns "None%" because today's first / yesterday's last candle aren't both present | `_detect_gap_day` uses `lookback_candles=600` (~7 trading days), filters by IST date, logs a clear warning with the date range when data is missing (§2.4) |
| `compute_session_vwap` could be polluted by prior-day candles when callers pass multi-day data | `compute_session_vwap` filters to the calendar date of the most recent candle before computing (§2.5) |

If you ever rebuild from scratch you do NOT need to reproduce the
original-Phase-5-then-patch sequence — the §2.4-2.6 source already
incorporates everything.

---

## STEP 5 — Phase 5A done. Now what?

Once Phase 5A is verified, you have a working **alert-only bot** with
robust mid-session startup. The next layer — quarterly Excel
dashboards, monthly Parquet ML store, bot remark generation,
`would_alert_extended` event logging, directional gap labels, and
`finally`-block dashboard auto-sync — lives in **`PHASE_5B.md`**.

Phase 5B touches the orchestrator only via the small hooks already
visible in §2.4 (the `# Phase 5.2:` comments). The strategy logic
itself is locked at the end of 5A and 5B does not modify it.

After 5B verifies, **Phase 6** begins: 30 trading days of running the
bot every market day, reviewing the dashboard each evening. No coding
during Phase 6 — only data collection.
