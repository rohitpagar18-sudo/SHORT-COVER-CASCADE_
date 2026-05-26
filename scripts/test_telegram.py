"""Telegram sanity test.

Run BEFORE the first live bot start to verify TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are wired up.

Usage::

    python scripts/test_telegram.py

On success: a test message lands in your Telegram chat.
On failure: troubleshooting tips are printed.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"

from src.config_loader import load_secrets


def _print_troubleshooting() -> None:
    print()
    print("Troubleshooting tips:")
    print("  1. Check TELEGRAM_BOT_TOKEN in config/secrets.env — format like")
    print("     7891234567:AAH...xyz, no quotes, no spaces.")
    print("  2. Check TELEGRAM_CHAT_ID — must be a numeric id (e.g. 123456789).")
    print("     Get it via @userinfobot in Telegram.")
    print("  3. Did you send /start to the bot first? Telegram blocks")
    print("     unsolicited messages — open your bot in Telegram, click Start,")
    print("     send any 'hi' message, then retry this script.")
    print("  4. Verify with curl directly:")
    print("       curl \"https://api.telegram.org/bot<TOKEN>/sendMessage"
          "?chat_id=<CHAT_ID>&text=test\"")


def main() -> int:
    try:
        load_secrets(SECRETS_PATH)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        from src.alerts.telegram_bot import TelegramAlerter
    except Exception as e:
        print(f"ERROR: failed to import TelegramAlerter: {e}", file=sys.stderr)
        return 1

    try:
        alerter = TelegramAlerter()
    except Exception as e:
        print(f"ERROR: failed to construct TelegramAlerter: {e}", file=sys.stderr)
        _print_troubleshooting()
        return 1

    message = (
        "🧪 Telegram test from Short Cover Cascade Bot.\n"
        "If you see this, your setup works."
    )
    print("Sending test message...")
    ok = alerter.send(message)
    if ok:
        print("SUCCESS: test message sent. Check your Telegram chat.")
        return 0

    print("FAILED: Telegram send returned False.", file=sys.stderr)
    _print_troubleshooting()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
