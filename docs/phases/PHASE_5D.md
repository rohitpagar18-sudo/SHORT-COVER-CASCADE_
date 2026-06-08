# Phase 5D — Paper-Trade Tracking & First-Alert Selection Layer

Goal: lite reconstruction of TP/SL outcomes for the alert-only window
(the stand-in for Phase 8 broker callbacks), with first-alert-only
discipline so re-fires don't inflate P&L. The layer is **read-only**
over `logs/alerts.jsonl` + the existing 5B-A `data/replay_cache/`.

## Relationship to other phases

- **Phase 5A** — paper layer reads `alerts.jsonl` (event_type=alert).
  The scan / condition (C0–C4) / alert-firing path is untouched.
- **Phase 5B-A** — paper layer REUSES the exit kernel
  `src.dashboard.outcome_replay.replay_alert`. There is **no second
  candle walk** in Phase 5D. The `outcome.py` wrapper only computes
  the extra R-multiple / paper-pnl / drawdown numbers the kernel
  doesn't already emit.
- **Phase 5C** — holiday rows are excluded upstream (`is_holiday_scan`
  pattern). `event_type != "alert"` rows are dropped in
  `episodes.load_alerts_jsonl`.
- **Phase 6.1 (C5 ADX shadow)** — orthogonal. C5 lives on the
  alert-firing side; Phase 5D consumes whatever alerts come out.
- **Phase 7** — backtest harness will call the same 5B-A kernel +
  re-use the same `data/replay_cache/` files. Phase 5D's
  `paper_trades.jsonl` is one of the inputs the backtest can compare
  against.
- **Phase 8 (live orders)** — the broker callback replaces the kernel
  call inside `outcome.py`. The selection layer (D1+D2) stays useful
  as the "should I have taken it" gate.

## Deliverables (as built)

| ID | Module / artifact | What it does |
|----|-------------------|--------------|
| D1 | `src/paper/episodes.py` | Derive `alert_id` at read-time; collapse re-fires into one Episode per `(symbol, option_type)` within `dedup_window_minutes`. ITM1 tie-break on same `candle_timestamp`. |
| D2 | `src/paper/selector.py` | Deterministic TAKEN / SKIPPED gate, always replayed in chronological order. Caps: `max_trades_per_day`, 2-SL circuit breaker (§14), 15-min cooldown (§13), same-strike kill after 2 SLs (§13). |
| D3 | `src/paper/outcome.py` | Wraps the 5B-A kernel. Maps kernel status → paper outcome (`TP2 / TP1_BE / TP1_HIT / SL / HARD_EXIT / OPEN_SQOFF / NO_DATA`). Computes `realized_R`, `paper_pnl = pnl_per_unit × lots × lot_size`, `mfe_R`, `mae_R`, `max_drawdown_R`. Fidelity flag for legacy close-only rows. |
| D4 | `src/paper/persistence.py` | `logs/paper_trades.jsonl` (auto, rewritten idempotently each run); `logs/paper_overrides.csv` (user-owned, created with headers if missing, **never overwritten**). `merge_overrides` — manual always wins. |
| D5 | `src/dashboard/paper_sheets.py` | Three new sheets appended to the quarterly workbook: `Paper Trades`, `Paper Dashboard`, `Echoes (diagnostic, hidden)`. Per-row colors, data bars on `realized_R` / `paper_pnl`, KPI cards via Excel formulas, dropdowns on the manual columns. |
| D6 | `src/paper/backfill.py` + tests | One-shot CLI `python -m src.paper.backfill`; mocked-feed pytest suite. |

End-to-end orchestrator: `src/paper/engine.py` —
`alerts.jsonl → collapse → select → compute_paper_outcome → write`.

## Hard rules honored

1. **No changes** to scan / C0–C4 / alert-firing. `alert_id` is
   derived at read-time (`derive_alert_id`); the bot never injects it.
2. **No second candle walk.** `src/paper/outcome.py` imports
   `from src.dashboard.outcome_replay import replay_alert` and calls
   it for every kernel decision. A dedicated test
   (`test_engine_reuses_kernel_no_second_walk`) inspects the module
   source to enforce this — any future PR that adds an independent
   walk fails the assertion.
3. **No order placement.**
4. **Config-driven.** Every threshold, time, ladder, and path lives
   under `paper_trading:` in `config/config.yaml`. No hardcoded numbers.
