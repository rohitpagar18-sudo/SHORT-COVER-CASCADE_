# Short Cover Cascade — Trading Bot Project

## Project Goal
Build a Telegram alert bot for the Short Cover Cascade strategy on
NIFTY/BankNifty options. Strategy is fully specified in
docs/ShortCoverCascade_v3_1_FINAL.md — ALWAYS read it before writing
any condition or risk logic.

Roadmap:
- Phase 1: Multi-feed data layer (Kite + Upstox)
- Phase 2: Indicator calculations
- Phase 3: 5 conditions C0–C4
- Phase 4: Risk + State modules
- Phase 5: Telegram alerts + main orchestrator (ALERT-ONLY)
- Phase 6: 30 trading-day live alert-only validation (no coding)
- Phase 7: Backtest harness on collected signals.jsonl
- Phase 8: Order placement (only after Phase 6 passes)

## Phase Documents
Each phase has a doc at docs/phases/PHASE_N.md.
Read the relevant phase doc fully before starting work on it.
Do not skip ahead. Do not combine phases.

## Broker Feeds — One active at a time
- Active feed selected via config/config.yaml -> feeds.active_feed
- Possible values: "kite" or "upstox"
- The non-active feed must do ZERO API calls, ZERO token refresh, ZERO network activity
- Switching brokers = change config + restart bot. No code changes.
- Tokens refreshed manually via scripts/refresh_token_kite.py or
  scripts/refresh_token_upstox.py (no browser automation in the bot itself)
- Upstox can use a ~1-year token from its Analytics tab (set
  token_validity_days: 365 to skip daily refresh prompts)
- Kite forces daily token refresh (SEBI rule for individuals)
- Manual feed healthcheck: scripts/feed_healthcheck.py — run before market

## Master Control File
All strategy behavior is controlled by config/config.yaml.
NEVER hardcode strategy numbers in source files.
Every threshold, toggle, time, and target reads from config.

The bot reads config.yaml at startup AND between each 5-minute candle scan.
Exception: order_place_mode change requires explicit bot restart for safety.
Exception: feeds.active_feed change requires explicit bot restart.

## Tech Stack
- Python 3.11+ on native Windows
- Broker SDKs (one active at a time):
  - upstox-python-sdk>=2.27.0
  - kiteconnect>=5.0.1
- python-telegram-bot for alerts
- pandas, numpy for indicators
- pytest for testing
- pydantic for config validation
- loguru for logging
- pyyaml for config parsing
- python-dotenv for secrets

## Coding Rules
1. Never hardcode numbers — read from config/config.yaml
2. Every condition (C0–C4) is a pure function returning (bool, reason_str)
3. All signals MUST log to logs/signals.jsonl BEFORE any Telegram alert
4. No order placement code until Phase 8 explicitly approved
5. Write unit tests for every condition and risk function
6. Mock broker APIs in tests — never hit live API in tests
7. Use type hints everywhere
8. Use loguru, not print()
9. All times are IST (Asia/Kolkata) — never use UTC or naive datetimes
10. State (daily SL count, cooldowns, killed strikes) persists to disk

## Multi-Feed Architecture Rules
1. src/data/base_feed.py defines an abstract interface (ABC).
   All broker code implements this interface.
2. Strategy/condition/orchestrator code NEVER imports upstox or kite
   directly. It only calls methods on the BaseFeed object.
3. src/data/feed_factory.py reads config and returns the right feed.
4. Only the active feed is imported and instantiated at runtime.
   The inactive feed's SDK is never even loaded (lazy imports).
5. Each feed implementation lives in its own file (upstox_feed.py,
   kite_feed.py) — never mixed.

## Critical Safety Rules
- ALL toggles default to safe state (alert_mode ON, order_place_mode OFF)
- Bot refuses to start if config is missing any required field
- Bot refuses to start if active feed's token is invalid/expired
- Daily counters persist to logs/state.json — survive bot restart
- 9:15 AM lot size verification is MANDATORY before any signal scan
- 3:00 PM hard square-off cannot be disabled in code
- Bot sends Telegram startup alert with current config summary
  (including active broker name)
- Bot sends Telegram alert on any unhandled exception

## Expiry Day Rules — NSE/SEBI 2024–2025 reform

Authoritative reference: docs/expiry_calendar.md (includes 2026 calendar
and holiday-shift handling).

| Index     | Weekly        | Monthly                          |
|-----------|---------------|----------------------------------|
| NIFTY     | **Tuesday**   | Last Tuesday of the month        |
| BankNifty | None — discontinued 2024-11-20 | Last Tuesday of the month |
| BSE Sensex | Thursday (not traded — BSE) | (not traded)         |

- NIFTY weekly expiry day moved to Tuesday on **2025-09-02** (SEBI circular,
  superseding earlier Monday plan). Do NOT use Thursday or Monday.
