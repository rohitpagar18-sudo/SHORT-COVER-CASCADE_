# Phase 5A — Telegram Alerts + Main Orchestrator (Alert-Only Bot)

**Goal:** Connect every component built in Phases 0–4 into a running bot.
Every 5 minutes during market hours the bot scans NIFTY + BankNifty strikes,
checks all 5 conditions, logs to JSONL, and sends a Telegram alert on a 5/5
signal. No orders placed. Holiday guard prevents ghost rows on NSE holidays.

This document is the **single self-contained reference** for the alert-only bot.
It incorporates Phase 5.1.5 robustness fixes (multi-day candle fetch, VWAP
today-filter, `data_issue` event type, directional gap labels) and Phase 5.2.2
holiday guard (candle-based market-status detection with VIX second-source
confirmation). **The dashboard / ML data layer is in `PHASE_5B.md`** — rebuild
5A first, then 5B sits on top.

**Time estimate:** 3 hours code + 1 hour Telegram setup + first live run.

## Deliverables

- Synchronous Telegram alerts via `requests` (no asyncio, no event-loop issues)
- Append-only JSONL logger: `signals.jsonl` / `alerts.jsonl` / `gap_log.jsonl`
- Orchestrator: 5-min candle-close scan loop with full safety logic
- Holiday guard: detects NSE holidays/weekends from broker candle data; no
  hardcoded calendar. VIX timestamp used as second-source confirmation.
- Gap-day detection with directional labels (`GAP_UP` / `GAP_DOWN` / `_DISABLED`)
  and multi-day lookback so mid-session restarts work
- VWAP filters multi-day input to today's session only before computing
- `data_issue` event_type for `INSUFFICIENT_LOOKBACK` errors (keeps rejection
  analytics clean on mid-session bot starts)
- Token-date staleness check at startup
- `check_risk.py` entry > ₹2,000 guard
- Lot-size verification at startup

## What Phase 5A does NOT do

- No order placement (Phase 8)
- No backtest (Phase 7)
- No dashboard, Parquet ML store, `bot_remark`, or `would_alert_extended` —
  those are Phase 5B hooks that are present as inert stubs in the orchestrator

---

## STEP 1 — Telegram bot setup (Machine 2, one-time)

### Create the bot

1. Open Telegram, search **@BotFather** → `/newbot`
2. Choose a name and a `_bot` username (e.g. `scc_alerts_bot`)
3. Copy the bot token (e.g. `7891234567:AAH...xyz`)

### Get your chat ID

1. Search **@userinfobot** → `/start` → note the numeric chat_id

### Send the bot a first message

Find your new bot, click Start, send any message ("hi"). Without this
Telegram blocks unsolicited messages.

### Fill `secrets.env`

```
TELEGRAM_BOT_TOKEN=7891234567:AAH...xyz
TELEGRAM_CHAT_ID=123456789
```

### Smoke test

```cmd
curl "https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=test"
```

---

## STEP 2 — Code modules

### 2.1 — `src/alerts/telegram_bot.py`

Synchronous HTTP via `requests`. No asyncio — eliminates the "Event loop is
closed" error that occurs after many sends in one session.

