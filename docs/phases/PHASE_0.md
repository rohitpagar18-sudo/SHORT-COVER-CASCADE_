# Phase 0 — Project Foundation Setup (v2, Multi-Feed Edition)

**Goal:** Set up the complete project skeleton, multi-broker feed structure (Upstox + Kite), config, token-refresh scripts, and Claude Code memory so all later phases have a clean foundation.

**Time estimate:** 45–60 minutes.

**Output:** Working project folder. Running `run.bat` prints a startup banner showing the active broker and all mode settings. Zero strategy logic yet.

**What's new vs the old Phase 0:**
- Multi-feed support baked in from day 1 (Kite + Upstox, one active at a time)
- Active feed is whichever you set in `config.yaml`; the other does no API calls
- Token refresh scripts in `scripts/` for both brokers (Kite forced daily, Upstox 365-day)
- Standalone feed healthcheck script you run manually before market
- Native Windows paths, `run.bat` instead of `run.sh`
- `src/backtest/` folder reserved for future use
- `docs/phases/` folder for these phase documents

---

## STEP 1 — Create the project folder

Open VS Code, then open a terminal (`Ctrl + ` `` ` ` ``). Run:

```cmd
mkdir C:\trading\short-cover-cascade
cd C:\trading\short-cover-cascade
code .
```

The last line reopens VS Code rooted at the project folder. From now on, every terminal command runs from `C:\trading\short-cover-cascade`.

---

## STEP 2 — Copy your strategy doc into the project

In the project folder, create `docs\`:

```cmd
mkdir docs
mkdir docs\phases
```

Then **manually copy these files** into `docs\` using File Explorer (or `copy` command):

- `ShortCoverCascade_v3_1_FINAL.docx`
- `ShortCoverCascade_v3_1_FINAL.md` (the markdown export)

And copy **this very file** you're reading into `docs\phases\PHASE_0.md`. Future phases go in the same folder.

Expected:

```
docs\
├── ShortCoverCascade_v3_1_FINAL.docx
├── ShortCoverCascade_v3_1_FINAL.md
└── phases\
    └── PHASE_0.md
```

---

## STEP 3 — Create CLAUDE.md (project memory)

Create `C:\trading\short-cover-cascade\CLAUDE.md` with the content below. This is the single most important file — Claude Code reads it every session.

```markdown
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
Phase 0: Project foundation setup
(Update this line as we progress)

## How Phases Work
- Each phase has a doc in docs/phases/
- Read the phase doc completely before starting
- Implement exactly what the phase doc asks — nothing more, nothing less
- At end of each phase, run the verification checklist
- Do not begin a later phase until told explicitly
```

---

## STEP 4 — Create config.yaml

Create `C:\trading\short-cover-cascade\config\config.yaml`:

```yaml
# =====================================================
# SHORT COVER CASCADE — MASTER CONTROL FILE
# Bot reads config at startup AND between each 5-min candle scan.
# Exceptions (require restart): order_place_mode, feeds.active_feed
# =====================================================

# ---------- BROKER FEED SELECTION ----------
feeds:
  active_feed: kite               # kite OR upstox
  healthcheck_timeout_seconds: 10
  upstox:
    enabled: ON
    token_validity_days: 365      # 1 = daily refresh, 365 = analytics-tab long token
  kite:
    enabled: ON
    token_validity_days: 1        # Kite forces daily (SEBI)

# ---------- MODE CONTROLS (most-changed) ----------
mode:
  alert_mode: ON                  # ON = send Telegram alerts
  order_place_mode: OFF           # OFF = no orders placed (default until Phase 8)
  paper_trade_mode: ON            # ON = simulate orders, log only

# ---------- INSTRUMENT SELECTION ----------
instruments:
  nifty_enabled: ON
  banknifty_enabled: ON
  nifty_lot_size: 65              # Auto-verified at 9:15 AM
  banknifty_lot_size: 30          # Auto-verified at 9:15 AM

# ---------- STOP LOSS ----------
stop_loss:
  method: 1                       # 1 = point buffer, 2 = percentage
  use_vix_multiplier: ON
  hard_exit_red_candle_below_vwap: ON

# ---------- RISK / REWARD ----------
risk_reward:
  target_risk_per_trade: 3000
  risk_range_min: 2500
  risk_range_max: 3500
  normal_day_tp1_r: 1.5
  normal_day_tp2_r: 2.5
  expiry_day_tp1_r: 2.0
  expiry_day_tp2_r: 3.0
  move_sl_to_breakeven_after_tp1: ON
  trail_sl_after_tp1: OFF

