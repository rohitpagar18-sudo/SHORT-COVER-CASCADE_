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

## Strategy Decisions Locked In (Phases 0-4)

These decisions were made during phase-by-phase development. Do NOT
revisit without explicit user approval.

### Strike Selection
- Bot scans up to 7 depths per side per scan via independent per-level
  toggles: ITM3 / ITM2 / ITM1 / ATM / OTM1 / OTM2 / OTM3
- For CE: ITMn = ATM − n × interval, OTMn = ATM + n × interval
- For PE: ITMn = ATM + n × interval, OTMn = ATM − n × interval
- NIFTY strike interval: 50 points
- BankNifty strike interval: 100 points
- config.strike.alert_strikes has 7 booleans (itm3/itm2/itm1/atm/otm1/otm2/otm3).
  Defaults: itm2 + itm1 + atm ON, rest OFF. Non-contiguous combos allowed
  (e.g. itm1 ON, itm2 OFF, itm3 ON). At least one must be ON.
- config.strike.order_strikes is still the legacy 3-way (itm/atm/otm) for
  Phase 8 auto-orders (default ATM only)
- Alert and order are decoupled — alert on more depths, order on fewer
- signals.jsonl / alerts.jsonl / Parquet `relation` column = the depth
  label (ITM1..ITM3, ATM, OTM1..OTM3). One-time legacy migration:
  scripts/migrate_relation_labels.py (ITM → ITM1, OTM → OTM1)
- Killed-strike state keys off strike NUMBER, not relation label —
  a strike killed when scanned as ITM1 stays killed when later scanned
  as ITM2 after spot drifts

### Expiry Selection
- Expiries are NEVER hardcoded by day-of-week
- Always pulled from broker instrument dump (Kite or Upstox)
- For NIFTY: nearest Tuesday (weekly) is used
- For BankNifty: nearest last-Tuesday-of-month (monthly only) is used
- If SEBI changes expiry rules, broker reflects it next trading day
- src/data/expiry_resolver.py is the single source of truth

### VWAP Computation
- Session-anchored: resets 09:15 IST daily
- Uses hlc3 = (High + Low + Close) / 3 — NOT close-only
- get_5min_candles() ALWAYS fetches from 09:15 IST to now (full session)
- Never windowed — VWAP requires full session for correctness
- Verified against Kite chart on 26 May 2026: bot ₹194.94 vs Kite ₹194.94

### Risk Math
- check_risk.py is for OPTION PREMIUMS only
- Entries above ₹2,000 are rejected (no real option costs this much)
- This prevents passing index spot value (₹24,000) by accident
- Method 1 (point buffer) is default per strategy doc
- Method 2 (percentage) is available via config.stop_loss.method = 2
- Method 3 (Method-1 initial → 19-SMA trail of option close) is the
  trailing variant: initial SL = Method 1, then after
  `stop_loss.sma_trail.activate_after_minutes` (default 15) the SL
  trails the N-SMA of the option close (default N=19), re-evaluated
  every `update_interval_minutes` (default 15). `follow_direction`
  is `both` (SL follows SMA up AND down) or `ratchet` (up-only).
  Trailing continues through and after TP1 — Method 3 OVERRIDES
  `move_sl_to_breakeven_after_tp1`; breakeven does not apply.
  TP1/TP2 are fixed at entry from R; targets never move with the
  trail. Early-entry fallback: hold the Method-1 SL until N candles
  exist; never trail on a partial SMA. All knobs are config-driven —
  see config/config.yaml `stop_loss.sma_trail` block.

### 5B-A Outcome Kernel — simulates active SL method
- The Phase 5B-A exit-replay kernel (src/dashboard/outcome_replay.py)
  now simulates whichever `stop_loss.method` (1/2/3) is configured
  when the dashboard sync runs. The legacy refusal on
  `risk_reward.trail_sl_after_tp1` is REMOVED — alerts logged with
  that flag (or with method=3) now produce a real outcome instead of
  NO_DATA. Under Method 1/2 the legacy `trail_sl_after_tp1` flag is
  informational only (behavior matches `move_sl_to_breakeven_after_tp1`);
  Method 3 owns the actual SMA trail. The kernel is the single source
  of truth for exits — Phase 5D's paper engine and Phase 7's
  backtest harness both call it; neither runs an independent walk.
- SL method shadow comparison added (2026-06-19): dashboard sync now runs
  all three SL methods on the same cached candles and stamps
  auto_pnl_method1/2/3 + auto_exit_method1/2/3 columns (analysis-only,
  decision deferred to Phase 7). Shadow columns never feed paper_pnl or win-rate.