```python
"""Telegram alert sender (synchronous HTTP, no asyncio).

Direct calls to api.telegram.org via requests.post. All send_* methods
return True on success, False on failure; failures are logged but never
raised — Telegram outages must not crash the live scan loop.
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from loguru import logger

IST = ZoneInfo("Asia/Kolkata")
TELEGRAM_API_BASE = "https://api.telegram.org"
SEND_TIMEOUT_SECONDS = 10


class TelegramAlerter:
    """Send formatted alerts to a single Telegram chat."""

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token or not self.chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing from secrets.env"
            )
        self._url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"

    def send(self, message: str) -> bool:
        """POST to Telegram. Returns True on 2xx, False otherwise."""
        try:
            resp = requests.post(
                self._url,
                data={"chat_id": self.chat_id, "text": message},
                timeout=SEND_TIMEOUT_SECONDS,
            )
            if resp.status_code // 100 == 2:
                return True
            logger.error(f"Telegram send failed: HTTP {resp.status_code} body={resp.text[:300]}")
            return False
        except requests.RequestException as e:
            logger.error(f"Telegram send failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Telegram send unexpected error: {e}")
            return False

    def send_startup(self, config_summary: dict) -> bool:
        return self.send(self._format_startup(config_summary))

    def send_signal(self, signal_data: dict) -> bool:
        return self.send(self._format_signal(signal_data))

    def send_circuit_breaker(self, reason: str) -> bool:
        return self.send(
            "🛑 CIRCUIT BREAKER TRIGGERED\n─────────────────────────────\n"
            f"Reason: {reason}\nTime: {self._now_ist()}\nNo more trades today."
        )

    def send_eod_summary(self, summary: dict) -> bool:
        return self.send(self._format_eod(summary))

    def send_exception(self, trace: str) -> bool:
        return self.send(
            "⚠️ BOT EXCEPTION\n─────────────────────────────\n"
            f"Time: {self._now_ist()}\nTrace:\n{trace[:3000]}"
        )

    # ----- private formatters -----

    def _format_startup(self, c: dict) -> str:
        gap_line = self._format_gap_line(c.get("gap_info", {}))
        status = c.get("market_status", "open")
        if status in ("weekend", "holiday"):
            market_line = f"⛔ Market: {status.upper()} — bot dormant today"
        else:
            market_line = f"Market status: {status}"
        return (
            "🚀 SHORT COVER CASCADE BOT STARTED\n─────────────────────────────\n"
            f"Time: {self._now_ist()}\n"
            f"Active broker: {c['broker']}\n"
            f"Mode: alert={c['alert_mode']} | order={c['order_place_mode']} | paper={c['paper_trade_mode']}\n"
            f"Instruments: {c['instruments']}\n"
            f"India VIX: {c['vix']:.2f} ({c['vix_regime']})\n"
            f"Lot sizes: NIFTY={c['nifty_lot']}, BankNifty={c['banknifty_lot']}\n"
            f"{market_line}\n\n{gap_line}\n─────────────────────────────"
        )

    def _format_gap_line(self, gap_info: dict) -> str:
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

        if decision == "GAP_UP":
            verdict = "⚠️ GAP UP — 10:15 start"
        elif decision == "GAP_DOWN":
            verdict = "⚠️ GAP DOWN — 10:15 start"
        elif decision == "GAP_UP_DISABLED":
            verdict = "⚠ GAP UP detected (rule OFF) — 9:45 start"
        elif decision == "GAP_DOWN_DISABLED":
            verdict = "⚠ GAP DOWN detected (rule OFF) — 9:45 start"
        elif decision == "SKIPPED_HOLIDAY":
            verdict = "⛔ Gap check skipped (holiday/weekend)"
        else:
            verdict = "✓ Normal day — 9:45 start"

        toggle_str = "ON" if enabled else "OFF"
        return (
            f"📈 Gap status (threshold {threshold}%, dir={direction}, toggle={toggle_str}):\n"
            f"  NIFTY: {nifty_str} | BankNifty: {bn_str}\n"
            f"  {verdict}"
        )

    def _format_signal(self, s: dict) -> str:
        insight = (s.get("telegram_short_remark") or "").strip()
        insight_line = f"\nInsight: {insight}\n" if insight else "\n"
        return (
            "🚨 SHORT COVER CASCADE SIGNAL\n─────────────────────────────\n"
            f"Instrument: {s['symbol']} {s['strike']} {s['option_type']}\n"
            f"Strike relation: {s['relation']} (ITM/ATM/OTM)\n"
            f"Expiry: {s['expiry']}\n"
            f"Date: {s['date']} | Time: {s['time']}\n"
            f"Day Type: {s['day_type']}\n"
            f"VIX: {s['vix']:.2f} ({s['vix_regime']}, {s['vix_multiplier']}×)\n"
            f"Spot: {s['spot']:.2f} ({s['spot_position']})\n"
            f"Lot Size: {s['lot_size']}\n\n"
            f"ENTRY: ₹{s['entry']:.2f} (LIMIT)\n"
            f"SL: ₹{s['sl']:.2f} (Method {s['sl_method']})\n"
            f"TP1: ₹{s['tp1']:.2f} ({s['tp1_r']}R, exit 50%)\n"
            f"TP2: ₹{s['tp2']:.2f} ({s['tp2_r']}R, exit 50%)\n\n"
            f"Risk per unit: ₹{s['risk_per_unit']:.2f}\n"
            f"Lots: {s['lots']} → Total Risk: ₹{s['total_risk']:,.2f}\n"
            f"({s['lots']} × {s['lot_size']} × ₹{s['risk_per_unit']:.2f})\n"
            f"{insight_line}"
            "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓\n─────────────────────────────\n"
            "ALERT ONLY — no order placed"
        )

    def _format_eod(self, s: dict) -> str:
        return (
            "📊 END-OF-DAY SUMMARY\n─────────────────────────────\n"
            f"Date: {s['date']}\nSignals scanned: {s['total_scans']}\n"
            f"Alerts fired: {s['alerts_fired']}\n"
            f"Circuit breaker: {s['circuit_breaker']}\n"
            f"By symbol:\n  NIFTY: {s['nifty_alerts']} alerts\n  BankNifty: {s['banknifty_alerts']} alerts\n"
            f"VIX at close: {s['vix_close']:.2f}\n─────────────────────────────"
        )

    def _now_ist(self) -> str:
        return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
```

### 2.2 — `src/alerts/signal_logger.py`

```python
"""JSONL writers for signals.jsonl and alerts.jsonl.

  signals.jsonl — every scan, rejection, and data_issue.
  alerts.jsonl  — only valid 5/5 signals that fired a Telegram.

event_type values: "scan" / "rejection" / "alert" / "data_issue" /
"would_alert_extended" (Phase 5B)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

IST = ZoneInfo("Asia/Kolkata")


class SignalLogger:
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
        if "event_type" not in record:
            record["event_type"] = "scan"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_rejection(self, record: dict) -> None:
        record["event_type"] = "rejection"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.signals_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_alert(self, record: dict) -> None:
        record["event_type"] = "alert"
        record["_logged_at"] = datetime.now(IST).isoformat()
        with self.alerts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("Alert logged: {} {} {}", record.get("symbol"), record.get("strike"), record.get("option_type"))
```

### 2.3 — `src/alerts/__init__.py`

```python
from src.alerts.signal_logger import SignalLogger
from src.alerts.telegram_bot import TelegramAlerter

__all__ = ["TelegramAlerter", "SignalLogger"]
```

### 2.4 — `src/main.py` — critical architecture

Full source lives in the repo. Reproduce these EXACT structures; the
standard methods (lot-size check, _scan_symbol, _fire_alert, etc.) follow
the same pattern as Phases 1–4.

**Module-level types** (after imports, before class):

