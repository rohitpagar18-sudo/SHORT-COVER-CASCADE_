# Short Cover Cascade — Frontend Plan

This document is the shared context for every future "frontend phase"
prompt. Read it first before adding any new page or endpoint.

The frontend lives entirely under `frontend/`. It is a **separate
application** from the trading bot. The bot keeps running unchanged
under `src/` — the UI is read-only over its files, with a future
config-write capability (clearly separated and restart-aware).

---

## Architecture

```
                 ┌────────────────────────────────────┐
   browser ─────►│  FastAPI (frontend/api)            │
   (React SPA)   │  - read-only file services         │
                 │  - config writes (atomic, safe)    │
                 └──────────┬─────────────────────────┘
                            │ read only
            ┌───────────────┼────────────────┐
            ▼               ▼                ▼
         config/         logs/            data/
       config.yaml    *.jsonl, bot.log   *.parquet
       (master        (bot output —      (bot output —
        control)       NEVER write)       NEVER write)
```

* **API:** FastAPI + uvicorn. Reads:
  - `config/config.yaml` (ruamel.yaml round-trip — preserves comments)
  - `logs/state.json` (graceful if missing)
  - `logs/signals.jsonl`, `logs/alerts.jsonl`
  - `logs/paper_trades.jsonl`
  - `logs/bot.log` (mtime only, to infer RUNNING/STOPPED)
* **Web:** React 18 + Vite + TypeScript + Tailwind + lucide-react + recharts.

Single-port mode in production: FastAPI also serves the built SPA from
`frontend/web/dist`. Dev mode: Vite on 5173 proxies `/api` to FastAPI on
8000 (see `vite.config.ts`).

---

## Safety rules (non-negotiable)

1. **Never write to `logs/` or `data/`.** Those are the bot's outputs.
2. **Config writes use surgical text replacement + atomic `os.replace`.**
   Implemented in `frontend/api/app/services/config_write_service.py`:
   - `GET /api/config` — returns full config.yaml as JSON (ON/OFF → bool).
   - `PUT /api/config` — accepts a partial nested change dict. Only
     lines whose values actually changed are modified; all other bytes
     are preserved (comments, alignment, CRLF, quoted strings).
   - Validate feed/bool/numeric fields; reject invalid changes with 422.
   - **`feeds.active_feed` and `mode.order_place_mode` are
     restart-required** — the API returns `restart_required: [key]`
     and the UI shows a "restart needed" banner. Both are called out as
     restart-only in `config/config.yaml` and `CLAUDE.md`.
   - **Section-specific validators** (added Phase 4 editor pages):
     * `strike.max_deviation_from_atm` — integer ≥ 0.
     * `strike.late_entry_threshold_percent` — number > 0.
     * `strike.alert_strikes.{itm3,itm2,itm1,atm,otm1,otm2,otm3}` —
       booleans; **at least one must be ON** (rejected with 422 if all
       seven would end up OFF after the merge).
     * `strike.order_strikes.{itm,atm,otm}` — booleans.
     * `stop_loss.method` — integer in {1, 2, 3}.
     * `stop_loss.use_vix_multiplier`, `hard_exit_red_candle_below_vwap` —
       booleans.
     * `stop_loss.sma_trail.sma_period` — positive integer.
     * `stop_loss.sma_trail.activate_after_minutes` /
       `update_interval_minutes` — positive integers.
     * `stop_loss.sma_trail.follow_direction` — `"both"` or `"ratchet"`.
     * `risk_reward.target_risk_per_trade`, `risk_range_min`,
       `risk_range_max`, `normal_day_tp1_r`, `normal_day_tp2_r`,
       `expiry_day_tp1_r`, `expiry_day_tp2_r` — numbers > 0.
     * `risk_reward.move_sl_to_breakeven_after_tp1`, `trail_sl_after_tp1` —
       booleans.
     * `position_sizing.lot_cap_enabled` — boolean;
       `nifty_max_lots` / `banknifty_max_lots` — positive integers.
     * `circuit_breakers.daily_sl_count_breaker`, `daily_loss_breaker` —
       booleans; `max_sl_per_day` — integer ≥ 1;
       `max_loss_per_day_rupees` — number > 0.
   - None of these changes is restart-required — saves apply on the
     bot's next 5-min scan, and the UI shows a "Saved — applies on the
     bot's next scan." toast on success.
3. **Never import bot code from `src/`.** The API only reads files.
4. **All datetimes are IST** (`Asia/Kolkata`). Never naive, never UTC.
5. **Every file read is wrapped in try/except.** Missing or locked
   files degrade to empty/zero — they must never 500 an endpoint.
6. **No mock data.** If a value is unknown, return `null` or `0` and let
   the UI label it `—`.

---

## Design system (Overview v2 phase)

The visual layer is now token-driven so every later page inherits the
same look without duplicating colors or fonts.

* **Theme:** `web/src/context/ThemeContext.tsx` toggles a `dark` class
  on `<html>`. Default = light. `localStorage["scc.theme"]` persists
  the choice. The sidebar always uses its own dark navy (`bg-sidebar`)
  regardless of theme — only the content area swaps.
* **Tokens:** all colors flow through CSS variables in
  `web/src/index.css` (`--c-bg`, `--c-surface`, `--c-card`, `--c-ink`,
  `--c-muted`, `--c-line`, `--c-line2`, `--c-accent`). Tailwind classes
  `bg-bg`, `bg-card`, `text-ink`, `text-muted`, `border-line`,
  `bg-line2` resolve to those tokens — `darkMode: "class"` is set in
  `tailwind.config.js`.
* **Font:** Inter, loaded via the rsms CDN in `index.css`.
* **Sidebar (canonical order):** Overview, Instruments,
  Strike & Scanning, Stop Loss, Risk & Money, Conditions (C0–C5),
  Orders, Time Rules, Re-entry Rules, Alerts & Telegram, Paper Trading,
  Trades & Performance, Dashboard & Reports, Logs, Bot Status,
  Configuration, Settings, About. Footer shows the RUNNING/STOPPED pill, uptime,
  last config reload, next health check, a "View System Health"
  button, and the theme toggle. Uptime and next health check require a
  bot heartbeat (later phase) — until then they display "—" with a
  tooltip. Last config reload uses `config.yaml` mtime.
* **Header:** title + subtitle, "Last Config Reload … / Auto-Reload: ON"
  strip, notification bell badged with the count of today's ALERTED
  signals, IST date picker (default today), and a "Reload Config"
  button. Reload only refetches the UI; it shows a toast reminding the
  user that the bot itself auto-reloads at its next 5-min scan.
* **Toast:** `web/src/context/ToastContext.tsx` — global toasts used
  by the Reload Config button.