### Token Refresh Discipline
- Kite: refresh DAILY before 9:15 AM via scripts/refresh_token_kite.py
- Upstox: refresh ANNUALLY (365-day token via Analytics tab)
- Token-date stored in secrets.env (KITE_TOKEN_DATE / UPSTOX_TOKEN_DATE)
- Bot REFUSES to start at setup() if active feed token-date != today IST

### Two-Machine Workflow
- Machine 1: dev, write code, push to git, never has real secrets
- Machine 2: clone, fill real secrets in secrets.env, run live tests
- secrets.env is gitignored — copy via secrets.env.example template

### Scan Loop Cadence
- Bot fires exactly ONE scan per closed 5-min candle
- Trigger window: 5-30 seconds after each :00 / :05 / :10 / ... boundary
- Dedup via (date, hour, candle_minute) tuple — survives long scans
- If a scan takes 45s, next scan still fires correctly on next candle

### Gap-Day Rule
- Detected at setup(): if open_price diverges >1% from prev_close, gap day
- On gap day: no entries before 10:15 AM (vs normal 9:45 AM)
- Toggle: config.time_rules.gap_day_enabled (default ON)
- Reason: VWAP gets dominated by opening candles on gap days

### C5 ADX Shadow Mode (Phase 6.1, two-flag design)
- C5 ADX trend filter has TWO independent switches, by design:
  - `c5_adx.enabled`  → compute + log + display the C5 result
  - `c5_adx.gating`   → include C5 in all_passed (trigger) computation
- Trigger set is C1–C4 by default. C5 in shadow mode (enabled=ON, gating=OFF)
  is computed/logged/shown but NEVER blocks an alert.
- `ConditionResult` carries a `gating` field; `all_passed` only iterates
  results whose `gating=True`. Naively appending a C5 ConditionResult to
  the results list WOULD silently make it gating — the `gating` field is
  what prevents that.
- ADX is computed ONCE per `_scan_symbol` on the SPOT 5-min series (multi-day,
  rolling — NOT session-anchored) and reused across CE/PE and all strikes.
- C5 is crash-isolated: any exception in fetch/compute/evaluate logs a
  `data_issue` (`issue_type="C5_ADX"`) and the C1–C4 alert still fires.
  C5 NEVER defaults to pass on error — it shows as ❌ "insufficient data".
- **`use_di_alignment: OFF` on its own merits.** C5 measures trend STRENGTH
  (`adx >= adx_min` AND `adx > adx_prev`), not direction. Direction is
  already pinned by C0 (spot vs VWAP) and C1 (option vs option VWAP), so
  adding a DI-alignment gate would be redundant. +DI / −DI are still
  logged every scan and shown in the Telegram alert line — they're
  visible for Phase 7 analysis but do NOT drive the C5 ✓/❌.
- **Option DI alongside Spot DI on the alert line.** The Telegram C5
  suffix carries both: `Spot +DI>−DI ✓` (flips to `−DI>+DI` for PE) AND
  `Opt +DI>−DI ✓`. The Option DI is **direction-agnostic** because we
  are always BUYING the option — `+DI > −DI` is always the desired side,
  regardless of CE/PE. Option DI is computed on the option's own candle
  series (same `c5_adx.period`, reuses `compute_adx_di`). Insufficient
  option candles → `Opt N/A`. Logged as `option_di_plus`,
  `option_di_minus`, `option_di_aligned` in `signals.jsonl`.
  **Informational only — does NOT affect C5 pass/fail.**

### TP3 / Target 3 (future enhancement)
- TP3 / Target 3: future enhancement for Method 1 and Method 2 only.
  Full SL-movement ladder and lot-exit rules documented in
  config/config.yaml (risk_reward block). Method 3 SMA trail has no
  fixed TP3 — trail runs until SMA cross or 15:00 EOD. Not implemented
  until Phase 8 live orders land.

### Separate paper config (config_paper.yaml)
- Separate paper config (config_paper.yaml): deliberate NO for Phase 6.
  Paper engine uses a single config (single source of truth — PHASE_5D.md
  hard rule). Revisit at Phase 8 when real orders go live and a
  conservative live config vs experimental paper config separation
  becomes genuinely motivated.

## Phase 5.2 Decisions (Strategy Dashboard + ML Data)

### File Organization
- Excel: quarterly rotation → logs/dashboards/dashboard_YYYY_QN.xlsx
- Parquet: monthly → data/scc_data_YYYY-MM.parquet
- Both regenerable from JSONL — they are gitignored
- data/schema.md IS committed (documentation)