```python
from dataclasses import dataclass
from enum import Enum

class MarketStatus(Enum):
    UNKNOWN  = "unknown"
    WEEKEND  = "weekend"
    HOLIDAY  = "holiday"
    PRE_OPEN = "pre_open"
    OPEN     = "open"

@dataclass
class MarketStatusResult:
    status: MarketStatus
    reason: str
    today_candle_count: int
    latest_candle_date: str | None
    checked_at: str

HARD_SQUAREOFF_TIME = dt_time(15, 0)
MARKET_CLOSE_TIME   = dt_time(15, 30)
```

**Orchestrator.__init__ — attribute list** (all fields must be present):

```python
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
    self.session_scan_count = 0
    self.session_alert_count = 0
    self.session_nifty_alerts = 0
    self.session_bn_alerts = 0
    self.dashboard_synced = False   # Phase 5B hook, inert in 5A
```

**setup() — numbered steps** (each step is a method call or block):

```
1. Configure loguru → logs/bot.log
2. connect_feed(config) → self.feed, self.broker_name
3. _verify_token_freshness()  ← raises on stale token
4. Lot-size broker check (warn on mismatch, use broker value)
5. get_india_vix() → self.session_vix, classify_vix() → self.session_vix_info
6a. _check_market_status() → self.market_status
    If WEEKEND or HOLIDAY: set holiday_abort=True, skip gap detection
    If PRE_OPEN: log "will recheck"
6b. If NOT holiday_abort: _detect_gap_day() → self.is_gap_day, self.gap_info
    Else: self.gap_info = {"decision": "SKIPPED_HOLIDAY", ...}
7. TelegramAlerter(), SignalLogger(), StateManager().load_state()
8. get_next_expiry(feed, "NIFTY"), get_next_expiry(feed, "BANKNIFTY")
9. telegram.send_startup({..., "market_status": self.market_status.status.value})
```

**_check_market_status() — full implementation** (primary source of truth for
holidays; uses candle data, not a hardcoded calendar):

```python
def _check_market_status(self) -> MarketStatusResult:
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

    # VIX second-source check — only when candles said HOLIDAY.
    # A fresh VIX tick means the broker candle endpoint glitched on a
    # real trading day → flip to UNKNOWN (fail-open) so scans proceed.
    if status == MarketStatus.HOLIDAY:
        confirmed, vix_reason = self._confirm_holiday_via_vix(now)
        if not confirmed:
            logger.warning(
                f"Candle check said HOLIDAY but VIX is fresh ({vix_reason}). "
                "Likely a candle-fetch glitch. Falling back to UNKNOWN — scans will proceed."
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
```

**_confirm_holiday_via_vix() — full implementation**:

```python
def _confirm_holiday_via_vix(self, now: datetime) -> tuple[bool, str]:
    """VIX timestamp < 10 min → market is live → NOT holiday (returns False).
    Timestamp stale / unavailable / error → trust candle check (returns True).
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
        return False, f"VIX updated {age_minutes:.1f} min ago (value={vix_value:.2f}) — market is live"
    return True, f"VIX last updated {age_minutes:.1f} min ago (value={vix_value:.2f}) — confirms holiday"
```

**scan_once() — holiday_abort gate** (FIRST thing in the method):

```python
def scan_once(self) -> None:
    if self.holiday_abort:
        logger.debug(f"Scan suppressed — status={self.market_status.status.value}")
        return
    # ... hot-reload config, time gate, circuit-breaker check, symbol loop
```

**_detect_gap_day() — directional labels** (final decision block only):

```python
# After the per-symbol gap math loop:
any_up = any(
    info.get("triggers") and (info.get("gap_pct") or 0.0) >= threshold
    for info in gap_info["per_symbol"].values()
)
any_down = any(
    info.get("triggers") and (info.get("gap_pct") or 0.0) <= -threshold
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
self._log_gap(gap_info)
return is_gap_day, gap_info
```

**run_forever() — status re-check for PRE_OPEN/UNKNOWN** (inside the while
loop, before the candle_key dedup block):

```python
eod_sent = False
last_scan_candle: tuple | None = None
last_status_check: datetime | None = None
STATUS_RECHECK_SECONDS = 300

# Inside while True:
needs_recheck = (
    not self.holiday_abort
    and self.market_status is not None
    and self.market_status.status in (MarketStatus.PRE_OPEN, MarketStatus.UNKNOWN)
    and (
        last_status_check is None
        or (now - last_status_check).total_seconds() >= STATUS_RECHECK_SECONDS
    )
)
if needs_recheck:
    self.market_status = self._check_market_status()
    last_status_check = now
    if self.market_status.status == MarketStatus.HOLIDAY:
        self.holiday_abort = True
        logger.warning("Status upgraded to HOLIDAY after recheck. Suppressing scans.")
        try:
            self.telegram.send(
                f"⛔ NSE HOLIDAY DETECTED at {now.strftime('%H:%M')} — "
                "bot was started early. All scans suppressed."
            )
        except Exception:
            pass
    elif self.market_status.status == MarketStatus.OPEN:
        logger.info("Status upgraded to OPEN — scan loop is now live.")

# Candle dedup + scan_once() call unchanged from Phase 4.
# finally: self._run_dashboard_sync_on_exit()  ← Phase 5B hook (inert in 5A)
```

**_verify_token_freshness() — refuses to start on stale token:**

