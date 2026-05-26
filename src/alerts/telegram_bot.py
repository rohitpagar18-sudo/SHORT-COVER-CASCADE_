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
        """Send a raw message. Returns True on success, False on failure.

        Uses a fresh event loop per call so it remains safe in mixed
        sync/async environments.
        """
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
        gap_str = " | GAP DAY (10:15 start)" if c.get("is_gap_day") else ""
        return (
            "🚀 SHORT COVER CASCADE BOT STARTED\n"
            "─────────────────────────────\n"
            f"Time: {self._now_ist()}\n"
            f"Active broker: {c['broker']}\n"
            f"Mode: alert={c['alert_mode']} | order={c['order_place_mode']} | "
            f"paper={c['paper_trade_mode']}\n"
            f"Instruments: {c['instruments']}{gap_str}\n"
            f"India VIX: {c['vix']:.2f} ({c['vix_regime']})\n"
            f"Lot sizes: NIFTY={c['nifty_lot']}, BankNifty={c['banknifty_lot']}\n"
            "─────────────────────────────"
        )

    def _format_signal(self, s: dict) -> str:
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
