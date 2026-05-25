"""Manually refresh the Upstox access token.

Two flows:
  * Default (--oauth): standard v3 auth-code -> token exchange via HTTPS POST
  * Manual (--manual): for the long-validity (~365 day) token from the
    Upstox Analytics tab — paste the token directly.

Writes UPSTOX_ACCESS_TOKEN and UPSTOX_TOKEN_DATE back to config/secrets.env.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_PATH = PROJECT_ROOT / "config" / "secrets.env"

UPSTOX_AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"


def _update_env_file(env_path: Path, updates: dict[str, str]) -> None:
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


def _oauth_flow(api_key: str, api_secret: str, redirect_uri: str) -> str | None:
    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return None

    auth_params = {
        "client_id": api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
    }
    login_url = f"{UPSTOX_AUTH_URL}?{urlencode(auth_params)}"
    print("Step 1 — Open this URL in your browser and log in:")
    print(f"  {login_url}")
    print()
    print("Step 2 — After login, copy the 'code' value from the redirect URL.")
    print()
    auth_code = input("Paste auth code here: ").strip()
    if not auth_code:
        print("ERROR: auth code is empty", file=sys.stderr)
        return None

    try:
        resp = requests.post(
            UPSTOX_TOKEN_URL,
            data={
                "code": auth_code,
                "client_id": api_key,
                "client_secret": api_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
    except Exception as e:
        print(f"ERROR: token exchange request failed: {e}", file=sys.stderr)
        return None

    if resp.status_code != 200:
        print(f"ERROR: token exchange returned HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        return None

    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        print(f"ERROR: no access_token in response: {payload}", file=sys.stderr)
        return None
    return token


def _manual_flow() -> str | None:
    print("Manual mode — paste the long-validity access token from the Upstox Analytics tab.")
    token = input("Paste access token: ").strip()
    if not token:
        print("ERROR: token is empty", file=sys.stderr)
        return None
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Upstox access token")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Paste a long-validity token directly (skip OAuth)",
    )
    parser.add_argument(
        "--oauth",
        action="store_true",
        help="Force the OAuth code-exchange flow (default when --manual not set)",
    )
    args = parser.parse_args()

    load_dotenv(SECRETS_PATH)

    if args.manual:
        token = _manual_flow()
    else:
        api_key = os.getenv("UPSTOX_API_KEY", "").strip()
        api_secret = os.getenv("UPSTOX_API_SECRET", "").strip()
        redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "").strip()

        if not api_key or api_key == "your_upstox_api_key_here":
            print("ERROR: UPSTOX_API_KEY missing from config/secrets.env", file=sys.stderr)
            return 1
        if not api_secret or api_secret == "your_upstox_api_secret_here":
            print("ERROR: UPSTOX_API_SECRET missing from config/secrets.env", file=sys.stderr)
            return 1
        if not redirect_uri:
            print("ERROR: UPSTOX_REDIRECT_URI missing from config/secrets.env", file=sys.stderr)
            return 1
        token = _oauth_flow(api_key, api_secret, redirect_uri)

    if not token:
        return 1

    today = date.today().isoformat()
    _update_env_file(
        SECRETS_PATH,
        {"UPSTOX_ACCESS_TOKEN": token, "UPSTOX_TOKEN_DATE": today},
    )
    print()
    print(f"Upstox access token saved to {SECRETS_PATH}")
    print(f"UPSTOX_TOKEN_DATE={today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