- Weekly BankNifty options were **discontinued on 2024-11-20**. Only the
  monthly BankNifty contract exists. For BankNifty, "this week's expiry"
  is always the current-month last Tuesday (rolling on the day after
  expiry into next month's last Tuesday).
- **Holiday shift:** if the Tuesday expiry falls on an NSE trading
  holiday, the contract expires on the **previous trading day**.
- The strategy's "Expiry Day" mode (different TP multipliers per
  config.yaml `risk_reward.expiry_day_tp*_r`) applies only on the actual
  expiry trading day (calendar Tuesday adjusted for holidays).

### Phase 3+ rule
Every code path that picks an expiry — strike selection, candle
fetch, signal log fields, backtest harness — must go through a single
helper `get_next_expiry(symbol: str, today: date) -> date` that follows
the rules above. Never hardcode a weekday. Keep the weekday config-driven
so a future regulator change doesn't require a code release:

```yaml
instruments:
  nifty_weekly_expiry_day: tuesday  # SEBI 2025-09-02
  banknifty_monthly_expiry_day: tuesday  # last <day> of month
  # BankNifty weekly: none — discontinued 2024-11-20
```

## Indicator Calculation Standards

These formulas are confirmed from real Upstox/TradingView chart screenshots.
Do NOT use alternative formulas without explicit approval.

### VWAP — CRITICAL: use hlc3, NOT close-only
- Type: Session-anchored, resets at 9:15 AM IST every day
- Price input: (High + Low + Close) / 3  ← hlc3, NOT close-only
- Formula: cumsum(hlc3 * volume) / cumsum(volume)
- Reset trigger: First candle of new trading session
- Confirmed source: Upstox chart label "VWAP hlc3 Session"

Common bug to avoid: Many Python VWAP examples use close * volume.
This is WRONG for our strategy. Must use (H+L+C)/3 * volume.

### RSI(14)
- Period: 14 candles
- Smoothing: Wilder's smoothing (RMA — Running Moving Average)
- NOT Simple MA, NOT Exponential MA
- pandas implementation: ewm(alpha=1/14, adjust=False).mean() on gains/losses

### Moving Averages
- OI MA(20): Simple MA on 20 most recent candles' OI values
- Volume MA(20): Simple MA on 20 most recent candles' volume
- RSI MA(20): Simple MA on 20 most recent RSI(14) values
- All SMA — NOT EMA, NOT Wilder's

### Known-Good Test Values
docs/known_indicator_values.md contains real candle data from
Upstox/TradingView screenshots. Use as test fixtures in Phase 2.

### Calibration Acceptance Threshold
- VWAP: ±0.5%
- RSI: ±2 points
- MAs: ±1%

## Project Structure
C:\trading\short-cover-cascade\
├── docs\                — Strategy doc, indicator values, phase docs (read-only)
│   └── phases\          — PHASE_0.md, PHASE_1.md, ...
├── config\              — config.yaml + secrets.env
├── scripts\             — Token refresh + feed healthcheck (run manually)
├── src\
│   ├── data\            — base_feed.py, upstox_feed.py, kite_feed.py, feed_factory.py
│   ├── indicators\      — VWAP, RSI, OI MA, Volume MA (Phase 2)
│   ├── conditions\      — C0–C4 pure functions (Phase 3)
│   ├── risk\            — SL, lots, TP (Phase 4)
│   ├── state\           — Counters, cooldowns, killed strikes (Phase 4)
│   ├── alerts\          — Telegram (Phase 5)
│   ├── orders\          — Order placement (Phase 8 ONLY)
│   ├── backtest\        — Forward-data backtest harness (Phase 7)
│   ├── config_loader.py — Pydantic config validator
│   └── main.py          — Orchestrator
├── logs\                — signals.jsonl, alerts.jsonl, state.json, bot.log
├── tests\               — pytest unit tests
├── run.bat              — Windows launcher
└── CLAUDE.md            — This file

## Current Phase
Phase 3: Conditions C0–C4 + dynamic expiry helper (code complete on this
machine; awaiting live calibration on second laptop).
(Update this line as we progress)

## Phase Status
- Phase 0: Project foundation — DONE. Verified on second laptop, ran perfectly.
- Phase 1: Multi-feed data layer — DONE. Verified on second laptop, ran perfectly.
- Phase 2: Indicator calculations — code + unit tests done on this machine
  (all 10 indicator tests + 26 total tests pass). Live calibration against
  Kite chart still to be done on the second laptop during market hours.
- Phase 3: Conditions C0–C4 + expiry resolver — code + unit tests done on
  this machine (74 total tests pass: 26 prior + 31 condition tests +
  17 expiry-resolver tests). Live calibration via
  scripts/check_conditions.py and scripts/list_expiries.py still to be
  done on the second laptop during market hours.

## How Phases Work
- Each phase has a doc in docs/phases/
- Read the phase doc completely before starting
- Implement exactly what the phase doc asks — nothing more, nothing less
- At end of each phase, run the verification checklist
- Do not begin a later phase until told explicitly