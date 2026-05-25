"""Manually refresh the Kite (Zerodha) access token.

Kite forces daily token refresh (SEBI rule). Run this every trading morning
before market open. Writes KITE_ACCESS_TOKEN and KITE_TOKEN_DATE back to
config/secrets.env.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import date
from pathlib import Path

from dotenv import load_dotenv, set_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def main() -> int:
    try:
        if not SECRETS_PATH.exists():
            print(f"ERROR: secrets file not found at {SECRETS_PATH}", file=sys.stderr)
            return 1

        load_dotenv(SECRETS_PATH)
        api_key = os.getenv("KITE_API_KEY", "").strip()
        api_secret = os.getenv("KITE_API_SECRET", "").strip()

        if not api_key or api_key == "your_kite_api_key_here":
            print(
                "KITE_API_KEY missing from config/secrets.env — "
                "fill it in before running this script",
                file=sys.stderr,
            )
            return 1
        if not api_secret or api_secret == "your_kite_api_secret_here":
            print(
                "KITE_API_SECRET missing from config/secrets.env — "
                "fill it in before running this script",
                file=sys.stderr,
            )
            return 1

        from kiteconnect import KiteConnect

        kite = KiteConnect(api_key=api_key)
        print(kite.login_url())
        print(
            "Open this URL in Chrome. After login, copy the request_token "
            "from the redirect URL and paste it below."
        )
        request_token = input("request_token: ").strip()
        if not request_token:
            print("ERROR: request_token is empty", file=sys.stderr)
            return 1

        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data["access_token"]

        today = date.today().isoformat()
        set_key(str(SECRETS_PATH), "KITE_ACCESS_TOKEN", access_token)
        set_key(str(SECRETS_PATH), "KITE_TOKEN_DATE", today)

        print(
            "Kite token saved. Valid for today only. Run this script again "
            "tomorrow morning before 9:15 AM."
        )
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