# ---------- POSITION SIZING ----------
position_sizing:
  lot_cap_enabled: ON
  nifty_max_lots: 5
  banknifty_max_lots: 3

# ---------- DAILY CIRCUIT BREAKERS ----------
circuit_breakers:
  daily_sl_count_breaker: ON
  max_sl_per_day: 2
  daily_loss_breaker: ON
  max_loss_per_day_rupees: 6000

# ---------- ORDER PLACEMENT ----------
orders:
  order_type: limit               # limit OR market
  cancel_if_price_touches_tp1: ON
  fallback_to_market_if_limit_disabled: ON

# ---------- TIME RULES ----------
time_rules:
  normal_start_time: "09:45"
  gap_day_start_time: "10:15"
  gap_day_filter_enabled: ON
  gap_threshold_percent: 1.0
  last_entry_time: "14:30"
  soft_squareoff_time: "14:55"
  hard_squareoff_time: "15:00"    # Cannot be disabled in code

# ---------- RE-ENTRY RULES ----------
re_entry:
  cooldown_minutes_after_sl: 15
  same_strike_kill_after_2_sl: ON

# ---------- STRIKE SELECTION ----------
strike:
  max_deviation_from_atm: 1
  late_entry_threshold_percent: 30

# ---------- CONDITION THRESHOLDS ----------
conditions:
  c3_rsi_min: 50
  c3_rsi_max: 80

# ---------- ALERTS ----------
telegram:
  send_signal_alerts: ON
  send_rejection_alerts: OFF
  send_eod_summary: ON
  send_circuit_breaker_alerts: ON
  send_startup_alert: ON

# ---------- LOGGING ----------
logging:
  log_level: INFO
  log_every_signal_check: ON
  log_indicator_values: ON

# ---------- BOT BEHAVIOR ----------
bot:
  scan_buffer_seconds: 5
  api_retry_count: 3
  api_retry_delay_seconds: 2
  state_persistence_enabled: ON
```

---

## STEP 5 — Create known_indicator_values.md

Create `C:\trading\short-cover-cascade\docs\known_indicator_values.md` with the content from your existing notes (the candle 1–5 reference data). If you already have this file, copy it across.

If you don't have it ready, paste the full block from the previous Phase 0 doc — Claude Code will need it in Phase 2.

---

## STEP 6 — Create secrets.env

Create `C:\trading\short-cover-cascade\config\secrets.env`:

```
# ===== KITE (Zerodha) =====
KITE_API_KEY=your_kite_api_key_here
KITE_API_SECRET=your_kite_api_secret_here
KITE_ACCESS_TOKEN=
KITE_TOKEN_DATE=

# ===== UPSTOX =====
UPSTOX_API_KEY=your_upstox_api_key_here
UPSTOX_API_SECRET=your_upstox_api_secret_here
UPSTOX_REDIRECT_URI=https://localhost
UPSTOX_ACCESS_TOKEN=
UPSTOX_TOKEN_DATE=

# ===== TELEGRAM =====
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

Fill in whatever you have now. Leave the rest blank — the refresh scripts will fill in `ACCESS_TOKEN` and `TOKEN_DATE` fields when you run them.

**The `_TOKEN_DATE` fields store the date the token was last refreshed.** Kite's refresh script sets it daily. Upstox's sets it once per year. This is how the bot checks if your token is fresh at startup.

---

## STEP 7 — Create .gitignore

Create `C:\trading\short-cover-cascade\.gitignore`:

```
config/secrets.env
logs/
__pycache__/
*.pyc
.venv/
venv/
.env
.pytest_cache/
*.egg-info/
.vscode/
```

---

## STEP 8 — Paste this prompt into Claude Code

In the VS Code terminal, run:

```cmd
claude
```

Then paste this entire block:

````
Read CLAUDE.md and docs/ShortCoverCascade_v3_1_FINAL.md completely before writing any code. Then read docs/phases/PHASE_0.md to understand the full Phase 0 scope. Also note docs/known_indicator_values.md exists for later Phase 2 reference — do not use it yet.

PHASE 0 SCOPE — Build the project skeleton ONLY. No strategy logic, no broker API calls, no indicators, no conditions.

Tasks:

1. Create the folder structure exactly as specified in CLAUDE.md "Project Structure" section. Create empty __init__.py files in every Python package directory under src/.

2. Create requirements.txt with:
   upstox-python-sdk>=2.27.0
   kiteconnect>=5.0.1
   python-telegram-bot>=21.0
   pandas>=2.0
   numpy>=1.24
   pytest>=8.0
   pydantic>=2.5
   loguru>=0.7
   pyyaml>=6.0
   python-dotenv>=1.0
   requests>=2.31