* **Reusable charts:** `web/src/components/charts/`
  - `PnLChart` — recharts `ComposedChart` (per-day bars + cumulative
    line), reused by Trades & Performance and Dashboard & Reports.
  - `ConditionDonut` — donut with center total + legend.
  - `StatPanel` — Total/Realized/Unrealized/Max-profit/Max-loss list.
  - `PriceSparkline` — small price line for open positions.

---

## Folder layout

```
frontend/
├── api/
│   ├── app/
│   │   ├── main.py
│   │   ├── paths.py
│   │   ├── time_utils.py
│   │   ├── models/overview.py          # extended in Overview v2
│   │   ├── routers/                    # /health /overview /bot/status /config
│   │   └── services/                   # config (rt+write), signals, paper, state, botstatus
│   ├── tests/test_roundtrip_noop.py
│   └── requirements.txt
├── web/
│   ├── index.html, package.json, vite.config.ts, tailwind.config.js
│   └── src/
│       ├── main.tsx, App.tsx, index.css
│       ├── context/
│       │   ├── ConfigContext.tsx       # config editor cache (F1)
│       │   ├── ThemeContext.tsx        # NEW — light/dark theme
│       │   └── ToastContext.tsx        # NEW — global toasts
│       ├── components/
│       │   ├── Sidebar, Header, Card, ProgressBar, ComingSoon
│       │   ├── charts/                 # PnLChart, ConditionDonut,
│       │   │                           #       StatPanel, PriceSparkline
│       │   ├── positions/              # F6 — OpenPositionTracker (reusable)
│       │   └── config/                 # reusable config primitives (F1)
│       ├── pages/
│       │   ├── Overview.tsx            # v2 design
│       │   ├── Configuration.tsx       # F1 + Phase 4 tabs
│       │   ├── Instruments.tsx         # F1
│       │   ├── StrikeScanning.tsx      # Phase 4 — wraps StrikeScanningSection
│       │   ├── StopLoss.tsx            # Phase 4 — wraps StopLossSection
│       │   ├── RiskMoney.tsx           # Phase 4 — wraps RiskMoneySection
│       │   └── TradesPerformance.tsx   # F6 — KPIs + live tracker + history
│       └── lib/                        # api.ts (typed fetch), format.ts
├── docs/FRONTEND_PLAN.md               # this file
└── run_ui.bat
```

---

## How to run

### Production mode (single port, recommended)
```cmd
frontend\run_ui.bat
```
Builds `web/dist` if missing, then uvicorn serves `/` + `/api/*` from
port 8000. Override the port with `run_ui.bat 9000`.

