"""Telegram alert sender (synchronous HTTP, no asyncio).

Direct calls to api.telegram.org via requests.post. No
python-telegram-bot dependency, no asyncio event loop juggling.
All send_* methods return True on success, False on failure;
failures are logged but never raised.
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

    # ----- public sending API -----

    def send(self, message: str) -> bool:
        """POST to Telegram. Returns True on 2xx, False otherwise."""
        try:
            resp = requests.post(
                self._url,
                data={
                    "chat_id": self.chat_id,
                    "text": message,
                },
                timeout=SEND_TIMEOUT_SECONDS,
            )
            if resp.status_code // 100 == 2:
                return True
            logger.error(
                f"Telegram send failed: HTTP {resp.status_code} "
                f"body={resp.text[:300]}"
            )
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
        market_line = self._format_market_status_line(c.get("market_status"))
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
            f"{market_line}"
            f"\n{gap_line}\n"
            "─────────────────────────────"
        )

    def _format_market_status_line(self, status: str | None) -> str:
        """Render the market status line. Empty if caller didn't set it."""
        if not status:
            return ""
        if status in ("weekend", "holiday"):
            return f"\n⛔ Market: {status.upper()} — bot dormant today"
        return f"\nMarket status: {status}"

    def _format_gap_line(self, gap_info: dict) -> str:
        """Format the gap status block — always shown at startup."""
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

        # Phase 5.2: directional gap labels. Older labels (GAP_DAY,
        # GAP_DETECTED_BUT_DISABLED) are still accepted to keep replay /
        # backward-compat working.
        if decision == "GAP_UP":
            verdict = "⚠️ GAP UP — 10:15 start"
        elif decision == "GAP_DOWN":
            verdict = "⚠️ GAP DOWN — 10:15 start"
        elif decision == "GAP_UP_DISABLED":
            verdict = "⚠ GAP UP detected (rule OFF) — 9:45 start"
        elif decision == "GAP_DOWN_DISABLED":
            verdict = "⚠ GAP DOWN detected (rule OFF) — 9:45 start"
        elif decision == "GAP_DAY":  # legacy
            verdict = "⚠️ GAP DAY — 10:15 start"
        elif decision == "GAP_DETECTED_BUT_DISABLED":  # legacy
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
        # Phase 5.2: Insight line, populated only if the orchestrator
        # generated a short remark. Old callers (tests) still work.
        insight = (s.get("telegram_short_remark") or "").strip()
        insight_line = f"\nInsight: {insight}\n" if insight else "\n"
        cheap_warning = (s.get("cheap_option_warning") or "").strip()
        cheap_line = f"{cheap_warning}\n" if cheap_warning else ""
        # Phase 6.1: existing C0-C4 line, with an optional combined
        # C5 + Spot DI + Opt DI suffix when ADX data is present.
        conditions_line = "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓"
        c5_line = self._format_c5_line(s)
        if c5_line:
            conditions_line = f"{conditions_line} | {c5_line}"
        return (
            "🚨 SHORT COVER CASCADE SIGNAL\n"
            "─────────────────────────────\n"
            f"Instrument: {s['symbol']} {s['strike']} {s['option_type']}\n"
            f"Strike relation: {s['relation']}\n"
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
            f"{cheap_line}"
            f"{insight_line}"
            f"{conditions_line}\n"
            "─────────────────────────────\n"
            "ALERT ONLY — no order placed"
        )

    @staticmethod
    def _format_c5_line(s: dict) -> str:
        """Render the combined C5 + Spot DI + Opt DI line for the Telegram alert.

        Reads raw fields straight from the signal_record:
          adx, adx_prev, di_plus, di_minus, c5_passed,
          option_di_plus, option_di_minus, option_di_aligned,
          option_type ("CE" / "PE")

        Format (per Phase 6.1 follow-up spec):
          C5 ✓  ADX 24.1 ↑  |  Spot +DI>−DI ✓  Opt +DI>−DI ✓

        Spot DI label uses CE/PE context (CE: +DI>−DI aligned;
        PE: −DI>+DI aligned). Option DI label is direction-agnostic —
        we are always BUYING the option and want premium trending up,
        so it's always "+DI>−DI" (✓) or "+DI<−DI" (✗). Missing option
        DI (insufficient candles or compute error) renders as "Opt N/A".

        Returns "" when ADX inputs are absent (c5_adx disabled or both
        ADX values null) so the caller skips the C5 suffix entirely.
        """
        adx = s.get("adx")
        adx_prev = s.get("adx_prev")
        if adx is None or adx_prev is None:
            return ""

        arrow = "↑" if adx > adx_prev else "↓"
        c5_passed = s.get("c5_passed")
        c5_mark = "✓" if c5_passed else "❌"

        # Spot DI side: CE wants +DI>−DI, PE wants −DI>+DI.
        opt_type = (s.get("option_type") or "").upper()
        di_plus = s.get("di_plus")
        di_minus = s.get("di_minus")
        if di_plus is None or di_minus is None:
            spot_di = "Spot N/A"
        elif opt_type == "PE":
            if di_minus > di_plus:
                spot_di = "Spot −DI>+DI ✓"
            else:
                spot_di = "Spot −DI<+DI ✗"
        else:  # CE (default)
            if di_plus > di_minus:
                spot_di = "Spot +DI>−DI ✓"
            else:
                spot_di = "Spot +DI<−DI ✗"

        # Option DI is direction-agnostic — always want +DI > −DI.
        opt_di_plus = s.get("option_di_plus")
        opt_di_minus = s.get("option_di_minus")
        opt_aligned = s.get("option_di_aligned")
        if opt_di_plus is None or opt_di_minus is None or opt_aligned is None:
            opt_di = "Opt N/A"
        elif opt_aligned:
            opt_di = "Opt +DI>−DI ✓"
        else:
            opt_di = "Opt +DI<−DI ✗"

        return f"C5 {c5_mark}  ADX {adx:.1f} {arrow}  |  {spot_di}  {opt_di}"

    def _format_eod(self, s: dict) -> str:
        # Session window line — present when the orchestrator populated
        # session_started_at. Clarifies that counts cover only the
        # latest src.main run (relevant after a mid-day run.bat restart).
        started = s.get("session_started_at")
        if started:
            session_line = f"Session: since {started[11:16]} IST (this run only)\n"
        else:
            session_line = ""
        return (
            "📊 END-OF-DAY SUMMARY\n"
            "─────────────────────────────\n"
            f"Date: {s['date']}\n"
            f"{session_line}"
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