```python
def _verify_token_freshness(self) -> None:
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
            raise RuntimeError(f"UPSTOX_TOKEN_DATE format invalid: {token_date}")
        age_days = (datetime.now(IST).date() - token_d).days
        if age_days > 350:
            logger.warning(f"Upstox token is {age_days} days old. Refresh soon.")
        if age_days > 365:
            raise RuntimeError(
                f"Upstox token is {age_days} days old (>365). Refresh required."
            )
    logger.info(f"Token freshness OK for {self.broker_name}")
```

**_detect_gap_day() — 600-candle multi-day fetch, per-symbol gap math:**

```python
def _detect_gap_day(self) -> tuple[bool, dict]:
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
            "open": None, "prev_close": None, "gap_pct": None,
            "triggers": False, "error": None,
        }
        try:
            # 600 candles ≈ 7 trading days — covers mid-session bot starts.
            candles = self._get_spot_candles(symbol, lookback_candles=600)
            if candles is None or len(candles) < 2:
                sym_info["error"] = (
                    f"insufficient candle data: total_n="
                    f"{0 if candles is None else len(candles)}"
                )
                gap_info["per_symbol"][symbol] = sym_info
                continue

            ts_dates = pd.to_datetime(candles["timestamp"]).dt.date
            today_candles = candles[ts_dates == today_d]
            prev_candles = candles[ts_dates < today_d]
            if len(today_candles) == 0 or len(prev_candles) == 0:
                sym_info["error"] = (
                    f"insufficient_data: today_n={len(today_candles)}, "
                    f"prev_n={len(prev_candles)}"
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
                triggers = abs(gap_pct) >= threshold

            sym_info.update({
                "open": today_open, "prev_close": prev_close,
                "gap_pct": round(gap_pct, 4), "triggers": triggers,
            })
            if triggers:
                any_triggered = True
        except Exception as e:
            sym_info["error"] = str(e)
            logger.warning(f"Gap detection error for {symbol}: {e}")

        gap_info["per_symbol"][symbol] = sym_info

    gap_info["any_triggered"] = any_triggered

    # Directional labels — see "directional labels" block above.
    # ... (omitted here — see prior block)
    self._log_gap(gap_info)
    return is_gap_day, gap_info


def _log_gap(self, gap_info: dict) -> None:
    """Append gap math to logs/gap_log.jsonl (one line per startup)."""
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
```

**Time helpers — hard 3:00 PM is an invariant, others are config-driven:**

```python
def _is_market_hours(self, now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    return dt_time(9, 15) <= now.time() <= MARKET_CLOSE_TIME

def _is_scan_time(self, now: datetime) -> bool:
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
```

**scan_once() — full body:**

```python
def scan_once(self) -> None:
    if self.holiday_abort:
        status_val = self.market_status.status.value if self.market_status else "unknown"
        logger.debug(f"Scan suppressed — status={status_val}")
        return

    now = datetime.now(IST)
    # Hot-reload config every scan — allows runtime threshold tuning.
    # Broker / order_place_mode changes still require a restart.
    self.config = load_config(CONFIG_PATH)

    if not self._is_scan_time(now):
        return

    if self.state._state.circuit_breaker_triggered:
        logger.info(f"Circuit breaker active: {self.state._state.circuit_breaker_reason}")
        return

    if (
        self.config.circuit_breakers.daily_sl_count_breaker
        and self.state.get_daily_sl_count() >= self.config.circuit_breakers.max_sl_per_day
    ):
        self._trigger_circuit_breaker(
            f"Daily SL count reached {self.state.get_daily_sl_count()}"
        )
        return

    if (
        self.config.circuit_breakers.daily_loss_breaker
        and self.state.get_daily_loss() >= self.config.circuit_breakers.max_loss_per_day_rupees
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
```

**_scan_symbol() — C0 fast-fail before option chain fetch:**

```python
def _scan_symbol(self, symbol: str, expiry: Any, lot_size: int, now: datetime) -> None:
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
                self.feed, symbol, spot_close, option_type, str(expiry), self.config,
            )
        except Exception as e:
            logger.error(f"Strike selection failed for {symbol} {option_type}: {e}")
            continue

        for strike_choice in strikes:
            self._scan_strike(
                symbol, strike_choice, option_type, expiry,
                lot_size, spot_close, spot_vwap, now,
            )
```

**_scan_strike() — runs C0–C4, logs every scan, routes data issues:**

```python
def _scan_strike(
    self, symbol: str, strike_choice, option_type: str, expiry: Any,
    lot_size: int, spot_close: float, spot_vwap: float, now: datetime,
) -> None:
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
            # Technical data issue — NOT a strategy rejection.
            self._log_data_issue(
                symbol, strike_choice.strike, option_type,
                "INSUFFICIENT_LOOKBACK", err_msg, now,
            )
            return
        logger.error(f"Indicator computation failed: {e}")
        return
    except Exception as e:
        logger.error(f"Indicator computation failed: {e}")
        return

    result = check_all_conditions(
        option_snapshot=snapshot,
        spot_close=spot_close, spot_vwap=spot_vwap,
        option_type=option_type, config=self.config,
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
        "opt_above_vwap_pct": float(result.opt_above_vwap_pct),
    }
    self.signal_logger.log_signal(signal_record)

    # Phase 5B hook — captures 4/5 scans in the extended zone.
    self._maybe_log_extended_zone(signal_record, result)

    if not result.all_passed:
        return

    self._fire_alert(
        symbol, strike_choice, option_type, expiry,
        lot_size, snapshot, signal_record, now,
    )
```

**_maybe_log_extended_zone() — Phase 5B hook (inert in 5A, lives in main.py):**

```python
def _maybe_log_extended_zone(self, signal_record: dict, result) -> None:
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
```