### Dev mode (hot reload)
Terminal 1 — API:
```cmd
cd frontend\api
..\..\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Terminal 2 — Vite:
```cmd
cd frontend\web
npm install
npm run dev
```
Open http://localhost:5173/. Vite proxies `/api` to :8000.

### Environment overrides

| Var                          | Default | Meaning                                                |
|------------------------------|---------|--------------------------------------------------------|
| `SCC_ROOT`                   | auto    | Override repo root used by the API to find bot files.  |
| `SCC_UI_PORT`                | `8000`  | Port for `uvicorn` in `run_ui.bat`.                    |
| `SCC_BOT_ALIVE_SECONDS`      | `120`   | Bot considered RUNNING if `bot.log` was touched within this many seconds. |

---

## API endpoints

| Method | Path             | Returns | Notes |
|--------|------------------|---------|-------|
| GET    | `/api/health`    | `{ok, now_ist, project_root, config_present}` | Liveness. |
| GET    | `/api/bot/status`| `{status, last_activity_ist, uptime_seconds, next_health_check_ist, last_config_reload_ist}` | uptime / next_health_check are `null` until the bot writes a heartbeat. |
| GET    | `/api/overview?date=YYYY-MM-DD` | Aggregated Overview payload (see below). | Single round-trip; `date` defaults to today IST. |
| GET    | `/api/config`    | Full `config.yaml` as JSON. | |
| PUT    | `/api/config`    | `{ok, updated, restart_required, message}` | 422 on validation error. |
| GET    | `/api/positions/open` | `{as_of, positions:[…]}` | Live read of open paper episodes. LTP / running P&L derived from the most recent matching `signals.jsonl` scan. Never fabricates a price — missing → `null`. |
| GET    | `/api/trades?date_from&date_to&symbol&option_type&status&outcome` | `{filters, kpis, trades:[…], daily_series:[…]}` | Defaults to today IST. Unrealized P&L is the sum of `running_pnl` across currently-open positions. |
| GET    | `/api/trades/history?group_by=day\|week\|month&…` | `{group_by, filters, groups:[{period_label, period_start, total_trades, win_rate, total_pnl, realized_pnl, unrealized_pnl, max_profit, max_loss, trades:[…]}]}` | Default window = last 30 days IST when neither `date_from` nor `date_to` supplied. |
| GET    | `/api/paper/today` | `{selection:{max_trades_per_day, trades_taken, trades_remaining, daily_sl_hit, max_sl_per_day, cooldown_active, same_strike_sl_count}, reentry:{cooldown_minutes, minutes_since_last_sl, same_strike_kill_enabled, strikes_locked_today}}` | Reuses `paper_service.get_trade_plan_dict()` and `get_reentry_status_dict()` — no duplicated logic. |
| GET    | `/api/paper/episodes?date_from&date_to&status&symbol&option_type` | `{episodes:[{episode_id, date, time, symbol, option_type, strike, relation, selection, skip_reason, entry_price, sl, tp1, tp2, qty_lots, outcome, r_multiple, paper_pnl, mfe_r, mae_r, max_drawdown_r, echo_count, echoes, is_overridden}]}` | Groups `paper_trades.jsonl` by `episode_id`. Default date = today. |
| GET    | `/api/paper/overrides` | `{rows:[…], columns:[…]}` | Read-only view of `logs/paper_overrides.csv`. Empty payload if file absent. |
| GET    | `/api/reports/performance?date_from&date_to&agg=daily\|weekly\|monthly` | Performance report (KPIs, cumulative, underlying, weekday, winners/losers, outcome distribution, duration, monthly) | Default range = This Month IST; prev-period deltas for KPIs. |
| GET    | `/api/reports/conditions?date_from&date_to` | Condition pass rates, funnel, bottleneck, C5 shadow analysis, DI alignment | IST; default = This Month. |
| GET    | `/api/reports/risk?date_from&date_to` | R-distribution, equity curve, drawdown, streaks, MFE/MAE, risk adherence, payoff | IST; default = This Month. |
| GET    | `/api/reports/insights?date_from&date_to` | Strategy-level breakdowns (time-of-day, weekday, symbol, relation, CE/PE, day-type) + rule-based key_insights (guarded by MIN_SAMPLE=10) | IST; default = This Month. |
| GET    | `/api/reports/monthly?date_from&date_to` | Monthly aggregates (all-time, newest-first) + per-day calendar heatmap data (date-range filtered). best_day/worst_day per month. | IST; default = This Month for calendar. |
| GET    | `/api/system/health` | **SHARED — F7c + F8 Bot Status.** Feed, bot (RUNNING/STOPPED + last activity + uptime), scan cadence (gap analysis on signals.jsonl), log file sizes/mtimes/fresh, data_issues, last_config_reload_ist, last_dashboard_sync_ist. | Polled every 30s. No date params. |
| GET    | `/api/logs/files` | `{files:[{name, path_label, size_kb, last_modified_ist}]}` | Stats for the 5 allowlisted log files (bot.log, signals.jsonl, alerts.jsonl, paper_trades.jsonl, state.json). |
| GET    | `/api/logs/tail?file&lines&level&search` | `{file, type, rows, filtered_count, total_read, ...}` | **Allowlist-only `file` param** (422 on anything else). Reads efficiently from EOF (walks backwards in 8 KB chunks — large files never load fully). `bot.log` returns text rows parsed into `{time, level, message}`; `*.jsonl` returns parsed JSON objects; `state.json` returns the single doc as a one-row table. `level` filter applies only to bot.log; `search` is a case-insensitive substring filter applied AFTER tailing. |

### `/api/overview` payload — Overview v2

In addition to the F0 fields (`feed`, `modes`, `instruments`,
`position`, `today`, `circuit_breakers`, `next_events`,
`recent_alerts`, `bot`, `last_synced_ist`) the response now carries:

* `today.paper_pnl_today` (₹), `today.paper_pnl_pct_today` (%),
  `today.open_positions_count`
* `circuit_breakers.status` — `"OK" | "WARN" | "TRIPPED"`
* `recent_alerts[].conditions` — `[{name,passed}]` derived from the
  REAL `conditions_passed` / `conditions_failed` arrays in
  `signals.jsonl` / `alerts.jsonl`. No hardcoded legend.
* `recent_alerts[].conditions_passed_count` / `conditions_total` /
  `notes` (falls back to `telegram_short_remark` or `bot_remark`).
* `pnl_series` — `{window_days, days, cumulative, totals}` aggregated
  from `paper_trades.jsonl` by IST `date` field.
* `open_position` — most recent unresolved TAKEN paper trade, or
  `null`. **`ltp`, `pnl`, and `price_series` are intentionally `null` /
  `[]`** because the JSONL is post-hoc; the UI labels them "—".
* `condition_summary` — total scans on the chosen date + `5/5 .. 1/5`
  buckets counted from `signals.jsonl`.
* `trade_plan` — `{max_trades_per_day, trades_taken, trades_remaining,
  daily_sl_hit, max_sl_per_day, cooldown_active, same_strike_sl_count}`
  derived from `config.paper_trading` + today's `paper_trades.jsonl`.
* `reentry_status` — `{cooldown_minutes, minutes_since_last_sl,
  same_strike_kill_enabled, strikes_locked_today}` derived from
  `config.re_entry` + today's `paper_trades.jsonl`.
* `bot.uptime_seconds`, `bot.next_health_check_ist`,
  `bot.last_config_reload_ist`.
* `date_ist` — the IST date the response is scoped to.

### Honest limitations

| Field                                | Backed by                                 |
|--------------------------------------|-------------------------------------------|
| `open_position.ltp` / `pnl` / `price_series` | Not in `paper_trades.jsonl`. Will require a broker tap. |
| `bot.uptime_seconds`                 | Bot does not yet emit a heartbeat file.   |
| `bot.next_health_check_ist`          | Same — placeholder.                       |
| `bot.last_config_reload_ist`         | Proxy = `config.yaml` mtime.              |

These never fabricate values — the UI renders "—" with a tooltip.

---

## Pages status

| Sidebar item             | Route                  | Status     |
|--------------------------|------------------------|------------|
| Overview                 | `/overview`            | **v2 done** |
| Configuration            | `/configuration`       | **Done** (all 11 tabs live) |
| Instruments              | `/instruments`         | **Done** — `nifty_lot_size` / `banknifty_lot_size` are display-only (read from config, note "Auto-verified from broker at 09:15 IST"); only `nifty_enabled` / `banknifty_enabled` are editable |
| Strike & Scanning        | `/strike-scanning`     | **Done**   |
| Stop Loss                | `/stop-loss`           | **Done**   |
| Risk & Money             | `/risk-money`          | **Done**   |
| Conditions (C0–C5)       | `/conditions`          | **Done**   |
| Orders                   | `/orders`              | **Done**   |
| Time Rules               | `/time-rules`          | **Done**   |
| Re-entry Rules           | `/reentry-rules`       | **Done**   |
| Alerts & Telegram        | `/alerts-telegram`     | **Done**   |
| Paper Trading            | `/paper-trading`       | **Done** (F7) |
| Trades & Performance     | `/trades-performance`  | **Done** (Phase F6) — KPI row, live `OpenPositionTracker`, filter bar with date presets, Today's Trades table, Daily P&L (₹/% toggle), Trade History grouped by Day/Week/Month with expandable rows |
| Dashboard & Reports      | `/dashboard-reports`   | **COMPLETE** (F7c) — All 6 tabs done: Performance Overview, Strategy Insights, Condition Analysis (C0–C5), Risk Analysis, Monthly Summary, System Health. |
| Logs                     | `/logs`                | **Done** (F8) — file selector (allowlist), lines/level/search filters, auto-refresh ON 10–60s, bot.log monospace + JSONL table renderers |
| Bot Status               | `/bot-status`          | **Done** (F8) — renders shared `/api/system/health` snapshot + Next Key Events from `config.yaml`; polls per Settings.pollInterval |
| Settings                 | `/settings`            | **Done** (F8) — localStorage-only UI prefs (theme synced with sidebar; default date range; poll interval; currency; reset). Never writes config.yaml |
| About                    | `/about`               | **Done** (F8) — app name, version, phase, disclaimers, live `/api/health` indicator |

All sidebar pages are now COMPLETE. No routes render the "Coming soon" placeholder anymore.

### Phase 4 section components (config editor)

Three section components live under
`web/src/components/config/sections/`. Each is built on the same
`SectionShell` + `useConfig` primitives as the F1 sections, and is
mounted from two places:

* As a tab inside `Configuration.tsx`.
* As the only body of a standalone sidebar route
  (`StrikeScanning.tsx`, `StopLoss.tsx`, `RiskMoney.tsx`).

| Component                 | File                                                       | Config blocks edited                                       |
|---------------------------|------------------------------------------------------------|------------------------------------------------------------|
| `StrikeScanningSection`   | `components/config/sections/StrikeScanningSection.tsx`     | `strike`                                                    |
| `StopLossSection`         | `components/config/sections/StopLossSection.tsx`           | `stop_loss`                                                 |
| `RiskMoneySection`        | `components/config/sections/RiskMoneySection.tsx`          | `risk_reward`, `position_sizing`, `circuit_breakers`        |

Notable UX rules these components encode:

* **Alert strikes:** disable Save and show an inline error when all
  seven `strike.alert_strikes.*` toggles are OFF; the API also rejects
  this state with 422 — defense in depth.
* **SMA Trail panel:** rendered greyed/disabled with an "Active only
  when Method 3 is selected" note whenever `stop_loss.method !== 3`.
* **Save toast:** on a successful write the section pushes a
  `"Saved — applies on the bot's next scan."` toast via the existing
  `ToastContext` — there's no restart banner for these blocks.

### Phase 5 section components (final config-editor pages)

Five more section components added under the same folder. Each has
a standalone sidebar route AND a tab in `Configuration.tsx`.

| Component                  | File                                                        | Config block  | Standalone route |
|----------------------------|-------------------------------------------------------------|---------------|------------------|
| `ConditionsSection`        | `components/config/sections/ConditionsSection.tsx`          | `conditions`  | `/conditions`    |
| `TimeRulesSection`         | `components/config/sections/TimeRulesSection.tsx`           | `time_rules`  | `/time-rules`    |
| `ReEntrySection`           | `components/config/sections/ReEntrySection.tsx`             | `re_entry`    | `/reentry-rules` |
| `AlertsTelegramSection`    | `components/config/sections/AlertsTelegramSection.tsx`      | `telegram`    | `/alerts-telegram` |
| `OrdersSection`            | `components/config/sections/OrdersSection.tsx`              | `orders`      | `/orders`        |

Notable UX rules these components encode:

* **ConditionsSection:** Save is disabled if `c3_rsi_min >= c3_rsi_max`
  or if `c5_adx.gating` is ON while `c5_adx.enabled` is OFF.
  The **Gating toggle** is fully disabled (not just visually greyed) until
  Enabled is ON — prevents the cross-field constraint from ever being
  violated before Save. When Gating is turned ON, an inline amber
  warning explains the impact: alerts will require C1–C5 all passing.
  Turning Enabled OFF automatically forces Gating to OFF. All C5
  sub-settings (Period, ADX Min, Require Rising, Use DI Alignment,
  Lookback Candles) pass `disabled={!enabled}` so they deactivate
  visually when C5 is OFF.
* **TimeRulesSection:** Uses an inline `TimeInput` component (not
  `TextField`) that validates the 24-hour `HH:MM` format on each
  keystroke, shows a red border + inline error on invalid input, and
  disables Save until all five time fields are valid.
* **OrdersSection:** A prominent "Phase 8 only — ignored in alert/paper
  mode" amber banner appears at the top of the section.
* All sections: Save toast says "Saved — applies on the bot's next scan."

### Phase 5 API validators (config_write_service.py)

Five new per-section validator functions added in Phase 5:

* **`_validate_conditions`**: validates `c3_rsi_min` and `c3_rsi_max`
  in 0..100 with cross-field `min < max` check; `c1_max_distance_pct > 0`;
  `c1_extended_zone_max_pct >= c1_max_distance_pct`; `c5_adx.period` and
  `c5_adx.lookback_candles` as positive integers; `c5_adx.adx_min > 0`.
  **Cross-field rule:** `c5_adx.gating` may be ON only if `c5_adx.enabled`
  is ON — rejected with 422 otherwise. The check uses effective values
  (considers both the incoming change and the existing doc value).
* **`_validate_time_rules`**: validates 5 time strings against
  `^([01]\d|2[0-3]):[0-5]\d$`; `gap_day_threshold_pct > 0`;
  `gap_day_direction` in `{"both","up","down"}`.
* **`_validate_re_entry`**: validates `cooldown_minutes_after_sl >= 0`.
* **`_validate_orders`**: validates `order_type` in `{"limit","market"}`.
* **`_walk_bool_checks`** (existing, unchanged): already covers all
  boolean toggles in `telegram`, `orders`, `re_entry`, and `conditions`.

### Quote-preservation fix in `_surgical_set`

`_surgical_set` now detects when the original YAML value was
double-quoted (e.g. `"09:45"`, `"both"`) and re-wraps the replacement
in double quotes if the new value is a bare string. This prevents
PyYAML (YAML 1.1, used by the bot) from misinterpreting bare
colon-containing strings like `10:00` as sexagesimal integers.

### Phase F6 — Trades & Performance + reusable OpenPositionTracker

Read-only visualization phase. No bot source touched, no broker calls.

**New API endpoints** (see table above): `/api/positions/open`,
`/api/trades`, `/api/trades/history`. All three are wrapped in
defensive try/except so locked, missing or partial JSONL files degrade
to empty payloads — never 500.

**New service modules** under `frontend/api/app/services/`:

* `positions_service.py` — joins paper episodes (`decision=="TAKEN"
  AND outcome=="NO_DATA"`) with the latest matching `signals.jsonl`
  scan to derive `last_ltp`, `last_ltp_time`, `running_pnl`
  (`(last_ltp - entry) * lots * lot_size`) and `running_pnl_r`
  (`(last_ltp - entry) / |entry - sl|`). Builds the entry-day price
  series for the sparkline. Returns `null` when no scan matches —
  no fabricated price.
  **Live-position eligibility** (two gates): an episode is counted as a
  live open position only when (a) `sl`, `tp1`, and `tp2` are all
  present (non-null / non-NA) **and** (b) `entry_time >= TRACKING_START`
  (`"2026-06-05T13:25:00+05:30"` — the date SL/TP tracking data began).
  Episodes that fail either gate are excluded and counted as
  `untracked_count` in the response. `OpenPositionTracker` renders a
  muted "N earlier entries hidden (no exit data)" note when
  `untracked_count > 0`.
* `trades_service.py` — implements `list_trades(...)` and
  `history(...)`. KPIs split realized (finalized trades) from
  unrealized (sum of `running_pnl` across open positions). History
  groups by day / week / month with stable period labels and a
  per-period stats block plus its full trade rows for the expandable
  row UI.

**New reusable component**:
`web/src/components/positions/OpenPositionTracker.tsx` — polls
`/api/positions/open` every 15s, renders one card per open episode
(symbol + strike + relation + RUNNING badge; entry time, lots, buy
price, LTP with `as of HH:MM` label, SL/TP1/TP2, running P&L in ₹
and R, horizontal SL→entry→TP1→TP2 track with an LTP triangle, and
a recharts sparkline of the day's price series). Empty state:
"No open paper positions." This component will also be mounted on
the Paper Trading page (F7) and can later replace Overview's static
Open Position card.

**New page**: `web/src/pages/TradesPerformance.tsx` (route
`/trades-performance` in `App.tsx`). Layout, top to bottom:

1. **KPI row** (8 tiles) — Total Trades, Winning (+ %), Losing
   (+ %), Total P&L, Realized, Unrealized, Max Daily Profit, Max
   Daily Loss.
2. **OpenPositionTracker** — mounted directly under the KPIs.
3. **Filter bar** — date-range presets (Today, This Week, This
   Month, Last Week, Last Month, Custom) + From/To inputs +
   Symbol/Type/Status/Outcome selects + Apply / Reset. Presets are
   computed in IST (Monday-start ISO weeks).
4. **Today's Trades table** — Time / Symbol / Type / Strike (+ rel)
   / Qty / Buy / Sell / SL / TP1 / TP2 / P&L / Status / Outcome
   with colored outcome badges (TP2 HIT, TP1 HIT, SL HIT, PARTIAL,
   RUN, SKIPPED). Totals row + legend.
5. **Daily P&L Overview** — reuses the Overview `PnLChart`
   (`ComposedChart` bars + line) with a ₹ / % toggle (% view is a
   relative bar chart since this layer has no fixed `target_risk`
   context). Side `StatPanel` shows Total / Realized / Unrealized /
   Max Profit / Max Loss.
6. **Trade History** — Group By Day / Week / Month with
   expandable rows. Each row collapses to label + total P&L; expand
   shows a 6-stat strip (Total Trades, Win Rate, Total P&L, Realized,
   Unrealized, Max Day Profit) and the period's full trade rows.
7. **Footer** — "All times are IST (Asia/Kolkata). Paper P&L;
   updates each 5-min scan, outcomes finalized at EOD."

**Live-data reality rules** (enforced server-side, surfaced
client-side):

* LTP is `signals.jsonl::option_close` from the latest matching
  scan. No scan → `last_ltp = null`, `running_pnl = null`. UI
  renders `—`, never a fake number.
* `as_of` and `last_ltp_time` are real IST timestamps from the JSONL
  rows — the user sees exactly when the bot last priced the option.
* All values change only on the bot's natural 5-min scan cadence;
  the 15s UI poll just keeps the screen fresh.

**Polling**: open positions + today's trades refetch every 15s.
History refetches only on filter / Group By changes.

**Skeletons** show while the first response is in flight. Subsequent
errors keep the last good payload visible — the UI never blocks.

* `frontend/requirements.txt` created at the frontend root (canonical
  location). Contains: `fastapi>=0.110.0`, `uvicorn[standard]>=0.27.0`,
  `ruamel.yaml>=0.18.0`, `pydantic>=2.5.0`.
* `frontend/api/requirements.txt` removed (was a duplicate).
* `run_ui.bat` updated: `pip install -r "%~dp0requirements.txt"` instead
  of inlining the package list.
* Bot's root `requirements.txt` is untouched.

### Phase F7 — Paper Trading

Read-only visualization phase. No bot source touched, no broker calls,
no writes to `logs/` or `data/`.

**New API endpoints** (see table above):
`/api/paper/today`, `/api/paper/episodes`, `/api/paper/overrides`.
All three are wrapped in defensive try/except — locked, missing or
partial files degrade to empty payloads, never 500.

**Refactoring: TradePlan / ReentryStatus logic extracted to service.**
`paper_service.get_trade_plan_dict(date_iso)` and
`paper_service.get_reentry_status_dict(date_iso)` are the single source
of truth for both `/api/overview` and `/api/paper/today` — no duplicated
config-reading logic. `overview.py` now calls these service functions
instead of recomputing inline.

**New path constant** in `paths.py`: `PAPER_OVERRIDES_CSV` pointing to
`logs/paper_overrides.csv`.

**New router** `frontend/api/app/routers/paper.py`:

* `GET /api/paper/today` — today's trade-plan + reentry status snapshot.
  Reuses `get_trade_plan_dict()` and `get_reentry_status_dict()`.
* `GET /api/paper/episodes` — groups `paper_trades.jsonl` rows by
  `episode_id`, separates representative row from echoes, applies
  date/status/symbol/option_type filters. Marks rows whose `alert_id`
  appears in `paper_overrides.csv` with `is_overridden: true`.
  Sorted date-desc, time-desc.
* `GET /api/paper/overrides` — returns columns + rows from
  `paper_overrides.csv` verbatim. Empty payload when file absent.

**Reused components** (mounted as-is, no internals copied):

* `OpenPositionTracker` — polls `/api/positions/open` every 15s; shows
  live OPEN / OPEN(stale) cards. Mounted with `showTitle={true}`.

**New page** `web/src/pages/PaperTrading.tsx` (route `/paper-trading` in
`App.tsx`). Layout, top to bottom:

1. **Today's Paper Plan** (Card) — 7 compact `StatTile`s from
   `/api/paper/today`, polls every 60s: Max Trades/Day, Taken,
   Remaining, Daily SL Hit (count/max), Cooldown Active (YES/NO with
   color), Same-Strike Kill (ON/OFF), Strikes Locked Today
   (comma-joined numbers or "None").
2. **Open Positions (Live)** — `<OpenPositionTracker showTitle />`.
3. **Paper Episodes** — filter bar (Today / This Week / Custom presets,
   date-from/to, TAKEN/SKIPPED/All, Symbol input, CE/PE/All).
   Expandable rows reveal: price levels, R-metrics (only when at least
   one is non-null), Echoes (only when echo_count > 0).
   Outcome badges: TP2_HIT=emerald-600, TP1_HIT=emerald-400,
   SL_HIT=rose-500, PARTIAL=amber-500, NO_DATA=slate-400 ("RUNNING"),
   WOULD_SKIP=slate-300. Override marker: amber "OVR" pill.
4. **Manual Overrides** (collapsible Card) — lazy-loads on first expand.
   Note: "Manual overrides are user-owned and always win; edit the CSV
   directly." Empty → "No manual overrides."
5. **Footer** — "All times are IST (Asia/Kolkata). Paper P&L; positions
   update each 5-min scan, outcomes finalize at EOD."

**Read-only guarantee**: no file writes anywhere in this phase.

### Phase F8 — Final pages: Logs Viewer, Bot Status, Settings, About

Read-only visualization phase. Completes the last four sidebar pages.
No bot source touched, no broker calls, no `secrets.env` read, no writes
to `logs/` or `data/`. **All pages are now COMPLETE.**

**New API endpoints** (see table above):
`/api/logs/files`, `/api/logs/tail`. Both wrapped in defensive try/except.
The `file` query is validated against an explicit allowlist
(`bot.log, signals.jsonl, alerts.jsonl, paper_trades.jsonl, state.json`);
anything else returns 422 — we never tail an arbitrary path.

**New service** `frontend/api/app/services/logs_service.py`:
* `ALLOWED_FILES` — the dict that the router validates against.
* `list_files()` — `os.stat` over the allowlist. Missing files return
  `last_modified_ist = null`, `size_kb = null`.
* `_tail_lines(path, n)` — walks the file **backwards in 8 KB chunks**
  from EOF, stops as soon as `n+1` newlines are collected. Multi-GB
  log files only ever cost the last few KB. UTF-8 decoded with
  `errors="replace"` to handle partial multibyte sequences at chunk
  boundaries.
* `tail_text(...)` — for `bot.log`. Parses the loguru pattern
  `"YYYY-MM-DD HH:MM:SS.mmm | LEVEL | rest"` into
  `{time, level, message}`. Applies optional `level` (one of
  DEBUG/INFO/WARNING/ERROR/CRITICAL or `all`) and free-text `search`
  filters AFTER tailing — filters never expand what's read.
* `tail_jsonl(...)` — for `signals.jsonl`, `alerts.jsonl`,
  `paper_trades.jsonl`. Parses each line; malformed lines are counted
  and skipped, never crash. Search is applied to the raw line for
  cross-field matching.
* `tail_state_json(...)` — `state.json` is a single JSON document, so
  it is read fully (the file is always small) and surfaced as a
  one-row table for consistency with the JSONL renderer.

**Reused** `/api/system/health` (F7c) — Bot Status page polls this
endpoint; **no duplicated health logic**. The `system_health_router`
already wraps `health_service.get_health()` in defensive try/except.

**Reused** `/api/health` — About page calls this every 15 s for the
API-up indicator.

**Reused** `/api/config` — Bot Status reads `time_rules` +
`dashboard.auto_trigger_at_1535` + `telegram.send_eod_summary` to
render Next Key Events. Read-only — no PUT calls from these pages.

**New context** `web/src/context/SettingsContext.tsx`:
* `UiSettings` — `{defaultDateRange, pollIntervalSeconds, currencyDisplay,
  compactNumbers}`. Persisted to localStorage under
  `scc.uiSettings.v1`. Defaults: `This Month`, `15s`, `₹`, off.
* `usePollIntervalMs()` helper used by Logs and Bot Status to honor
  the user's chosen poll cadence.
* This context is purely UI state; **it never writes config.yaml** and
  the bot does not read it.

**New pages** (route → file):

1. **`/logs` → `pages/Logs.tsx`** — file selector (allowlist), lines
   (100/200/500), level (All/DEBUG/INFO/WARNING/ERROR — only shown
   when `bot.log` is selected), search box, auto-refresh toggle
   (default ON; respects Settings.pollInterval, min 5 s). bot.log
   renders as a monospace block with color-coded levels and
   auto-scroll-to-bottom when the user is at the bottom. JSONL files
   render as a compact table picking columns from the first 12
   rows' union of keys (up to 14 cols; overflow is noted). state.json
   surfaces as a one-row table.

2. **`/bot-status` → `pages/BotStatus.tsx`** — polls `/api/system/health`
   (and `/api/config` for time rules) on Settings.pollInterval.
   Renders: 4 top-level StatTiles (Bot, Feed, Uptime, Scan Cadence) +
   Scan Cadence card with recent gaps table + Next Key Events card
   (Last Entry, Soft Squareoff, Hard Squareoff, EOD Summary,
   Dashboard Sync) + Log Files freshness table + Data Issues panel +
   Recent Activity (last config reload, last dashboard sync, last bot
   activity). Stale-data amber banner when a fetch fails. Heartbeat
   fields show "—" with a tooltip — never fabricated.

3. **`/settings` → `pages/Settings.tsx`** — pure UI preferences:
   theme (synced with the sidebar toggle), default date range,
   poll interval, currency display, compact-numbers toggle, and a
   Reset button. Every change persists to localStorage; **no
   `config.yaml` write path exists**. Includes a prominent blue info
   banner: "These settings control the dashboard UI only — they do
   not change the bot's config."

4. **`/about` → `pages/About.tsx`** — app name (Short Cover Cascade
   Bot — Dashboard), frontend version (`1.0.0-F8`), bot phase
   (`Phase 6 — live alert-only validation`), short description,
   honest disclaimers (paper P&L; updates every 5 min; outcomes
   finalize at EOD; dashboard does not place orders), and a live
   API-health pulse calling `/api/health` every 15 s. Shows green ✓
   + server time when reachable, red ✗ + error message when not.

**Provider wiring** (`web/src/main.tsx`): `<SettingsProvider>` is
mounted **inside** `<ThemeProvider>` and **outside** `<ToastProvider>`
so that toasts can show "settings reset" notifications.

**Read-only guarantee**: no file writes anywhere in this phase. The
only writes performed by the whole frontend continue to be config.yaml
edits via `PUT /api/config`. `secrets.env` is never read.

### Phase F7c — Dashboard & Reports: Strategy Insights + Monthly Summary + System Health

Read-only visualization phase. Completes all 6 tabs on the Dashboard & Reports page.
No bot source touched, no broker calls, no writes to `logs/` or `data/`.

**New API endpoints** (see table above):
`/api/reports/insights`, `/api/reports/monthly`, `/api/system/health`.
All reads wrapped in defensive try/except — missing or locked files degrade to
empty payloads, never 500. No `secrets.env` read anywhere.

**New service modules** under `frontend/api/app/services/`:

* `insights_service.py` — reads `paper_trades.jsonl` (max 20k lines), filters to
  TAKEN + representative rows in the date range, computes 5 (or 6) breakdowns:
  `by_time_of_day` (30-min buckets), `by_weekday` (Mon–Fri), `by_symbol`,
  `by_relation` (ITM3..OTM3 ordered), `by_option_type` (CE/PE), and optionally
  `by_day_type` (Expiry/Normal — only included when `is_expiry_day` field is
  present in the data). `by_gap_type` is intentionally absent — no gap_type field
  in `paper_trades.jsonl`.
  `key_insights` is a rule-based list generated **only** for dimensions whose
  n ≥ `MIN_SAMPLE` (= 10). Smaller samples appear in the breakdown table but
  produce no insight string — guarding against false conclusions from small N.

* `monthly_service.py` — reads `paper_trades.jsonl`. Produces two outputs:
  - `months`: all-time aggregation (newest-first) with best_day/worst_day per month
    (absent from the earlier Performance Overview monthly table).
  - `calendar`: per-day `{date, pnl, trades}` filtered to the query date range,
    used by the CalendarHeatmap component.

* `health_service.py` — derives a real-time operational snapshot:
  - `feed`: active_feed name (from config.yaml) + connected/disconnected (from bot.log mtime).
  - `bot`: status, last_activity_ist, uptime_seconds (all from `botstatus_service`).
  - `scan_cadence`: parses `timestamp_ist` from `signals.jsonl`, filters to
    Mon–Fri 09:15–15:30 IST, finds consecutive gaps > 7 min. Returns last 10 gaps
    + `healthy` bool. Empty signals.jsonl → healthy=True, no gaps.
  - `files`: `os.stat` on signals.jsonl / alerts.jsonl / paper_trades.jsonl /
    state.json / bot.log. Each row: `{name, last_modified_ist, size_kb, fresh}`.
    fresh = modified within 86,400 s. OSError → all null/False.
  - `data_issues`: scans `signals.jsonl` for rows with `event_type=="data_issue"`
    or a non-null `issue_type` field (e.g., C5_ADX). Returns count + last 10.
  - `last_config_reload_ist`: config.yaml mtime via `botstatus_service`.
  - `last_dashboard_sync_ist`: reversed scan of `bot.log` for lines containing
    "dashboard" or "sync"; extracts loguru timestamp. None if not found.

  **SHARED**: this endpoint is explicitly designed for reuse by F8 Bot Status page —
  no duplication of health logic will be needed there.

**New routers** `frontend/api/app/routers/insights.py`, `monthly.py`,
`system_health.py`. All follow the thin-wrapper pattern.

**New chart component** `web/src/components/charts/CalendarHeatmap.tsx`:
* Accepts `data: CalendarDay[]` (`{date, pnl, trades}`).
* Groups by YYYY-MM, renders one calendar grid per month.
* Mon-first week layout using `(getDay() + 6) % 7` ISO weekday arithmetic.
* 3-intensity colour scaling: light/medium/dark × green/red based on |pnl| / max(|pnl|).
* Fixed-position hover tooltip showing date, INR P&L (with sign), and trade count.
* Entirely self-contained — no recharts dependency.
* Empty data → "No data for this period." placeholder.
* Exports `CalendarDay` type for consumers.

**MIN_SAMPLE insight guard** (`MIN_SAMPLE = 10`):
Key insights are asserted ONLY when the relevant dimension has ≥ 10 trades.
Below that threshold, breakdowns are shown in the table (with n clearly visible)
but no claim is made in `key_insights`. A `note` field in the payload explains
the silence when total_n is between 1 and MIN_SAMPLE.

**Polling**: insights + monthly every 60s (shared main fetch), system health every
30s (independent effect with its own abort refs). Date range persists across tabs.

**Read-only guarantee**: no file writes anywhere in this phase.

---

### Phase F7b — Dashboard & Reports: Conditions + Risk Analysis

Read-only visualization phase. Two new tabs on the existing Dashboard & Reports page, 
powered by re-readable `signals.jsonl` and `paper_trades.jsonl`.

**New API endpoints** (see table above):
`/api/reports/conditions`, `/api/reports/risk`. Both accept optional
`date_from` and `date_to` query params (IST YYYY-MM-DD format); defaults to 
This Month when omitted. All reads wrapped in defensive try/except — 
missing or locked files degrade to empty payloads, never 500.

**New service modules** under `frontend/api/app/services/`:

* `conditions_service.py` — reads `signals.jsonl` (up to 20K lines) and computes:
  - **Pass Rates** — per-condition (C0–C5) count of scans where the condition 
    passed, pass rate (%), and status flag (`active` / `shadow` / `off`).
  - **Funnel** — histogram of "how many conditions passed?" (0/5 to 5/5 buckets 
    plus an "Alerted" bucket for `all_passed=true AND event_type="alert"`).
  - **Bottleneck** — top 5 conditions that block near-miss scans (4/5 scans where 
    the condition was the blocker).
  - **C5 Shadow Analysis** — joins C5-present alerts to `paper_trades.jsonl` TAKEN 
    episodes. Computes win rate and average R separately for "when C5 passed" vs 
    "when C5 failed". If join is incomplete (< 80% coverage), adds a join_note.
  - **DI Alignment** (optional) — spot and option DI alignment percentages. 
    Informational only; does not affect C5 pass/fail.

* `risk_service.py` — reads `paper_trades.jsonl` (up to 20K lines) and computes:
  - **R-Distribution** — histogram buckets: `<-1.0`, `-1.0 to 0`, `0 to 1.0`, 
    `1.0 to 1.5`, `1.5 to 2.5`, `>2.5` (finalized TAKEN trades only).
  - **Equity Curve** — cumulative paper P&L by date with running max drawdown.
  - **Streaks** — current (W5 / L3 / —), max win, max loss.
  - **MFE/MAE** (optional) — average max favorable / adverse excursions in R.
  - **Risk Adherence** — target + range from config; % within range; distribution 
    histogram (`<2500`, `2500–3000`, `3000–3500`, `>3500`) of actual risk per trade.
  - **Payoff** — avg R per winner, avg R per loser, payoff ratio (avg_win / |avg_loss|).

**New routers** `frontend/api/app/routers/conditions.py` and `risk.py`:

* `GET /api/reports/conditions?date_from&date_to` — returns ConditionsReport JSON.
* `GET /api/reports/risk?date_from&date_to` — returns RiskReport JSON.

Both wrap service calls in try/except and return safe defaults on error.

**New chart component**: `web/src/components/charts/Histogram.tsx` — 
recharts BarChart with configurable buckets, colors, axis labels. 
Accepts data with `bucket` / `r_bucket` / `risk_bucket` keys (normalizes 
to a shared `label` key for recharts).

**New types** in `web/src/lib/api.ts`:

* `ConditionPassRate`, `FunnelBucket`, `BottleneckItem`, `C5ShadowStats`, 
  `C5ShadowReport`, `DIAlignment`, `ConditionsReport`.
* `RBucket`, `EquityCurvePoint`, `MaxDrawdown`, `Streaks`, `MfeMAE`, 
  `RiskBucket`, `RiskAdherence`, `Payoff`, `RiskReport`.
* `api.reportsConditions(...)` and `api.reportsRisk(...)` methods.

**New page content** in `web/src/pages/DashboardReports.tsx`:

1. **Condition Analysis (C0–C5) tab**:
   - Condition Pass Rates table (7 rows: condition, label, status badge, 
     scans, passes, pass rate %).
   - Signal Funnel histogram (0/5 through 5/5, plus Alerted).
   - Blocking Conditions ranked list (top 5 near-miss blockers with bar 
     indicators).
   - C5 ADX Shadow Analysis highlight card (amber border): C5 pass rate 
     among fired alerts %; side-by-side comparison (when C5 passed vs failed) 
     with n, win_rate %, avg_R stats; optional join_note for incomplete joins.
   - DI Alignment summary (optional): spot & option DI aligned % with 
     informational note.

2. **Risk Analysis tab**:
   - R-Multiple Distribution histogram.
   - Equity Curve & Drawdown line chart + max drawdown (₹ and R) sub-stats.
   - Current Streaks 3-tile layout (current / max win / max loss).
   - Payoff Metrics 3-tile layout (avg_win_r, avg_loss_r, ratio).
   - MFE / MAE 2-tile layout (optional, only if mfe_R and mae_R fields present).
   - Risk Adherence vs Config: target, range, within-range %; distribution 
     histogram of actual risk amounts.

**Polling and state management**:
- Date range persists across tab switches.
- Both endpoints fetched in parallel when date range changes.
- Polls every 60s (same as existing Performance tab).
- Skeletons while first response is in flight.
- Stale banner on error; last good payload kept visible.

**IST always**: all timestamp parsing and date range filtering use IST.

**Honest join limitation**: C5 → paper trade matching uses 
(symbol, strike, option_type, candle_timestamp) key. If join coverage 
< 80%, service returns an optional `join_note` explaining the limitation 
(e.g., "Limited join coverage: 42% of C5 alerts matched to paper trades"). 
UI displays this note; never fabricates comparison stats.

**Read-only guarantee**: no file writes anywhere in this phase.
`paper_overrides.csv` is displayed read-only; the user edits it
directly outside the UI.

### Phase F7a — Dashboard & Reports (Performance Overview tab)

Read-only analytics phase. No bot source touched, no broker calls, no
writes to `logs/` or `data/`.

**New API endpoint**: `GET /api/reports/performance` (see table above).
All file I/O wrapped in defensive try/except — degraded gracefully on
missing or partial JSONL.

**New router**: `frontend/api/app/routers/reports.py`
* `GET /api/reports/performance?date_from&date_to&agg=daily|weekly|monthly`
  — returns the full performance report. Default range = current IST
  month (start-of-month to today). On any unhandled exception the router
  returns an empty-but-valid payload — never 500.

**New service**: `frontend/api/app/services/reports_service.py`
* Only TAKEN + `paper_role=="representative"` rows are counted (echoes excluded).
* Finalized = outcome not in (None, "NO_DATA"). Open = outcome == "NO_DATA".
* Winners = TP2_HIT | TP1_HIT | TP1_BE. OPEN_SQOFF classified by paper_pnl sign.
* KPI deltas compare the immediately preceding equal-length window.
* Spark series = list of daily_pnl values over the current period (same
  for all 7 KPIs — it's the daily P&L series).
* Monthly table covers ALL historical TAKEN+representative rows,
  regardless of the selected date range.
* Duration section is `null` when no `exit_time` data is present.

**New chart components** under `web/src/components/charts/`:
* `WeekdayBarChart.tsx` — recharts BarChart of Mon–Fri P&L. Green bars
  for positive days, red for negative. Currency tooltip. Empty state.
* `SimpleDonut.tsx` — generic reusable recharts PieChart donut with
  center total count + legend (name · count (pct%)). Empty state.
* `KpiSparkline.tsx` — tiny 80×32 px recharts LineChart (no axes, no
  tooltip, no grid) for inline KPI cards. Returns null when data < 2.

**New page**: `web/src/pages/DashboardReports.tsx` (route
`/dashboard-reports` in `App.tsx`). Layout, top to bottom:

1. **Page header** — title, description, "Last synced HH:MM" + manual
   Refresh button, disabled Export button (Coming soon).
2. **Date-range bar** — presets: This Week / This Month / This Quarter
   / Last 30 Days / Last 90 Days / Custom (default: This Month). Custom
   reveals From/To date inputs. Apply button triggers re-fetch.
3. **Stale banner** — amber ribbon when last fetch failed but old data
   is still showing.
4. **Tab bar** — Performance Overview (functional) | Strategy Insights
   | Condition Analysis (C0–C5) | Risk Analysis | Monthly Summary
   | System Health. Non-functional tabs show a "Coming in a later phase"
   placeholder.
5. **Performance Overview tab**:
   - 7 KPI cards (Total P&L, Total Trades, Win Rate, Profit Factor,
     Avg Win, Avg Loss, Expectancy) with delta badge vs prev period and
     mini KpiSparkline.
   - Cumulative P&L card with Daily / Weekly / Monthly toggle — reuses
     `PnLChart` (ComposedChart bars + line).
   - Two-column row: P&L by Underlying (SimpleDonut) | P&L by Weekday
     (WeekdayBarChart). NIFTY=#2563EB, BANKNIFTY=#7C3AED.
   - Two-column row: Top Winning Trades table | Top Losing Trades table
     (top 5 each). Time / Symbol / Type / Strike+Rel / P&L / Outcome.
   - Two-column row: Outcome Distribution (SimpleDonut) | Trade Duration
     table (if exit_time data present). Outcome colors: TP2_HIT=#16A34A,
     TP1_HIT=#65A30D, SL_HIT=#DC2626, PARTIAL=#F59E0B, WOULD_SKIP=#94A3B8,
     Running=#64748B.
   - Monthly Performance Overview wide table (all-time, sorted month
     desc): Month | Total Trades | Win Rate | Total P&L | Realized |
     Unrealized | Profit Factor | Max Profit | Max Loss.
6. **Footer** — "All times are IST (Asia/Kolkata). Paper P&L; outcomes
   finalize at EOD."

**Polling**: auto-refresh every 60s. Stale-data safety: on fetch error,
keep last good data visible with amber stale banner — never blank.
Skeletons shown while first response is in flight.

---

## Field-name contract (observed from real data)

**`logs/alerts.jsonl`** — one row per fired alert:
`timestamp_ist, time, date, event_type="alert", symbol, strike, relation,
option_type, expiry, trading_symbol, conditions_passed[], conditions_failed[],
all_passed, entry, sl, sl_method, tp1, tp2, tp1_r, tp2_r,
lots, lot_size, total_risk, risk_per_unit, day_type, vix_regime,
vix_multiplier, spot, spot_position, bot_remark, bot_tags,
telegram_short_remark, reasons{}, opt_above_vwap_pct`.

**`logs/signals.jsonl`** — one row per scan/rejection/extended event
(superset of alerts minus the entry/sl/tp fields). `event_type` is one
of `scan`, `rejection`, `would_alert_extended`, `alert`. Condition
names live in `conditions_passed` / `conditions_failed` and are the
single source of truth for the Recent Alerts legend.

**`logs/paper_trades.jsonl`** — one row per paper trade decision:
`alert_id, episode_id, paper_role, date, candle_timestamp, symbol,
strike, relation, option_type, expiry, entry, sl, tp1, tp2, lots,
lot_size, is_expiry_day, decision ("TAKEN"|"SKIPPED"), decision_reason,
slot, outcome ("TP2_HIT"|"TP1_HIT"|"SL_HIT"|"NO_DATA"|"PARTIAL"|"WOULD_SKIP"),
exit_price, exit_time, exit_reason, realized_R, paper_pnl,
paper_pnl_per_unit, mfe, mae, mfe_R, mae_R, max_drawdown_R,
intrabar_ambiguous, fidelity, bot_remark, bot_tags, triggered_caps[]`.

**`logs/state.json`** — daily counters; may be missing on a fresh
machine. Always treated as `{}` when absent. Today's Status reads
`gap_day` from here when present.

If new fields appear in production data, prefer reading them
opportunistically (`.get()`) and updating this doc rather than failing.
