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

## Folder layout

```
frontend/
├── api/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, SPA mount
│   │   ├── paths.py                 # PROJECT_ROOT resolution (env SCC_ROOT)
│   │   ├── time_utils.py            # IST helpers
│   │   ├── models/                  # Pydantic response schemas
│   │   ├── routers/                 # /health, /overview, /bot/status, /config
│   │   └── services/                # config_write_service, state, signals, paper, botstatus
│   ├── tests/
│   │   └── test_roundtrip_noop.py   # acceptance test: no-op PUT leaves file byte-identical
│   └── requirements.txt
├── web/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts               # /api proxy to :8000 in dev
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx, App.tsx
│       ├── context/
│       │   └── ConfigContext.tsx    # ConfigProvider + useConfig hook
│       ├── components/
│       │   ├── Sidebar, Header, Card, ProgressBar, ComingSoon
│       │   └── config/              # reusable config field primitives + SectionShell
│       │       ├── Toggle.tsx, NumberField.tsx, TextField.tsx
│       │       ├── SelectField.tsx, RadioCards.tsx, SectionShell.tsx
│       │       └── sections/        # FeedsSection, ModeSection, InstrumentsSection
│       ├── pages/
│       │   ├── Overview.tsx
│       │   ├── Configuration.tsx    # tabbed: Feeds / Mode / Instruments / (coming soon)
│       │   └── Instruments.tsx      # standalone, reuses InstrumentsSection
│       └── lib/                     # api.ts (typed fetch + getConfig/putConfig), format.ts
├── docs/
│   └── FRONTEND_PLAN.md             # this file
└── run_ui.bat                       # single-port launcher
```

---

## How to run

### Production mode (single port, recommended)

```cmd
frontend\run_ui.bat
```

What it does:
1. Verifies the bot's `venv\` exists.
2. Installs `fastapi`, `uvicorn`, `ruamel.yaml`, `pydantic` into the
   venv if missing.
3. If `frontend\web\dist\` is missing, runs `npm install` + `npm run
   build` (requires Node.js LTS — install from https://nodejs.org).
4. Starts uvicorn on port `8000` (override with `run_ui.bat 9000`).

Open http://localhost:8000/ — the SPA loads from the same port and
calls `/api/*` on the same origin.

### Dev mode (hot reload)

Terminal 1 — API:
```cmd
cd frontend\api
..\..\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — Vite dev server:
```cmd
cd frontend\web
npm install        :: first time only
npm run dev
```

Open http://localhost:5173/ — Vite proxies `/api` to :8000.

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
| GET    | `/api/health`    | `{ok, now_ist, project_root, config_present}` | Liveness — does not touch bot files beyond `stat()`. |
| GET    | `/api/bot/status`| `{status, last_activity_ist}` | Polled by sidebar every 15s. |
| GET    | `/api/overview`  | Aggregated Overview payload (see `app/models/overview.py`). | Single round-trip for the Overview page. |
| GET    | `/api/config`    | Full `config.yaml` as plain JSON dict (ON/OFF → bool). | Used by the config editor pages. |
| PUT    | `/api/config`    | `{ok, updated, restart_required: [key,...], message}` | Partial nested change dict. 422 on validation error. |

All future endpoints will be added here as they ship.

---

## Pages status

| Sidebar item             | Route                  | Status   |
|--------------------------|------------------------|----------|
| Overview                 | `/overview`            | **Done** |
| Configuration            | `/configuration`       | **Done** (Feeds / Mode / Instruments tabs; others coming soon) |
| Instruments              | `/instruments`         | **Done** (standalone InstrumentsSection) |
| Strike & Scanning        | `/strike-scanning`     | Pending  |
| Risk & Money             | `/risk-money`          | Pending  |
| Conditions               | `/conditions`          | Pending  |
| Orders                   | `/orders`              | Pending  |
| Time & Re-entry          | `/time-reentry`        | Pending  |
| Alerts & Telegram        | `/alerts-telegram`     | Pending  |
| Paper Trading            | `/paper-trading`       | Pending  |
| Trades & Performance     | `/trades-performance`  | Pending  |
| Logs Viewer              | `/logs`                | Pending  |
| Dashboard & Reports      | `/dashboard-reports`   | Pending  |
| Bot Status               | `/bot-status`          | Pending  |
| Settings                 | `/settings`            | Pending  |
| About                    | `/about`               | Pending  |

Pending routes render a shared "Coming soon" placeholder.

---

## Field-name contract (observed from real data)

Recorded in `frontend/api/app/services/signals_service.py` and
`paper_service.py` headers — kept here for quick reference.

**`logs/alerts.jsonl`** — one row per fired alert:
`timestamp_ist, time, date, event_type="alert", symbol, strike, relation,
option_type, expiry, trading_symbol, conditions_passed[], all_passed,
entry, sl, tp1, tp2, lots, lot_size, total_risk, risk_per_unit,
day_type, vix_regime, vix_multiplier, bot_remark, bot_tags,
telegram_short_remark`.

**`logs/signals.jsonl`** — one row per scan/rejection/extended event
(superset of alerts minus the entry/sl/tp fields).

**`logs/paper_trades.jsonl`** — one row per paper trade decision:
`alert_id, episode_id, paper_role, date, candle_timestamp, symbol,
strike, relation, option_type, expiry, entry, sl, tp1, tp2, lots,
lot_size, is_expiry_day, decision ("TAKEN"|"SKIPPED"), decision_reason,
slot, outcome ("TP2_HIT"|"TP1_HIT"|"SL_HIT"|"NO_DATA"|"PARTIAL"|"WOULD_SKIP"),
exit_price, exit_time, exit_reason, realized_R, paper_pnl,
paper_pnl_per_unit, mfe, mae, mfe_R, mae_R, max_drawdown_R,
intrabar_ambiguous, fidelity, bot_remark, bot_tags, triggered_caps[]`.

If new fields appear in production data, prefer reading them
opportunistically (`.get()`) and updating this doc rather than failing.