**_fire_alert() — compute SL/TP/lots → log_alert() → send_signal():**

```python
def _fire_alert(
    self, symbol: str, strike_choice, option_type: str, expiry: Any,
    lot_size: int, snapshot, signal_record: dict, now: datetime,
) -> None:
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
        lot_result = compute_lots(entry, sl_result.sl_price, symbol, lot_size, self.config)

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

        # Phase 5B: generate the human-readable remark and structured ML tags.
        try:
            context = {
                "time_hhmm": now.strftime("%H:%M"),
                "vix_regime": self.session_vix_info.regime.value,
                "is_expiry_day": is_expiry,
                "daily_sl_count": self.state.get_daily_sl_count(),
                "daily_alert_count": self.session_alert_count,
            }
            snapshot_dict = {
                "option_close": snapshot.close, "option_vwap": snapshot.vwap,
                "rsi": snapshot.rsi, "rsi_ma": snapshot.rsi_ma,
                "oi": snapshot.oi, "oi_ma": snapshot.oi_ma,
                "volume": snapshot.volume, "volume_ma": snapshot.volume_ma,
                "opt_above_vwap_pct": signal_record.get("opt_above_vwap_pct", 0.0),
            }
            bot_remark, bot_tags = generate_remark_and_tags(snapshot_dict, context)
            alert_data["bot_remark"] = bot_remark
            alert_data["bot_tags"] = bot_tags
            alert_data["telegram_short_remark"] = telegram_short_remark(bot_remark)
        except Exception as e:
            logger.warning(f"Bot remark generation failed: {e}")
            alert_data.setdefault("bot_remark", "")
            alert_data.setdefault("bot_tags", "")
            alert_data.setdefault("telegram_short_remark", "")

        # Durability first: JSONL lands on disk BEFORE Telegram fires.
        self.signal_logger.log_alert(alert_data)

        self.session_alert_count += 1
        if symbol == "NIFTY":
            self.session_nifty_alerts += 1
        elif symbol == "BANKNIFTY":
            self.session_bn_alerts += 1

        if self.config.telegram.send_signal_alerts:
            self.telegram.send_signal(alert_data)
            logger.info(f"ALERT FIRED: {symbol} {strike_choice.strike}{option_type}")

    except Exception as e:
        logger.error(f"Alert generation failed: {e}")
        logger.exception(e)
```

**_log_rejection() and _log_data_issue() — both honour log_every_signal_check toggle:**

```python
def _log_rejection(
    self, symbol: str, strike: int | None, option_type: str,
    blocker: str, reason: str, now: datetime,
) -> None:
    if not self.config.logging.log_every_signal_check:
        return
    self.signal_logger.log_rejection({
        "timestamp_ist": now.isoformat(),
        "symbol": symbol, "strike": strike, "option_type": option_type,
        "rejection_blocker": blocker, "rejection_reason": reason,
        "all_passed": False,
    })


def _log_data_issue(
    self, symbol: str, strike: int | None, option_type: str,
    issue_type: str, msg: str, now: datetime,
) -> None:
    """Records technical data-availability issues — NOT strategy rejections.
    Gets its own event_type='data_issue' so analytics stay clean.
    """
    if not self.config.logging.log_every_signal_check:
        return
    self.signal_logger.log_signal({
        "timestamp_ist": now.isoformat(),
        "event_type": "data_issue",
        "symbol": symbol, "strike": strike, "option_type": option_type,
        "issue_type": issue_type, "issue_message": msg,
    })


def _trigger_circuit_breaker(self, reason: str) -> None:
    logger.warning(f"CIRCUIT BREAKER: {reason}")
    self.state.trigger_circuit_breaker(reason)
    if self.config.telegram.send_circuit_breaker_alerts:
        self.telegram.send_circuit_breaker(reason)
```

**_get_spot_candles() — broker-aware token map:**

```python
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
```

**EOD summary + dashboard sync on exit:**

```python
def send_eod(self) -> None:
    if not self.config.telegram.send_eod_summary:
        return
    self.telegram.send_eod_summary(self._compute_eod_summary())


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


def _run_dashboard_sync_on_exit(self) -> None:
    """Phase 5.2.1: Auto-sync dashboard on bot exit. Best-effort, idempotent.

    Honours:
      - config.dashboard.auto_trigger_at_1535 (toggle, default ON)
      - self.dashboard_synced (prevents double-run in same process)
      - weekday check (skip Saturday/Sunday)

    Failures are logged + Telegrammed but never re-raised — the bot
    must exit cleanly even if sync fails.
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
            self.telegram.send_exception(f"Dashboard auto-sync failed on exit:\n{e}")
        except Exception:
            pass
```

**Full run_forever() — wraps everything in try/except/finally:**