5. **IST everywhere.** `derive_alert_id` re-localizes naive timestamps;
   `Episode.first_candle_ts` / `window_end` are timezone-aware.
6. **Tests mock the feed.** No live Kite/Upstox calls.
7. **Holiday rows excluded.** `load_alerts_jsonl` filters
   `event_type != "alert"`; gap/holiday/data_issue rows never enter
   the engine.
8. **Manual overrides persist.** `paper_overrides.csv` is created
   empty when missing and is otherwise read-only to the engine. The
   regeneration round-trip is tested
   (`test_overrides_survive_paper_trades_regeneration`).

## Episode model (the core rule)

A re-fire is the *same* paper trade as the first alert if:

- the episode-key tuple matches
  (default `[symbol, option_type]`), AND
- the new alert's `candle_timestamp` is within
  `dedup_window_minutes` (default 20) of the episode's first
  `candle_timestamp`.

The episode's **representative** is the earliest `candle_timestamp`.
For the rare ties (multiple strikes firing on the same candle), the
`relation_priority` list breaks them — default
`[ITM1, ATM, ITM2, ITM3, OTM1, OTM2, OTM3]`. Every non-representative
becomes a `paper_role="echo"` row and lives on the hidden
`Echoes (diagnostic)` sheet. Echoes are *never* counted in TAKEN P&L.

## Selection gate (TAKEN / SKIPPED reasons)

Replayed in chronological order over the representatives. Caps are
checked in this order on every row:

1. **circuit breaker** — `state.sl_count >= circuit_breaker_sl_count`
   (default 2) → `"skipped: circuit breaker (N paper SL)"`.
2. **same-strike kill** — strike has 2 SLs on the day →
   `"skipped: same-strike killed (2 paper SL)"`. Same-strike state
   keys off the strike NUMBER, per the locked-in decision in
   `CLAUDE.md`.
3. **cooldown after SL** — `ts < last_sl_time + cooldown` →
   `"skipped: cooldown 15m after SL"`.
4. **daily slot cap** — `taken_count >= max_trades_per_day` →
   `"skipped: daily cap (3) reached"`.
5. Otherwise → `"taken (slot N/M)"`.

The selector accepts an `outcome_resolver(rep_row) -> str | None`
callback so the SL-driven caps can react to each TAKEN trade's
outcome. The engine wires this up to a memoizing call to
`compute_paper_outcome`, so candles are only fetched once per
representative.

## Outcome mapping (§9 R-ladder)

> CHANGED 2026-06-08: the R-ladder is sourced directly from `risk_reward`. There are no paper-only override knobs; full SL is −1R by definition.

| Kernel status | Paper outcome | Normal-day R | Expiry-day R |
|---------------|---------------|--------------|--------------|
| `SL_HIT`      | `SL_HIT`      | −1R          | −1R          |
| `HARD_EXIT`   | `HARD_EXIT`   | −1R          | −1R          |
| `TP2_HIT`     | `TP2_HIT`     | +2.5R (= `risk_reward.normal_day_tp2_r`) | +3.0R (= `risk_reward.expiry_day_tp2_r`) |
| `PARTIAL` (TP1 banked, second leg SL/breakeven/trailed) | `TP1_BE` | +0.75R (= 0.5 × `risk_reward.normal_day_tp1_r`) | +1.0R (= 0.5 × `risk_reward.expiry_day_tp1_r`) |
| `TP1_HIT` (TP1 banked, second leg EOD-flat ≥ SL) | `TP1_HIT` | actual `pnl/R` | actual `pnl/R` |
| `EOD_FLAT`    | `OPEN_SQOFF`  | actual `pnl/R` | actual `pnl/R` |
| (no candles)  | `NO_DATA`     | 0            | 0            |

The SL method used by the kernel is whichever `stop_loss.method`
(1/2/3) is configured live — there is no paper-only SL toggle. Under
Method 3, the `PARTIAL` second-leg exit reflects the SMA-trailed SL,
not breakeven.

`paper_pnl = auto_pnl_per_unit × lots × lot_size`. Lot size is
read from `config.instruments.{nifty,banknifty}_lot_size` — never
hardcoded.

## Config (paper_trading block)

> CHANGED 2026-06-08: paper_trading is now just the episode block + 4 caps + paths. The `tp*_R_*` / `tp1_then_be_R_*` / `sl_R` / `selection_mode` knobs are removed. TP1/TP2 multipliers and the SL method are read straight from the `risk_reward` and `stop_loss` blocks — single source of truth. Selection is always chronological; conviction-mode was over-engineering and is gone. Full SL is −1R by definition. Old prose removed; see git history.