### Gap Decision Labels (directional)
- NORMAL: no gap above threshold
- GAP_UP: positive gap, threshold breached, rule enabled
- GAP_DOWN: negative gap, threshold breached, rule enabled
- GAP_UP_DISABLED: positive gap, threshold breached, rule OFF
- GAP_DOWN_DISABLED: negative gap, threshold breached, rule OFF

### C1 Filter (option-above-VWAP late-entry filter)
- Now configurable: config.conditions.c1_max_distance_pct (default 30)
- Strikes with opt 30-50% above VWAP logged as
  event_type="would_alert_extended" but DO NOT fire alerts
- This captures data for future C1 threshold tuning

### Bot Remarks (two-pass)
- bot_remark: entry-time observation, 3-5 short clauses, ~25 words
- bot_tags: structured comma-separated tags for ML queries
- outcome_remark: written after Order Status is filled (rule-based)
- user_notes: free-form, manual

### Outcome Categories
- TP2_HIT (strong green) | TP1_HIT (light green)
- SL_HIT (red) | WOULD_SKIP (grey) | PARTIAL (yellow)

### Update Triggers (Phase 5.2.1)
- Auto: orchestrator's finally block runs dashboard sync on bot exit.
  Fires on clean market-close exit, Ctrl+C, or exception.
  Skipped on weekends (no market data) and when toggle is OFF.
- Manual: update_dashboard.bat anytime
- Sync is idempotent and best-effort (never blocks bot runtime)

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
│   ├── paper\           — Paper-trade tracking + selection (Phase 5D)
│   ├── orders\          — Order placement (Phase 8 ONLY)
│   ├── backtest\        — Forward-data backtest harness (Phase 7)
│   ├── config_loader.py — Pydantic config validator
│   └── main.py          — Orchestrator
├── logs\                — signals.jsonl, alerts.jsonl, state.json, bot.log
├── tests\               — pytest unit tests
├── run.bat              — Windows launcher
└── CLAUDE.md            — This file

## Current Phase
Phase 5: Telegram alerts + main orchestrator (ALERT-ONLY). Code complete
on this machine. First live alert-only run is on the second laptop.
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
- Phase 4: Risk + State modules — code + unit tests done on this machine.
- Phase 5: Telegram alerts + main orchestrator (ALERT-ONLY) — code + unit
  tests done on this machine. First live run (alert-only) is on the
  second laptop.
- Phase 5C addendum: Internet reconnect resilience + session-only EOD
  — kite_feed waits out long ISP drops via DNS-probe loop, run.bat
  blocks Windows standby for the duration, and EOD Telegram summary
  now reports only the latest src.main run's counts (full suite still
  326/326 passing). Documented as the Phase 5C addendum in
  docs/phases/PHASE_5C.MD.
- Phase 6.1 (shadow C5 ADX): additive non-gating data-collection layer
  during the Phase 6 live alert-only validation window. ADX(14) +DI/-DI
  computed once per scan on the SPOT 5-min multi-day series, logged on
  every scan, and shown in Telegram. Two-flag design: c5_adx.enabled
  (compute/log/display) is independent of c5_adx.gating (block alerts).
  Shadow defaults (enabled=ON, gating=OFF) keep today's C1-C4 trigger
  set unchanged. Acceptance line: after N days, decide promotion from
  parquet data. Documented in docs/phases/PHASE_6_1.md.
- Phase 5D (Paper-Trade Tracking & First-Alert Selection): read-only
  layer over the alert-only bot. Collapses re-fires into one paper
  trade per episode (default key `[symbol, option_type]`, 20-min
  window, ITM1 tie-break on same-candle ties). Deterministic selection
  gate emits TAKEN/SKIPPED per §13/§14 caps. Outcome step REUSES the
  5B-A kernel (`src.dashboard.outcome_replay.replay_alert`) — no second
  candle walk. Adds R-multiples, paper_pnl (lots × lot_size), MFE/MAE
  in R, max_drawdown_R. Auto results in `logs/paper_trades.jsonl`;
  user-owned `logs/paper_overrides.csv` (manual ALWAYS wins, never
  overwritten by code). Two new dashboard sheets (Paper Trades + Paper
  Dashboard) plus a hidden Echoes (diagnostic) sheet, leaving the
  existing six sheets unchanged. CLI: `python -m src.paper.backfill`.
  Phase 8's broker callback later replaces the outcome step; the
  selection layer remains. Suite: 362 → 390 tests passing. Documented
  in docs/phases/PHASE_5D.md; locked decisions in
  config.yaml/`paper_trading:`.

## How Phases Work
- Each phase has a doc in docs/phases/
- Read the phase doc completely before starting
- Implement exactly what the phase doc asks — nothing more, nothing less
- At end of each phase, run the verification checklist
- Do not begin a later phase until told explicitly