```python
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

            # Dynamic status re-check while still PRE_OPEN/UNKNOWN.
            needs_recheck = (
                not self.holiday_abort
                and self.market_status is not None
                and self.market_status.status in (MarketStatus.PRE_OPEN, MarketStatus.UNKNOWN)
                and (
                    last_status_check is None
                    or (now - last_status_check).total_seconds() >= STATUS_RECHECK_SECONDS
                )
            )
            if needs_recheck:
                self.market_status = self._check_market_status()
                last_status_check = now
                if self.market_status.status == MarketStatus.HOLIDAY:
                    self.holiday_abort = True
                    logger.warning(
                        "Status upgraded to HOLIDAY after recheck. Suppressing scans."
                    )
                    try:
                        self.telegram.send(
                            f"⛔ NSE HOLIDAY DETECTED at {now.strftime('%H:%M')} — "
                            "bot was started early. All scans suppressed."
                        )
                    except Exception:
                        pass
                elif self.market_status.status == MarketStatus.OPEN:
                    logger.info("Status upgraded to OPEN — scan loop is now live.")

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
                # Mark the candle scanned whether scan_once raised or not —
                # prevents a retry storm inside the trigger window.
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
        # Phase 5.2.1: Auto-sync dashboard on exit (clean exit, Ctrl+C,
        # or exception). Runs exactly once per session.
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

### 2.4.1 — Feed support: `get_india_vix_with_timestamp()`

The VIX second-source check needs a `(value, last_trade_time_iso)` tuple
from the active feed. Added as an abstract method on `BaseFeed` and
implemented on both Kite and Upstox feeds.

**`src/data/base_feed.py` — abstract method (after `get_india_vix`):**

```python
@abstractmethod
def get_india_vix_with_timestamp(self) -> tuple[float, str | None]:
    """Return ``(vix_value, last_trade_time_iso)`` for the holiday-guard
    second check. ``last_trade_time_iso`` is the IST ISO timestamp of
    the most recent VIX tick, or ``None`` if the broker does not
    expose one. Returns ``(-1.0, None)`` on any error so callers can
    treat it as 'unknown — trust the first check'.
    """
    raise NotImplementedError
```

**`src/data/kite_feed.py` — Kite implementation (after `get_india_vix`):**

```python
def get_india_vix_with_timestamp(self) -> tuple[float, str | None]:
    try:
        quote = self._kite.quote(["NSE:INDIA VIX"])
        data = quote.get("NSE:INDIA VIX", {}) if isinstance(quote, dict) else {}
        value = float(data.get("last_price", -1.0))
        last_trade_time = data.get("last_trade_time")
        ts_iso: str | None = None
        if last_trade_time is not None:
            if isinstance(last_trade_time, datetime):
                ts = last_trade_time
            else:
                try:
                    ts = datetime.fromisoformat(str(last_trade_time))
                except ValueError:
                    ts = None
            if ts is not None:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=IST)
                ts_iso = ts.isoformat()
        return value, ts_iso
    except Exception as e:
        logger.warning("Kite India VIX with-timestamp fetch failed: {}", e)
        return -1.0, None
```

**`src/data/upstox_feed.py` — Upstox implementation + format-tolerant helper:**

```python
def get_india_vix_with_timestamp(self) -> tuple[float, str | None]:
    """Best-effort: Upstox's quote response timestamp format varies by
    SDK version. If we can't normalise to an IST ISO string cleanly we
    return ``(value, None)`` and the holiday-guard second check will
    skip gracefully (fall back to trusting the candle check).
    """
    try:
        resp = self._market_quote_api.get_full_market_quote(
            symbol=_UPSTOX_VIX_KEY, api_version="2.0"
        )
        value = self._extract_last_price(resp, _UPSTOX_VIX_KEY)
        ts_iso = self._extract_last_trade_time(resp, _UPSTOX_VIX_KEY)
        return value, ts_iso
    except Exception as e:
        logger.warning("Upstox India VIX with-timestamp fetch failed: {}", e)
        return -1.0, None


@staticmethod
def _extract_last_trade_time(resp: Any, instrument_key: str) -> str | None:
    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    if data is None:
        return None
    candidates = [instrument_key, instrument_key.replace("|", ":")]
    record = None
    if isinstance(data, dict):
        for k in candidates:
            if k in data:
                record = data[k]
                break
        if record is None and len(data) == 1:
            record = next(iter(data.values()))
    else:
        record = data
    if record is None:
        return None
    raw = None
    for field in ("last_trade_time", "timestamp"):
        raw = getattr(record, field, None)
        if raw is None and isinstance(record, dict):
            raw = record.get(field)
        if raw is not None:
            break
    if raw is None:
        return None
    try:
        if isinstance(raw, datetime):
            ts = raw
        elif isinstance(raw, (int, float)):
            # Treat large ints as ms epoch, small ints as seconds.
            secs = raw / 1000.0 if raw > 1e12 else float(raw)
            ts = datetime.fromtimestamp(secs, tz=IST)
        else:
            s = str(raw).strip()
            try:
                ts = datetime.fromisoformat(s)
            except ValueError:
                # "DD-MM-YYYY HH:MM:SS" — Upstox often uses this form.
                ts = datetime.strptime(s, "%d-%m-%Y %H:%M:%S")
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        return ts.isoformat()
    except Exception:
        return None
```

`FakeFeed` in `tests/test_expiry_resolver.py` must also implement the
new abstract method (stub returning `(0.0, None)` is sufficient — see
the test file).

### 2.5 — `src/indicators/vwap.py` (multi-day filter)

`compute_session_vwap` filters its input to the calendar date of the most
recent candle BEFORE computing. Multi-day input (needed for RSI MA warmup) is
safe because only today's candles enter the VWAP accumulator.

```python
def compute_session_vwap(df, session_start_hour=9, session_start_minute=15):
    if len(df) == 0:
        return pd.Series([], dtype=float, index=df.index)
    ts = pd.to_datetime(df["timestamp"])
    minutes_since_midnight = ts.dt.hour * 60 + ts.dt.minute
    pre_session_mask = minutes_since_midnight < (session_start_hour * 60 + session_start_minute)
    session_date = ts.dt.date.where(~pre_session_mask, (ts - pd.Timedelta(days=1)).dt.date)
    latest_session_date = session_date.iloc[-1]
    today_mask = session_date.values == latest_session_date
    out = pd.Series(np.nan, index=df.index, dtype=float)
    today_idx = df.index[today_mask]
    if len(today_idx) == 0:
        return out
    out.loc[today_idx] = compute_vwap_hlc3(df.loc[today_idx]).values
    return out