```yaml
paper_trading:
  enabled: ON
  episode_key: [symbol, option_type]
  dedup_window_minutes: 20
  relation_priority: [ITM1, ATM, ITM2, ITM3, OTM1, OTM2, OTM3]
  max_trades_per_day: 3
  circuit_breaker_sl_count: 2
  cooldown_minutes_after_sl: 15
  same_strike_kill_after_2_sl: ON
  paper_trades_path: logs/paper_trades.jsonl
  paper_overrides_path: logs/paper_overrides.csv
```

## Files

```
src/paper/
├── __init__.py
├── episodes.py        — D1: alert_id, episode collapse, ITM1 tie-break
├── selector.py        — D2: TAKEN / SKIPPED gate (caps from §13/§14)
├── outcome.py         — D3: wraps 5B-A kernel, adds R / paper_pnl / drawdown_R
├── persistence.py     — D4: paper_trades.jsonl + paper_overrides.csv merge
├── engine.py          — end-to-end pipeline (used by backfill + dashboard)
└── backfill.py        — D6: python -m src.paper.backfill

src/dashboard/
└── paper_sheets.py    — D5: Paper Trades / Paper Dashboard / Echoes

tests/
├── test_paper_episodes.py   — derive_alert_id, collapse, ITM1 tie-break
├── test_paper_selector.py   — daily cap, cooldown, breaker, same-strike kill
├── test_paper_outcome.py    — kernel-mapping for each status + close-only
├── test_paper_persistence.py — write/read, override merge, regen survival
└── test_paper_engine.py     — end-to-end + "no second walk" enforcement
```

## What Phase 5D does NOT do

- No order placement. That is Phase 8.
- No second outcome engine. We import + call the 5B-A kernel.
- No changes to the live scan/alert path. The bot still fires alerts
  on every passing 5-min candle, exactly as before.
- No live-feed dependency for the dashboard refresh — the workbook
  reads from `paper_trades.jsonl` + `paper_overrides.csv`.

## Ambiguous strategy-doc points we had to decide

| Point | Decision | Reason |
|-------|----------|--------|
| `TP1_HIT` (TP1 banked, second leg EOD-flat ≥ SL) R-multiple | Use the kernel's actual `pnl/R` rather than `0.5 × tp1_R` | The kernel already returned the real close price; using the canonical 0.75R label would mis-represent strong-finish days. SL_HIT and TP2_HIT keep the canonical labels because their P&L is deterministic. |
| `OPEN_SQOFF` outcome label | Renamed from kernel's `EOD_FLAT` | "EOD_FLAT" was confusing alongside `TP1_HIT` (which is also EOD-flat). `OPEN_SQOFF` = "still open, forced out at hard squareoff". |
| `HARD_EXIT` R | −1R (treated as full SL) | Strategy doc §7 treats hard-exit-below-VWAP as a discretionary stop — same magnitude as SL for paper accounting. |
| Tie-break beyond `candle_timestamp` + `relation_priority` | File order | Stable, deterministic, matches "first seen wins" intuition. |
| `outcome_resolver` returning `None` (unknown outcome) | Treat as **not SL** for cap counting | A real trader would have observed *something*; "unknown" is closer to "in progress" than to "lost". Keeps the selector deterministic on close-only fallback. |
| Whether to compute outcomes for SKIPPED reps | Yes | The dashboard shows the what-would-have-happened column. Echoes (paper_role=echo) are NOT outcome-computed in the dashboard path (only in the diagnostic `--all-alerts` distribution from the backfill CLI). |

## Acceptance

- **pytest**: 362 (pre-5D) → 390 (+28 new) — all green.
- **June backfill** (cache-only, no live feed): 1 raw alert →
  1 episode (1.00:1). TAKEN: `{NO_DATA: 1}` (no replay cache for May
  data on dev machine). The shape is exercised by the test suite;
  the headline collapse-ratio will become meaningful once 30 days of
  Phase 6 alerts + caches accumulate on the live machine.
- **Manual override survives regen**: verified — appended a row to
  `logs/paper_overrides.csv`, ran the backfill, override unchanged.
  Also pinned by `test_overrides_survive_paper_trades_regeneration`.
- **No second candle walk** in `src/paper/outcome.py` — pinned by
  `test_engine_reuses_kernel_no_second_walk`.