3. Create pyproject.toml minimally configured for the project.

4. Create src/config_loader.py using pydantic v2:
   - One pydantic model per config section (FeedsConfig, ModeConfig, InstrumentsConfig, StopLossConfig, RiskRewardConfig, PositionSizingConfig, CircuitBreakersConfig, OrdersConfig, TimeRulesConfig, ReEntryConfig, StrikeConfig, ConditionsConfig, TelegramConfig, LoggingConfig, BotConfig)
   - One top-level AppConfig model that nests all of them
   - Parser converts ON/OFF strings to bool automatically
   - Validators:
     * feeds.active_feed must be exactly "kite" or "upstox"
     * If feeds.active_feed == "kite", feeds.kite.enabled must be ON
     * If feeds.active_feed == "upstox", feeds.upstox.enabled must be ON
     * All numeric ranges sane (max_lots > 0, tp_r > 0, etc.)
     * Time strings parse as HH:MM
   - Function load_config(path) returns AppConfig
   - Raise ConfigError (custom exception) with clear messages on failure

5. Create src/data/base_feed.py — abstract base class with these methods, all raising NotImplementedError:
   - connect() -> bool : authenticate and verify token
   - is_token_valid() -> bool
   - get_lot_size(symbol: str) -> int : symbol in {"NIFTY", "BANKNIFTY"}
   - get_spot_price(symbol: str) -> float
   - get_5min_candles(instrument_key: str, n_candles: int) -> pd.DataFrame : columns = [timestamp, open, high, low, close, volume, oi]
   - get_option_chain(symbol: str, expiry: str) -> pd.DataFrame
   - get_india_vix() -> float
   - get_atm_strike(symbol: str) -> int
   - get_broker_name() -> str
   Use Python ABC. Document expected return shapes in docstrings.

6. Create src/data/upstox_feed.py and src/data/kite_feed.py — both subclass BaseFeed. EVERY method raises NotImplementedError with comment "TODO: Phase 1". The imports for the SDKs go INSIDE the methods (lazy import) so importing the file does not load the SDK.

7. Create src/data/feed_factory.py:
   - Function get_feed(config: AppConfig) -> BaseFeed
   - Reads config.feeds.active_feed
   - If "kite": imports and returns KiteFeed
   - If "upstox": imports and returns UpstoxFeed
   - Else: raises ConfigError
   - CRITICAL: Only the active feed's module is imported. The inactive one is never touched.

8. Create src/state/state_manager.py with stub functions raising NotImplementedError with "TODO: Phase 4" comments:
   load_state(), save_state(), increment_sl_count(), reset_daily_state(), is_strike_killed(strike), kill_strike(strike), add_loss(amount), get_daily_sl_count(), get_daily_loss(), get_cooldown_until()

9. Create scripts/refresh_token_kite.py:
   - Loads .env
   - If KITE_API_KEY missing, prints clear error and exits
   - Generates Kite login URL, prints it, asks user to open in browser
   - Reads request_token from user input
   - Exchanges it for access_token via kiteconnect
   - Writes KITE_ACCESS_TOKEN and KITE_TOKEN_DATE=YYYY-MM-DD back to secrets.env
   - Prints confirmation

10. Create scripts/refresh_token_upstox.py:
    - Same flow but for Upstox v3 auth code -> token exchange
    - Note: For the long-validity token from Upstox Analytics tab, the script
      should accept the user pasting the token directly (--manual flag)
    - Writes UPSTOX_ACCESS_TOKEN and UPSTOX_TOKEN_DATE back to secrets.env

11. Create scripts/feed_healthcheck.py:
    - Loads config and secrets
    - Reads the ACTIVE feed only
    - Instantiates the feed via feed_factory
    - Note: in Phase 0, connect() raises NotImplementedError — that's expected
    - Script should catch NotImplementedError and print:
      "Active feed: <name> | Status: Phase 0 stub (connection logic comes in Phase 1)"
    - In Phase 1 this script becomes a real connectivity test