```

### 2.6 — Multi-day candle fetch (KiteFeed + UpstoxFeed)

Both feeds implement:

```
get_5min_candles(instrument_key, lookback_candles: int = 100) -> pd.DataFrame
```

```python
days_back = max(2, math.ceil(max(lookback_candles, 1) / 75) + 1)
# Fetch from (today - days_back) at 09:15 IST to now.
# Return sorted oldest→newest, timestamps timezone-aware IST.
```

Gap detection calls with `lookback_candles=600` (~7 trading days).
`compute_session_vwap` filters to today; RSI/OI/Volume MA use the full window.

### 2.7 — `scripts/check_risk.py` guard

At top of `main()`, before computation:

```python
if args.entry > 2000 and not args.force_entry:
    print("ERROR: --entry looks like a spot price, not an option premium.")
    sys.exit(1)
```

Add `--force-entry` boolean flag (`action="store_true", default=False`).

### 2.8 — `config/config.yaml` additions

```yaml
time_rules:
  normal_start_time: "09:45"
  gap_day_start_time: "10:15"
  last_entry_time: "14:30"
  soft_squareoff_time: "14:55"
  hard_squareoff_time: "15:00"
  gap_day_enabled: true
  gap_day_threshold_pct: 1.0
  gap_day_direction: "both"   # "both" / "up" / "down"

logging:
  log_level: "INFO"
  log_every_signal_check: true   # logs rejections + data_issues

telegram:
  send_startup_alert: true
  send_signal_alerts: true
  send_circuit_breaker_alerts: true
  send_eod_summary: true
```

### 2.9 — `scripts/test_telegram.py`

```python
#!/usr/bin/env python
"""Verify Telegram setup before first live run."""
from src.config_loader import load_secrets
from src.alerts.telegram_bot import TelegramAlerter

def main() -> None:
    load_secrets()
    try:
        alerter = TelegramAlerter()
    except RuntimeError as e:
        print(f"FAIL: {e}"); return
    ok = alerter.send("🧪 Telegram test from Short Cover Cascade Bot.")
    print("SUCCESS — check Telegram." if ok else "FAILED — check logs.")

if __name__ == "__main__":
    main()
```

### 2.10 — `run.bat`

```bat
@echo off
call venv\Scripts\activate.bat
echo Short Cover Cascade Bot — Live Mode
python -m src.main
```

---

## STEP 3 — Unit tests (target ~210 passing)

### `tests/test_telegram.py`
```
test_telegram_initialized_with_secrets
test_telegram_missing_secrets_raises
test_telegram_missing_chat_id_raises
test_telegram_send_returns_true_on_2xx
test_telegram_send_returns_false_on_non_2xx
test_telegram_send_returns_false_on_timeout
test_telegram_send_returns_false_on_connection_error
test_format_startup_includes_broker_name
test_format_startup_always_includes_gap_line
test_format_gap_line_shows_normal_when_under_threshold
test_format_gap_line_shows_gap_up_when_triggered_and_enabled
test_format_gap_line_shows_gap_down_when_triggered_and_enabled
test_format_gap_line_shows_disabled_warning_when_breached_but_off
test_format_signal_includes_all_required_fields
test_send_signal_passes_formatted_message_to_send
test_send_circuit_breaker_includes_reason
test_send_eod_summary_includes_counts
test_send_exception_truncates_long_trace
```

### `tests/test_signal_logger.py`
```
test_log_signal_appends_to_jsonl
test_log_signal_default_event_type_is_scan
test_log_signal_respects_explicit_event_type
test_log_rejection_writes_event_type_rejection
test_log_rejection_overrides_event_type
test_log_alert_appends_to_alerts_jsonl
test_log_creates_directory_if_missing
test_each_line_is_valid_json
test_timestamps_are_ist_iso
test_multiple_logs_append_not_overwrite
test_alerts_and_signals_files_are_separate
```

### `tests/test_orchestrator.py`
```
# Time helpers
test_is_market_hours_weekday_open
test_is_market_hours_weekend_closed
test_is_market_hours_before_open / after_close
test_is_scan_time_before_945_normal_day
test_is_scan_time_before_1015_gap_day
test_is_scan_time_during_window
test_is_scan_time_after_1430
test_is_hard_squareoff_after_3pm

# Circuit breakers
test_trigger_circuit_breaker_at_2_sl
test_trigger_circuit_breaker_at_6k_loss
test_circuit_breaker_blocks_further_scans

# Token freshness
test_token_freshness_kite_stale_raises
test_token_freshness_kite_today_ok
test_token_freshness_kite_missing_raises
test_token_freshness_upstox_missing_raises
test_token_freshness_upstox_recent_ok
test_token_freshness_upstox_invalid_format_raises

# Gap detection
test_gap_detection_disabled_toggle_returns_false
test_gap_detection_enabled_under_threshold_returns_false
test_gap_detection_enabled_over_threshold_returns_true
test_gap_detection_symmetric_negative_triggers
test_gap_detection_direction_up_only_ignores_negative
test_gap_detection_direction_down_only_ignores_positive
test_gap_log_jsonl_written_when_disabled
test_gap_log_jsonl_appends_not_truncates
test_gap_info_decision_field_correct   ← GAP_UP / GAP_DOWN / *_DISABLED / NORMAL

