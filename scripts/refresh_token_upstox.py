"""Manually refresh the Upstox access token.

Two modes:
  --manual  : Paste a long-validity token from the Upstox Analytics tab.
  (default) : Standard OAuth code-exchange flow.

Writes UPSTOX_ACCESS_TOKEN and UPSTOX_TOKEN_DATE back to config/secrets.env.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from dotenv import load_dotenv, set_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"

UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def _save_token(token: str) -> None:
    today = date.today().isoformat()
    set_key(str(SECRETS_PATH), "UPSTOX_ACCESS_TOKEN", token)
    set_key(str(SECRETS_PATH), "UPSTOX_TOKEN_DATE", today)
    print(f"Upstox access token saved to {SECRETS_PATH}")
    print(f"UPSTOX_TOKEN_DATE={today}")


def _manual_flow() -> int:
    token = input("Paste your Upstox access token: ").strip()
    if not token:
        print("ERROR: token is empty", file=sys.stderr)
        return 1
    _save_token(token)
    print("Manual token saved. Update annually if using long-validity token.")
    return 0


def _oauth_flow() -> int:
    api_key = os.getenv("UPSTOX_API_KEY", "").strip()
    api_secret = os.getenv("UPSTOX_API_SECRET", "").strip()
    redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "").strip()

    if not api_key or api_key == "your_upstox_api_key_here":
        print(
            "UPSTOX_API_KEY missing from config/secrets.env — "
            "fill it in before running this script",
            file=sys.stderr,
        )
        return 1
    if not api_secret or api_secret == "your_upstox_api_secret_here":
        print(
            "UPSTOX_API_SECRET missing from config/secrets.env — "
            "fill it in before running this script",
            file=sys.stderr,
        )
        return 1
    if not redirect_uri:
        print(
            "UPSTOX_REDIRECT_URI missing from config/secrets.env — "
            "fill it in before running this script",
            file=sys.stderr,
        )
        return 1

    auth_params = {
        "client_id": api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
    }
    login_url = f"{UPSTOX_AUTH_URL}?{urlencode(auth_params)}"
    print("Open this URL in your browser and log in:")
    print(f"  {login_url}")
    print()
    print(
        "After login, the browser will redirect to your redirect_uri with "
        "?code=XXXX appended. Paste the FULL redirect URL below."
    )
    full_url = input("redirect URL: ").strip()
    if not full_url:
        print("ERROR: redirect URL is empty", file=sys.stderr)
        return 1

    parsed = urlparse(full_url)
    qs = parse_qs(parsed.query)
    code_list = qs.get("code", [])
    if not code_list or not code_list[0]:
        print(
            "ERROR: could not extract 'code' parameter from redirect URL",
            file=sys.stderr,
        )
        return 1
    auth_code = code_list[0].strip()

    import requests

    resp = requests.post(
        UPSTOX_TOKEN_URL,
        data={
            "code": auth_code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(
            f"ERROR: token exchange returned HTTP {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        return 1
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        print(f"ERROR: no access_token in response: {payload}", file=sys.stderr)
        return 1

    _save_token(token)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Upstox access token")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Paste a long-validity token directly (skip OAuth)",
    )
    args = parser.parse_args()

    try:
        if not SECRETS_PATH.exists():
            print(f"ERROR: secrets file not found at {SECRETS_PATH}", file=sys.stderr)
            return 1
        load_dotenv(SECRETS_PATH)

        if args.manual:
            return _manual_flow()
        return _oauth_flow()
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