12. Create src/main.py that:
    - Loads config/config.yaml via config_loader
    - Loads config/secrets.env via python-dotenv
    - Configures loguru to write to logs/bot.log
    - Prints a startup banner showing:
      * Active broker (from config.feeds.active_feed)
      * Current mode (alert_mode, order_place_mode, paper_trade_mode)
      * Enabled instruments
      * Token date for active broker only (from secrets.env)
    - Validates that active broker's token date is present in secrets
      (does NOT validate token freshness yet — that's Phase 1)
    - Prints "Phase 0 setup complete — bot foundation ready"
    - Exits cleanly
    - DO NOT instantiate the feed or hit any API in Phase 0

13. Create run.bat for Windows:
    @echo off
    if not exist venv\Scripts\activate.bat (
      python -m venv venv
      call venv\Scripts\activate.bat
      pip install -r requirements.txt
    ) else (
      call venv\Scripts\activate.bat
    )
    python -m src.main

14. Create README.md with:
    - Project title and one-line description
    - Setup steps (clone, fill secrets.env, run.bat)
    - Current phase status
    - How to switch brokers (edit config.yaml -> feeds.active_feed, restart)
    - How to refresh tokens (scripts/refresh_token_kite.py daily, upstox once a year)

15. Create empty placeholder files so future phases have homes:
    - src/indicators/__init__.py (Phase 2)
    - src/conditions/__init__.py (Phase 3)
    - src/risk/__init__.py (Phase 4)
    - src/alerts/__init__.py (Phase 5)
    - src/orders/__init__.py (Phase 8)
    - src/backtest/__init__.py (Phase 7)
    - tests/__init__.py

DO NOT WRITE:
- Any indicator calculation
- Any condition logic
- Any order placement code
- Any actual SDK calls (everything raises NotImplementedError)
- Any Telegram code beyond an empty alerts/__init__.py

After creating everything, run `python -m src.main` once and confirm the banner appears with "Active broker: kite" (since config.yaml has active_feed: kite). Report what you created, any issues, and the exact banner output.
````

---

## STEP 9 — Verification Checklist

After Claude Code finishes, manually verify:

| # | Check | Command |
|---|---|---|
| 1 | Folder structure correct | `tree /F /A` from project root |
| 2 | All `__init__.py` files exist | Check each subfolder of `src\` |
| 3 | `run.bat` exists and runs | Double-click or `run.bat` in terminal |
| 4 | Startup banner shows `Active broker: kite` | Output of `run.bat` |
| 5 | Banner shows `order_place_mode: OFF` | Same output |
| 6 | Switch to Upstox works | Edit `config.yaml`: `active_feed: upstox`, run again — banner should now show `Active broker: upstox` |
| 7 | Switch back to Kite | Edit back to `kite`, run again |
| 8 | Bad config rejected | Set `active_feed: hdfc` (invalid), run — should fail with clear `ConfigError` |
| 9 | Healthcheck stub works | `python scripts\feed_healthcheck.py` — should print "Phase 0 stub" message, not crash |
| 10 | Inactive feed SDK not loaded | If you remove the upstox-python-sdk install, running with `active_feed: kite` should still work fine (only Kite imports) |
| 11 | `logs\` exists, `bot.log` created | After running `run.bat` |
| 12 | `.gitignore` in place | `type .gitignore` |
| 13 | No strategy logic anywhere | Search src for "rsi", "vwap", "telegram_bot" — should find nothing functional |
| 14 | `CLAUDE.md` readable | `type CLAUDE.md` shows the project memory |

**If all 14 are green → Phase 0 complete. Tell me and I'll write Phase 1 (data feed implementation for both Kite and Upstox).**

If any fail, paste the error and Claude Code's last output. We debug before moving on.

---

## Phase 0 Deliverable Summary

When Phase 0 is done you have:

- Complete Windows-friendly folder at `C:\trading\short-cover-cascade\`
- One master config file controlling everything
- CLAUDE.md with project memory and indicator standards
- Abstract `BaseFeed` interface — strategy code stays broker-agnostic forever
- Stub `UpstoxFeed` and `KiteFeed` (raise NotImplementedError, Phase 1 fills them in)
- Lazy-import feed factory — inactive broker SDK never loads
- Token refresh scripts for both brokers
- Manual feed healthcheck script
- Working `run.bat` launcher
- `secrets.env` with token-date tracking
- Empty placeholder modules for every future phase
- Zero strategy logic (intentional)

Time check: if Phase 0 took more than 60 minutes, something's wrong. Send me what happened.

---

## Questions I'll ask after you finish Phase 0

To kick off Phase 1 I'll need:

1. Did `run.bat` print the banner correctly? Paste the exact output.
2. Does your Kite API subscription have F&O enabled? (Required for option chain access)
3. For Upstox, do you want to use the 1-year Analytics-tab token (recommended) or the 1-day OAuth flow?
4. What's your Telegram bot setup status? (Bot created via @BotFather? Got the token? Got your chat_id?)

Don't answer these now — answer them when you confirm Phase 0 is complete.

**End of Phase 0 (v2 Multi-Feed).**