# Scan-loop mechanics
test_scan_loop_fires_exactly_once_per_candle
test_scan_loop_trigger_window_5_to_30_seconds

# EOD + helpers
test_eod_summary_uses_in_memory_counters
test_eod_summary_circuit_breaker_yes
test_enabled_instruments_str
test_log_rejection_respects_toggle
test_log_rejection_logs_when_enabled
test_trigger_circuit_breaker_sends_telegram_when_enabled
test_trigger_circuit_breaker_skips_telegram_when_disabled

# Phase 5.1.5 robustness
test_scan_strike_logs_data_issue_not_rejection_on_insufficient_lookback
test_data_issue_skipped_when_logging_toggle_off
test_gap_detection_succeeds_with_multi_day_candles
test_gap_detection_logs_clear_error_on_no_prev_day_data

# Holiday guard (Phase 5.2.2)
test_market_status_saturday_returns_weekend
test_market_status_sunday_returns_weekend
test_market_status_before_0915_returns_pre_open
test_market_status_no_today_candles_after_0930_returns_holiday
test_market_status_today_candles_present_returns_open
test_market_status_no_candles_before_0930_returns_pre_open
test_market_status_api_error_returns_unknown_not_holiday
test_scan_once_returns_immediately_when_holiday_abort_true
test_holiday_confirmed_when_both_candles_and_vix_stale
test_holiday_overridden_when_vix_is_fresh
test_vix_check_skipped_when_first_check_is_open
test_vix_check_failure_defaults_to_trusting_first_check
test_vix_check_no_timestamp_field_defaults_to_holiday

# Dashboard sync hook (Phase 5B inert stubs — tests still pass in 5A)
test_dashboard_sync_runs_in_finally_block_on_clean_exit
test_dashboard_sync_runs_on_keyboard_interrupt
test_dashboard_sync_skipped_on_weekend_exit
test_dashboard_sync_skipped_when_toggle_disabled
test_dashboard_sync_failure_does_not_prevent_exit
```

Run: `pytest tests/ -v`

---

## STEP 4 — Verification checklist

### Pre-market

```cmd
git pull && call venv\Scripts\activate.bat
python scripts\test_telegram.py   :: → receive test message in Telegram
pytest tests\ -v                  :: → 210+ tests passing
```

### Market-open ritual (9:14 AM)

```cmd
python scripts\refresh_token_kite.py   :: → writes KITE_TOKEN_DATE=today
python scripts\feed_healthcheck.py
run.bat
```

### What you should see

- **9:15 AM**: `🚀 SHORT COVER CASCADE BOT STARTED` Telegram with market status
- **9:45 AM** (10:15 on gap day): scanning starts every 5 min
- **Holiday/weekend**: bot starts, sends dormant notice, scans suppressed all day
- **Pre-open start before 9:30**: bot re-checks status every 5 min until OPEN
- `logs/signals.jsonl`: growing with `event_type ∈ {scan, rejection, data_issue}`
- `logs/alerts.jsonl`: 0–3 lines per day (only 5/5 signals)
- `logs/gap_log.jsonl`: one row per startup with directional decision
- **15:00**: EOD Telegram summary
- **15:30**: Bot exits, dashboard sync runs (Phase 5B — no-op in 5A)

### After market close

```cmd
:: Scan count should match signals.jsonl "event_type":"scan" lines
findstr /c:"\"event_type\": \"scan\"" logs\signals.jsonl | find /c /v ""

:: VIX confirmation logged? (should see one of these on holidays)
findstr "VIX confirms" logs\bot.log
findstr "VIX is fresh" logs\bot.log
```

### Token-freshness sanity

Start bot WITHOUT refreshing token → must refuse to start.

---

## STEP 5 — Phase 5A done. Now what?

Once Phase 5A verifies you have a working holiday-aware alert-only bot. The
next layer — Excel dashboards, Parquet ML store, bot remarks, C1 tuning — is
**`PHASE_5B.md`**. See **`PHASE_5C.md`** for the retroactive holiday-scan
cleanup script (`mark_holiday_scans.py`) and the `is_holiday_scan` schema
column.

---

## Post-first-live-run patches (see PHASE_5B Addendum for full detail)

After the first live runs, three orchestrator-side patches were folded
in. They live in `src/main.py`, both feeds, and `config.yaml`:

1. **In-progress candle drop** — `kite_feed.py` / `upstox_feed.py`
   `get_5min_candles()` now drop any candle whose timestamp is at or
   after the current 5-min boundary (IST). `.iloc[-1]` is therefore
   always the last fully closed bar.
2. **Stale-candle guard with retry** — `_scan_strike()` calls
   `_fetch_closed_candles_with_retry()` which retries up to
   `config.bot.api_retry_count` times and routes a still-stale fetch
   to `_log_data_issue(... issue_type="STALE_CANDLE", ...)` (NOT a
   rejection). `config.bot.scan_buffer_seconds` raised from 5 → 20.
3. **C0 toggleable, default OFF** — new
   `config.conditions.c0_spot_trend_filter_enabled` flag. When OFF,
   `check_all_conditions()` appends a SKIPPED C0 result and
   `_scan_symbol()` scans both CE and PE on every selected strike. The
   original `check_c0()` is retained and runs only when the toggle is
   ON.

Full text in **`PHASE_5B.md` → Phase 5B Addendum`**. New test file:
`tests/test_phase5b_fixes.py` (12 tests). Total suite: 305 passing.
