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
* **Sidebar (canonical order):** Overview, Configuration, Instruments,
  Strike & Scanning, Stop Loss, Risk & Money, Conditions (C0–C5),
  Orders, Time Rules, Re-entry Rules, Alerts & Telegram, Paper Trading,
  Trades & Performance, Dashboard & Reports, Logs, Bot Status,
  Settings, About. Footer shows the RUNNING/STOPPED pill, uptime,
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
│       │   ├── charts/                 # NEW — PnLChart, ConditionDonut,
│       │   │                           #       StatPanel, PriceSparkline
│       │   └── config/                 # reusable config primitives (F1)
│       ├── pages/
│       │   ├── Overview.tsx            # v2 design (this phase)
│       │   ├── Configuration.tsx       # F1
│       │   └── Instruments.tsx         # F1
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
| Configuration            | `/configuration`       | **Done** (Feeds / Mode / Instruments tabs; others coming soon) |
| Instruments              | `/instruments`         | **Done**   |
| Strike & Scanning        | `/strike-scanning`     | Pending    |
| Stop Loss                | `/stop-loss`           | Pending    |
| Risk & Money             | `/risk-money`          | Pending    |
| Conditions (C0–C5)       | `/conditions`          | Pending    |
| Orders                   | `/orders`              | Pending    |
| Time Rules               | `/time-rules`          | Pending    |
| Re-entry Rules           | `/reentry-rules`       | Pending    |
| Alerts & Telegram        | `/alerts-telegram`     | Pending    |
| Paper Trading            | `/paper-trading`       | Pending    |
| Trades & Performance     | `/trades-performance`  | Pending    |
| Dashboard & Reports      | `/dashboard-reports`   | Pending    |
| Logs                     | `/logs`                | Pending    |
| Bot Status               | `/bot-status`          | Pending    |
| Settings                 | `/settings`            | Pending    |
| About                    | `/about`               | Pending    |

Pending routes render the shared "Coming soon" placeholder.

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
