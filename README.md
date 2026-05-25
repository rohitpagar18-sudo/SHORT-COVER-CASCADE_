# Short Cover Cascade

Telegram alert bot for the Short Cover Cascade strategy on NIFTY / BankNifty options. Multi-broker (Kite + Upstox), one active at a time.

## Current Phase

**Phase 0 — Project foundation.** Skeleton, config, multi-feed scaffolding. No strategy logic yet.

Roadmap is tracked in `CLAUDE.md` and `docs/phases/`.

## Setup

1. Clone or copy the project to a local folder (Windows path, e.g. `C:\trading\short-cover-cascade`).
2. Fill in `config/secrets.env`:
   - Either `KITE_API_KEY` + `KITE_API_SECRET` (if `feeds.active_feed: kite`)
   - Or `UPSTOX_API_KEY` + `UPSTOX_API_SECRET` + `UPSTOX_REDIRECT_URI` (if `feeds.active_feed: upstox`)
   - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (used from Phase 5 onward)
3. Refresh the access token for the broker you're using (see below).
4. Double-click `run.bat` (or run it from a terminal). The bat file will create a venv, install requirements, and start the bot.

## How to switch brokers

Edit `config/config.yaml`:

```yaml
feeds:
  active_feed: kite     # change to "upstox" to switch
```

Then restart the bot. The inactive broker's SDK is never imported.

## How to refresh tokens

```cmd
python scripts\refresh_token_kite.py
python scripts\refresh_token_upstox.py            # OAuth flow
python scripts\refresh_token_upstox.py --manual   # paste long-validity token
```

- **Kite**: SEBI forces daily refresh — run every trading morning.
- **Upstox**: 1-day OAuth, or paste a ~365-day token from the Upstox Analytics tab using `--manual`.

Both scripts update `KITE_/UPSTOX_ACCESS_TOKEN` and `_TOKEN_DATE` in `config/secrets.env`.

## Healthcheck

```cmd
python scripts\feed_healthcheck.py
```

In Phase 0 this prints a stub status; in Phase 1 it becomes a real connectivity check.

## Project layout

See the "Project Structure" section in `CLAUDE.md`.
