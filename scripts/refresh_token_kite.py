"""Manually refresh the Kite (Zerodha) access token.

Kite forces daily token refresh (SEBI rule). Run this every trading morning
before market open. Writes KITE_ACCESS_TOKEN and KITE_TOKEN_DATE back to
config/secrets.env.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"


def _update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Update or append KEY=VALUE lines in a .env file, preserving order/comments."""
    if not env_path.exists():
        raise FileNotFoundError(f"secrets.env not found at {env_path}")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for k, v in remaining.items():
        out.append(f"{k}={v}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    load_dotenv(SECRETS_PATH)
    api_key = os.getenv("KITE_API_KEY", "").strip()
    api_secret = os.getenv("KITE_API_SECRET", "").strip()

    if not api_key or api_key == "your_kite_api_key_here":
        print("ERROR: KITE_API_KEY missing from config/secrets.env", file=sys.stderr)
        return 1
    if not api_secret or api_secret == "your_kite_api_secret_here":
        print("ERROR: KITE_API_SECRET missing from config/secrets.env", file=sys.stderr)
        return 1

    try:
        from kiteconnect import KiteConnect
    except ImportError:
        print(
            "ERROR: kiteconnect not installed. Run: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()
    print("Step 1 — Open this URL in your browser and log in:")
    print(f"  {login_url}")
    print()
    print("Step 2 — After login, copy the 'request_token' value from the redirect URL.")
    print("         (It looks like: https://localhost/?request_token=XXXXX&action=login&status=success)")
    print()
    request_token = input("Paste request_token here: ").strip()
    if not request_token:
        print("ERROR: request_token is empty", file=sys.stderr)
        return 1

    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
    except Exception as e:
        print(f"ERROR: token exchange failed: {e}", file=sys.stderr)
        return 1

    access_token = session.get("access_token")
    if not access_token:
        print("ERROR: no access_token in Kite response", file=sys.stderr)
        return 1

    today = date.today().isoformat()
    _update_env_file(
        SECRETS_PATH,
        {"KITE_ACCESS_TOKEN": access_token, "KITE_TOKEN_DATE": today},
    )
    print()
    print(f"Kite access token refreshed and saved to {SECRETS_PATH}")
    print(f"KITE_TOKEN_DATE={today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
