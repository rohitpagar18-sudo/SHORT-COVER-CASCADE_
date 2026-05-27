# Phase 5B — Strategy Dashboard + ML Data Store + Bot Remarks

**Goal:** Layer human-readable Excel dashboards and a machine-readable
Parquet ML store on top of the alert-only bot built in `PHASE_5A.md`.
Add bot-generated entry remarks (`bot_remark` / `bot_tags`), a Telegram
"Insight:" line, directional gap labels (`GAP_UP` / `GAP_DOWN` /
`GAP_UP_DISABLED` / `GAP_DOWN_DISABLED`), a config-driven C1 threshold,
and a `would_alert_extended` event type for capturing 4/5 borderline
scans. Dashboard auto-syncs in the orchestrator's `finally` block so it
runs on clean exit, Ctrl+C, or unhandled exception.

This document absorbs the original PHASE_5_2_FINAL prompt, the
PRE_PHASE_5_2_CHECK pre-flight gate, and the PHASE_5_2_1 finally-block
hotfix. The dashboard-sync code is shown in its **final form only** —
the deprecated 15:35 in-loop poll from the first 5.2 draft is not
reproduced.

This document is internally split:

- **Strategy / behaviour deltas** (config, C1, directional gap)
- **ML data / database layer** (Parquet writer + schema doc)
- **Excel dashboard layer** (8-sheet workbook)
- **Orchestrator wiring** (the small set of hooks that connect 5A to 5B)

The two layers can in principle be rebuilt independently — the writer
emits Parquet, the Excel builder reads Parquet. If you only need the
ML store, build §3.1-3.3 and skip the Excel sheet code in §3.4. If you
only need the human dashboard, you still need the writer because
`excel_builder.py` reads from the monthly Parquet files.

**Time estimate:** 4 hours code + verification pass.

## Deliverables

- Quarterly rotating Excel dashboards at `logs/dashboards/dashboard_YYYY_QN.xlsx`
- Monthly Parquet ML data files at `data/scc_data_YYYY-MM.parquet`
- `data/schema.md` — committed documentation of every Parquet column
- Two-pass bot remarks: entry-time `bot_remark` + post-fill `outcome_remark`
- Structured `bot_tags` for ML queries
- Directional gap labels: `GAP_UP` / `GAP_DOWN` (and `_DISABLED` variants)
- Configurable C1 late-entry filter (`c1_max_distance_pct`, default 30)
- `would_alert_extended` event for 4/5 scans where only C1 fails AND
  the option sits in the extended zone (30 < pct ≤ 50 % above VWAP)
- Outcome cell coloring in Order Place sheet (TP2 green, TP1 light
  green, SL red, PARTIAL yellow, WOULD_SKIP grey)
- 4 charts on Strategy Dashboard sheet (Wins by Relation, Alerts by
  VIX, Alerts by Time of Day, Cumulative P&L)
- Telegram alert gains an "Insight:" line
- `finally`-block dashboard sync — runs on clean exit, Ctrl+C, or
  exception (Phase 5.2.1 fix). Skipped on weekends and when the
  toggle is OFF.
- Best-effort Excel→Parquet back-sync of user-filled outcome columns
- Manual entry point: `update_dashboard.bat` / `scripts/update_dashboard.py`

## What Phase 5B does NOT do

- No order placement (Phase 8)
- No backtest harness (Phase 7)
- No paper-trade simulation — outcome columns are filled **manually**
  by the user in the Order Place sheet, then back-synced to Parquet
- No live ML inference — `bot_tags` are written but not consumed by
  the strategy

## Architecture

```
logs/                                  ← Bot runtime (Phase 5A)
  signals.jsonl                        ← scan / rejection / data_issue
  alerts.jsonl                         ← 5/5 alerts
  gap_log.jsonl                        ← one row per startup
  bot.log
  dashboards/                          ← NEW (Phase 5B)
    dashboard_2026_Q2.xlsx
    dashboard_2026_Q3.xlsx

data/                                  ← NEW (Phase 5B)
  schema.md                            ← Column documentation (committed)
  scc_data_2026-05.parquet             ← One unified file per month
  scc_data_2026-06.parquet

src/dashboard/                         ← NEW (Phase 5B)
  __init__.py
  data_writer.py                       ← JSONL → Parquet + Excel notes back
  excel_builder.py                     ← Parquet → quarterly .xlsx
  remarks.py                           ← Generate bot_remark + bot_tags
```

Data flow:

```
Bot runs all day → writes raw JSONL
      ↓
[bot exit / Ctrl+C / exception → finally block]
[or manual: update_dashboard.bat]
      ↓
data_writer.sync_jsonl_to_parquet() → data/scc_data_YYYY-MM.parquet
      ↓
excel_builder.update_dashboard() → logs/dashboards/dashboard_YYYY_QN.xlsx
      ↓
data_writer.sync_excel_notes_to_parquet() → back-fill outcome columns
```

Key design principles:

1. **Quarterly Excel, monthly Parquet** — quarterly is what humans want
   to flip through; monthly keeps Parquet files tractable.
2. **Idempotent** — every sync function can be re-run safely. Dedup
   key is `(timestamp_ist, event_type, symbol, strike, option_type)`.
3. **Manual columns preserved** — running sync again does not wipe the
   user-filled `order_status`, `exit_price`, `pnl_rupees`, or
   `user_notes` cells in Order Place.
4. **Excel-missing never crashes the bot** — every Excel read is wrapped
   in try/except; absent openpyxl, missing workbook, or unreadable
   sheet just yields an empty frame.
5. **`event_type` is the primary axis** — all downstream filtering keys
   off it. The six values are documented in `data/schema.md`.

---

## STEP 1 — Pre-flight verification

Before adding any Phase 5B code, confirm Phase 5A has been running long
enough to produce meaningful JSONL. Skip this if you're rebuilding from
scratch — it's a sanity check, not a build step.

Quick checks:

```cmd
:: 1. Are the three JSONL files present and growing?
dir logs\signals.jsonl logs\alerts.jsonl logs\gap_log.jsonl

:: 2. Does signals.jsonl contain at least scan + rejection + data_issue?
findstr /c:"\"event_type\": \"scan\""       logs\signals.jsonl | find /c /v ""
findstr /c:"\"event_type\": \"rejection\""  logs\signals.jsonl | find /c /v ""
findstr /c:"\"event_type\": \"data_issue\"" logs\signals.jsonl | find /c /v ""

:: 3. Does gap_log.jsonl have a row with a Phase 5A "decision" value?
type logs\gap_log.jsonl | findstr "decision"

:: 4. Are timestamps IST-tagged?
type logs\signals.jsonl | findstr "+05:30" | find /c /v ""

:: 5. Confirm secrets.env still has TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

:: 6. Confirm pytest still passes (~210 tests)
pytest tests\ -v
```

Anomalies to investigate before continuing:

- Empty JSONL → bot never finished a scan. Run it first.
- No `data_issue` rows → not a problem (only appears on mid-session
  restarts). Confirm `data_issue` is at least handled in 5A code.
- Timestamps without `+05:30` → 5A bug; do not proceed.

---

## STEP 2 — Strategy / behaviour deltas

### 2.1 — `requirements.txt`

Add (preserve existing):

```
openpyxl>=3.1.0
pyarrow>=14.0.0
pandas>=2.0.0
```

### 2.2 — `config/config.yaml`

Add a `conditions` section (extend if present):

```yaml
conditions:
  c1_max_distance_pct: 30          # Reject alerts where opt > 30% above own VWAP.
                                   # Strategy doc default. Strikes 30-50%
                                   # above VWAP logged for analysis but do
                                   # NOT fire alerts.
  c1_extended_zone_enabled: true   # Log would_alert_extended events
  c1_extended_zone_max_pct: 50     # Upper bound for extended zone logging
```

Add to `logging`:

```yaml
logging:
  log_extended_zone: true          # Write would_alert_extended events
```

Add a `dashboard` section:

```yaml
dashboard:
  auto_trigger_at_1535: true       # Run sync in finally block on bot exit
  excel_rotation: "quarterly"      # Excel files rotate per quarter
  parquet_rotation: "monthly"      # Parquet files split monthly
  send_eod_dashboard_link: false   # Reserved — future Telegram attachment

  outcome_categories:
    - TP2_HIT
    - TP1_HIT
    - SL_HIT
    - PARTIAL
    - WOULD_SKIP
```

> Note on the toggle name: `auto_trigger_at_1535` predates Phase 5.2.1.
> The behaviour is now "run in `finally` on bot exit" — the time stamp
> in the name is preserved for backwards compatibility. Treat it
> as the on/off switch, not as a wall-clock setting.

### 2.3 — `src/conditions/c1_option_price_vwap.py` (config-driven)

The C1 late-entry filter now reads its threshold from config rather
than hardcoding 30. Returns `(passed, reason, opt_above_vwap_pct)` —
the third value is consumed by the orchestrator's
`would_alert_extended` logic (§4.3).

```python
"""C1 — Option Price Above VWAP on a Green Candle.

On the option's own 5-minute chart the current candle must be GREEN
(close > open) and close above the option's session VWAP. Strategy doc
section 5 also defines the late-entry rule: if the candle has already
moved ``c1_max_distance_pct`` (config-driven, default 30%) or more above
VWAP, do not chase — wait for a retrace.

Pure function: in → ``(bool, reason, opt_above_vwap_pct)``, no I/O,
no logging, no raises.
"""

from __future__ import annotations

from src.indicators.calculator import IndicatorSnapshot


def check_c1(
    snapshot: IndicatorSnapshot, late_entry_threshold_pct: float
) -> tuple[bool, str, float]:
    """Evaluate C1 on the supplied option snapshot.

    Args:
        snapshot: option IndicatorSnapshot for the latest 5m candle.
        late_entry_threshold_pct: from ``config.conditions.c1_max_distance_pct``.

    Returns:
        ``(passed, reason, opt_above_vwap_pct)``.

        ``opt_above_vwap_pct`` is always populated (even on failure
        cases) so Phase 5B can log it and decide whether to fire a
        ``would_alert_extended`` event.
    """
    close = snapshot.close
    vwap = snapshot.vwap
    is_green = snapshot.is_green

    if vwap <= 0:
        return False, "C1 FAIL: VWAP not yet available", 0.0

    opt_above_vwap_pct = ((close - vwap) / vwap) * 100.0

    if not is_green:
        return False, (
            f"C1 FAIL: candle is RED (close {close:.2f} <= open {snapshot.open:.2f})"
        ), opt_above_vwap_pct

    if close <= vwap:
        return False, f"C1 FAIL: close {close:.2f} not above VWAP {vwap:.2f}", opt_above_vwap_pct

    if opt_above_vwap_pct >= late_entry_threshold_pct:
        return False, (
            f"C1 FAIL (LATE ENTRY): close {close:.2f} is {opt_above_vwap_pct:.1f}% above "
            f"VWAP {vwap:.2f} (threshold {late_entry_threshold_pct}%) — wait for retrace"
        ), opt_above_vwap_pct

    return True, (
        f"C1 PASS: green candle, close {close:.2f} above VWAP {vwap:.2f} "
        f"({opt_above_vwap_pct:.1f}% above, under {late_entry_threshold_pct}% threshold)"
    ), opt_above_vwap_pct
```

Also update `src/conditions/all_conditions.py` (or wherever C1 is
called) so the third return value `opt_above_vwap_pct` is captured on
the result object that the orchestrator inspects.

### 2.4 — Directional gap labels

Replace the Phase 5A label set (`NORMAL` / `GAP_DAY` /
`GAP_DETECTED_BUT_DISABLED`) with the directional set. This is a
locally-contained change to `_detect_gap_day` and to
`TelegramAlerter._format_gap_line`.

**In `src/main.py`, end of `_detect_gap_day` — replace the tri-state
decision block with:**

```python
# Phase 5.2: directional labels. The per-symbol ``triggers`` flag
# already honours ``direction`` ("both" / "up" / "down"), so we use
# *that* to gate which side counts — a -1.2% gap with direction="up"
# leaves triggers=False and produces NORMAL.
any_up = any(
    info.get("triggers") and (info.get("gap_pct") or 0.0) >= threshold
    for info in gap_info["per_symbol"].values()
)
any_down = any(
    info.get("triggers") and (info.get("gap_pct") or 0.0) <= -threshold
    for info in gap_info["per_symbol"].values()
)

if any_up and enabled:
    gap_info["decision"] = "GAP_UP"
elif any_down and enabled:
    gap_info["decision"] = "GAP_DOWN"
elif any_up:
    gap_info["decision"] = "GAP_UP_DISABLED"
elif any_down:
    gap_info["decision"] = "GAP_DOWN_DISABLED"
else:
    gap_info["decision"] = "NORMAL"
is_gap_day = gap_info["decision"] in ("GAP_UP", "GAP_DOWN")

self._log_gap(gap_info)
return is_gap_day, gap_info
```

**In `src/alerts/telegram_bot.py`, expand `_format_gap_line` to handle
the new labels (keep the legacy ones for replay-compatibility):**

```python
if decision == "GAP_UP":
    verdict = "⚠️ GAP UP — 10:15 start"
elif decision == "GAP_DOWN":
    verdict = "⚠️ GAP DOWN — 10:15 start"
elif decision == "GAP_UP_DISABLED":
    verdict = "⚠ GAP UP detected (rule OFF) — 9:45 start"
elif decision == "GAP_DOWN_DISABLED":
    verdict = "⚠ GAP DOWN detected (rule OFF) — 9:45 start"
elif decision == "GAP_DAY":            # legacy 5A label
    verdict = "⚠️ GAP DAY — 10:15 start"
elif decision == "GAP_DETECTED_BUT_DISABLED":   # legacy 5A label
    verdict = f"⚠ Gap >{threshold}% but rule OFF — 9:45 start"
else:
    verdict = "✓ Normal day — 9:45 start"
```

The legacy branches preserve the ability to replay older `gap_log.jsonl`
rows through the dashboard.

---

## STEP 3 — Dashboard module (`src/dashboard/`)

### 3.1 — `src/dashboard/remarks.py`

Pure-function bot-remark + tag generator. The orchestrator's
`_fire_alert` calls `generate_remark_and_tags()` at alert time;
`sync_excel_notes_to_parquet` calls `generate_outcome_remark()` after
the user fills `order_status` in Excel.

```python
"""Phase 5.2 — Bot remark + tag generation.

Pure functions, no I/O. The orchestrator calls ``generate_remark_and_tags``
at alert time; the Excel→Parquet back-sync calls ``generate_outcome_remark``
after the user fills ``order_status`` in the Order Place sheet.
"""

from __future__ import annotations

from typing import List, Tuple


# ---------------- Zone helpers ----------------

def _vwap_zone(opt_above_vwap_pct: float) -> Tuple[str, str]:
    p = opt_above_vwap_pct
    if p < 10:  return ("fresh_breakout", f"opt {p:.0f}% above VWAP (fresh)")
    if p < 20:  return ("clean_entry",    f"opt {p:.0f}% above VWAP")
    if p < 25:  return ("mid_entry",      f"opt {p:.0f}% above VWAP (mid-zone)")
    return ("late_entry", f"opt {p:.0f}% above VWAP (near filter)")


def _rsi_zone(rsi: float) -> Tuple[str, str]:
    if rsi < 55:  return ("low_rsi",      f"RSI {rsi:.0f} early momentum")
    if rsi < 65:  return ("moderate_rsi", f"RSI {rsi:.0f} moderate")
    if rsi < 75:  return ("strong_rsi",   f"RSI {rsi:.0f} healthy zone")
    return ("high_rsi", f"RSI {rsi:.0f} high momentum")


def _oi_strength(oi: float, oi_ma: float) -> Tuple[str, str]:
    if oi_ma <= 0:  return ("oi_unknown", "OI data unclear")
    pct_below = ((oi_ma - oi) / oi_ma) * 100.0
    if pct_below > 15:  return ("strong_oi",     f"OI {pct_below:.0f}% below MA (strong cover)")
    if pct_below > 8:   return ("moderate_oi",   f"OI {pct_below:.0f}% below MA")
    if pct_below > 0:   return ("weak_oi",       f"OI {pct_below:.0f}% below MA (marginal)")
    return ("no_oi_signal", "OI not below MA — C2 should not have passed")


def _volume_strength(volume: float, volume_ma: float) -> Tuple[str, str]:
    if volume_ma <= 0:  return ("vol_unknown", "vol data unclear")
    ratio = volume / volume_ma
    if ratio > 2.0:  return ("explosive_volume", f"vol {ratio:.1f}× MA (explosive)")
    if ratio > 1.5:  return ("high_volume",      f"vol {ratio:.1f}× MA")
    if ratio > 1.2:  return ("moderate_volume",  f"vol {ratio:.1f}× MA")
    return ("low_volume", f"vol {ratio:.1f}× MA (marginal)")


def _time_zone(time_hhmm: str) -> Tuple[str, str]:
    h, m = int(time_hhmm[:2]), int(time_hhmm[3:5])
    minutes = h * 60 + m
    if minutes < 600:  return ("opening",         "opening hour")
    if minutes < 660:  return ("morning",         "morning push")
    if minutes < 720:  return ("mid_morning",     "mid-morning")
    if minutes < 780:  return ("lunch",           "lunch session")
    if minutes < 840:  return ("early_afternoon", "early afternoon")
    return ("afternoon", "afternoon")


def _vix_context(vix_regime: str) -> Tuple[str, str]:
    m = {
        "LOW":       ("low_vix",      "LOW VIX (0.85× SL)"),
        "NORMAL":    ("normal_vix",   ""),
        "ELEVATED":  ("elevated_vix", "ELEVATED VIX (1.25× SL)"),
        "HIGH":      ("high_vix",     "HIGH VIX (1.5× SL)"),
    }
    return m.get(vix_regime, ("normal_vix", ""))


def _expiry_context(is_expiry_day: bool) -> Tuple[str, str]:
    if is_expiry_day:
        return ("expiry_day", "expiry-day TP 2R/3R applied")
    return ("normal_day", "")


def _sequence_context(daily_sl_count: int, daily_alert_count: int) -> Tuple[str, str]:
    if daily_alert_count == 0:
        return ("first_alert", "first alert of day")
    if daily_sl_count > 0:
        return ("after_sl", f"after {daily_sl_count} SL today — caution")
    return (f"alert_{daily_alert_count + 1}", f"{daily_alert_count + 1}th alert of day")


# ---------------- Public API ----------------

def generate_remark_and_tags(snapshot: dict, context: dict) -> Tuple[str, str]:
    """Generate entry-time bot_remark (human, ~25 words) and bot_tags (CSV)."""
    observations: List[str] = []
    tags: List[str] = []

    t, p = _vwap_zone(snapshot["opt_above_vwap_pct"]);  tags.append(t); observations.append(p)
    t, p = _rsi_zone(snapshot["rsi"]);                  tags.append(t); observations.append(p)
    t, p = _oi_strength(snapshot["oi"], snapshot["oi_ma"]);     tags.append(t); observations.append(p)
    t, p = _volume_strength(snapshot["volume"], snapshot["volume_ma"]); tags.append(t); observations.append(p)
    t, p = _time_zone(context["time_hhmm"]);            tags.append(t); observations.append(p) if p else None
    t, p = _vix_context(context.get("vix_regime", "NORMAL"));   tags.append(t)
    if p: observations.append(p)
    t, p = _expiry_context(context.get("is_expiry_day", False)); tags.append(t)
    if p: observations.append(p)
    t, p = _sequence_context(
        context.get("daily_sl_count", 0),
        context.get("daily_alert_count", 0),
    )
    tags.append(t); observations.append(p)

    verdict = _verdict(snapshot, observations)

    primary = observations[:4]
    secondary = [o for o in observations[4:] if o][:1]
    remark = f"{verdict} — " + ", ".join(primary + secondary) + "."
    return remark, ",".join(tags)


def _verdict(snapshot: dict, observations: List[str]) -> str:
    p = snapshot["opt_above_vwap_pct"]
    rsi = snapshot["rsi"]
    oi_ratio = snapshot["oi"] / snapshot["oi_ma"] if snapshot["oi_ma"] > 0 else 1.0
    vol_ratio = snapshot["volume"] / snapshot["volume_ma"] if snapshot["volume_ma"] > 0 else 1.0

    strong = p < 15 and 60 <= rsi < 75 and oi_ratio < 0.85 and vol_ratio > 1.5
    if strong:
        return "5/5 strong"

    marginal = rsi < 55 or oi_ratio > 0.93 or vol_ratio < 1.2 or p > 22
    if marginal:
        return "5/5 borderline"

    return "5/5 clean"


def generate_outcome_remark(
    alert_data: dict,
    outcome: str,
    exit_price: float | None = None,
    pnl: float | None = None,
) -> str:
    """Outcome remark based on alert quality + user-marked outcome."""
    bot_remark = alert_data.get("bot_remark", "")
    is_strong = "strong" in bot_remark
    is_marginal = "borderline" in bot_remark

    if outcome == "TP2_HIT":
        if is_strong:
            return f"Held to TP2 (₹{exit_price:.2f}) — strong setup played out. 2.5R captured."
        return f"Held to TP2 (₹{exit_price:.2f}) — 2.5R captured. Outcome confirmed setup."
    if outcome == "TP1_HIT":
        return f"TP1 hit at ₹{exit_price:.2f} — 1.5R captured. Reversed before TP2."
    if outcome == "SL_HIT":
        if is_strong:
            return f"SL hit at ₹{exit_price:.2f} — unusual reversal on strong setup."
        if is_marginal:
            return f"SL hit at ₹{exit_price:.2f} — marginal entry showed in outcome."
        return f"SL hit at ₹{exit_price:.2f} — reversed quickly."
    if outcome == "WOULD_SKIP":
        return "Skipped post-review — your judgement overrode 5/5."
    if outcome == "PARTIAL":
        return f"Partial exit — manual decision, P&L ₹{pnl:.0f}."
    return ""


def telegram_short_remark(bot_remark: str) -> str:
    """Pick verdict + 1 key observation for the Telegram Insight: line."""
    if not bot_remark:
        return ""
    parts = bot_remark.split(" — ", 1)
    if len(parts) < 2:
        return bot_remark[:80]
    verdict, rest = parts
    obs = rest.split(", ")
    if len(obs) >= 2:
        return f"{verdict} — {obs[0]}, {obs[1]}"
    return f"{verdict} — {obs[0]}" if obs else verdict
```

---

## Section 3 — ML DATA / DATABASE LAYER

### 3.2 — `src/dashboard/data_writer.py`

The ML store. Reads the three JSONL files, projects each line into a
unified row, dedupes against the existing monthly Parquet, and writes
new rows only. Also reads back user-filled outcome columns from the
quarterly Excel and merges them into the matching `event_type=alert`
rows.

**Behavioural contract:**

- Public function `sync_jsonl_to_parquet()` returns
  `{"rows_added": int, "months_updated": int, "total_rows_in_parquet": int}`
- Public function `sync_excel_notes_to_parquet()` returns
  `{"alerts_updated": int}` plus a `skipped_reason` if no rows matched.
- Dedup key: `(timestamp_ist, event_type, symbol, strike, option_type)`
- Gap rows are flattened: `per_symbol.NIFTY.open` → column `nifty_open` etc.
- `reasons.C0` … `reasons.C4` are promoted from the nested `reasons`
  dict to top-level columns so pandas filtering doesn't need un-nesting.
- Excel-not-found is silent (returns empty frame). Never crashes the bot.

```python
"""Phase 5.2 — JSONL → Parquet (and Excel → Parquet) sync.

Two public functions:

  sync_jsonl_to_parquet()
      Reads logs/signals.jsonl, logs/alerts.jsonl, logs/gap_log.jsonl,
      and appends only the *new* rows to monthly Parquet files in
      data/scc_data_YYYY-MM.parquet. Idempotent: running twice in a
      row produces 0 new rows on the second run.

  sync_excel_notes_to_parquet()
      Best-effort reader for the user-filled Order Place columns
      (order_status, exit_price, pnl_rupees, user_notes). Writes the
      back-fill into the matching alert rows in the monthly Parquet
      files. Silently skips on any error — Excel-not-found never blocks
      the bot.

Dedup key is ``(timestamp_ist, event_type, symbol, strike, option_type)``.
For event_type == "gap" the per-symbol detail is flattened into
``nifty_*`` / ``banknifty_*`` columns and the row's ``symbol`` is null.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

IST = ZoneInfo("Asia/Kolkata")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
DASHBOARDS_DIR = LOGS_DIR / "dashboards"

SIGNALS_JSONL = LOGS_DIR / "signals.jsonl"
ALERTS_JSONL = LOGS_DIR / "alerts.jsonl"
GAP_JSONL = LOGS_DIR / "gap_log.jsonl"

DEDUP_KEY_COLS = (
    "timestamp_ist",
    "event_type",
    "symbol",
    "strike",
    "option_type",
)


# ---------------------------------------------------------------------------
# JSONL → DataFrame
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping malformed JSON in {path.name} line {lineno}: {e}")
    return rows


def _flatten_reasons(record: dict) -> dict:
    """Promote nested ``reasons.CN`` into top-level ``reasons.C0`` etc."""
    out = dict(record)
    reasons = out.pop("reasons", None)
    if isinstance(reasons, dict):
        for k, v in reasons.items():
            out[f"reasons.{k}"] = v
    return out


def _flatten_gap_record(record: dict) -> dict:
    """Turn a gap JSONL record into a flat row.

    ``per_symbol`` becomes ``nifty_*`` / ``banknifty_*`` columns.
    """
    out: dict[str, Any] = {
        "timestamp_ist": record.get("timestamp_ist"),
        "event_type": "gap",
        "symbol": None,
        "strike": None,
        "option_type": None,
        "decision": record.get("decision"),
        "enabled": record.get("enabled"),
        "threshold_pct": record.get("threshold_pct"),
        "direction": record.get("direction"),
        "any_triggered": record.get("any_triggered"),
    }
    per_sym = record.get("per_symbol") or {}
    for sym, prefix in (("NIFTY", "nifty"), ("BANKNIFTY", "banknifty")):
        info = per_sym.get(sym) or {}
        out[f"{prefix}_open"] = info.get("open")
        out[f"{prefix}_prev_close"] = info.get("prev_close")
        out[f"{prefix}_gap_pct"] = info.get("gap_pct")
        out[f"{prefix}_triggers"] = info.get("triggers")
        out[f"{prefix}_error"] = info.get("error")
    return out


def _records_to_frame(
    signals: Iterable[dict],
    alerts: Iterable[dict],
    gaps: Iterable[dict],
) -> pd.DataFrame:
    rows: list[dict] = []
    for r in signals:
        rows.append(_flatten_reasons(r))
    for r in alerts:
        rows.append(_flatten_reasons(r))
    for r in gaps:
        rows.append(_flatten_gap_record(r))

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if "event_type" not in df.columns:
        df["event_type"] = "scan"
    df["event_type"] = df["event_type"].fillna("scan")
    if "symbol" not in df.columns:
        df["symbol"] = None
    if "strike" not in df.columns:
        df["strike"] = None
    if "option_type" not in df.columns:
        df["option_type"] = None

    df["timestamp_ist"] = df["timestamp_ist"].astype(str)
    df["date"] = df["timestamp_ist"].str.slice(0, 10)
    df["month"] = df["timestamp_ist"].str.slice(0, 7)
    return df


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------


def _dedup_key_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a frame with only the dedup-key columns, normalised to strings.

    Strings are used because Parquet null handling for ints/floats can
    flip None ↔ NaN, which would otherwise break equality compare.
    """
    out = pd.DataFrame()
    for col in DEDUP_KEY_COLS:
        if col not in df.columns:
            out[col] = pd.Series([None] * len(df))
        else:
            out[col] = df[col].astype("object").where(df[col].notna(), None).map(
                lambda v: "" if v is None else str(v)
            )
    return out


def _filter_new_rows(incoming: pd.DataFrame, existing: pd.DataFrame) -> pd.DataFrame:
    if incoming.empty:
        return incoming
    if existing.empty:
        return incoming
    inc_keys = _dedup_key_frame(incoming).astype(str).agg("||".join, axis=1)
    ex_keys = _dedup_key_frame(existing).astype(str).agg("||".join, axis=1)
    mask = ~inc_keys.isin(set(ex_keys))
    return incoming[mask].copy()


# ---------------------------------------------------------------------------
# Parquet I/O
# ---------------------------------------------------------------------------


def _parquet_path(month: str) -> Path:
    return DATA_DIR / f"scc_data_{month}.parquet"


def _read_existing_parquet(month: str) -> pd.DataFrame:
    p = _parquet_path(month)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception as e:
        logger.warning(f"Failed to read {p}: {e} — will rewrite from scratch")
        return pd.DataFrame()


def _write_parquet(month: str, df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = _parquet_path(month)
    df.to_parquet(p, index=False)


# ---------------------------------------------------------------------------
# Public — JSONL → Parquet
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    rows_added: int = 0
    months_updated: int = 0
    total_rows_in_parquet: int = 0


def sync_jsonl_to_parquet() -> dict:
    """Sync every JSONL line into the monthly Parquet files. Idempotent."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signals = _read_jsonl(SIGNALS_JSONL)
    alerts = _read_jsonl(ALERTS_JSONL)
    gaps = _read_jsonl(GAP_JSONL)

    incoming = _records_to_frame(signals, alerts, gaps)
    if incoming.empty:
        return {"rows_added": 0, "months_updated": 0, "total_rows_in_parquet": 0}

    rows_added = 0
    months_updated = 0
    total_rows = 0

    for month, month_df in incoming.groupby("month"):
        existing = _read_existing_parquet(month)
        new_rows = _filter_new_rows(month_df, existing)
        if new_rows.empty and not existing.empty:
            total_rows += len(existing)
            continue
        combined = (
            pd.concat([existing, new_rows], ignore_index=True)
            if not existing.empty
            else new_rows
        )
        combined = combined.sort_values("timestamp_ist").reset_index(drop=True)
        _write_parquet(month, combined)
        rows_added += len(new_rows)
        months_updated += 1
        total_rows += len(combined)

    logger.info(
        f"Parquet sync: +{rows_added} rows across {months_updated} months "
        f"(total {total_rows} rows)"
    )
    return {
        "rows_added": int(rows_added),
        "months_updated": int(months_updated),
        "total_rows_in_parquet": int(total_rows),
    }


# ---------------------------------------------------------------------------
# Public — Excel notes → Parquet (best-effort)
# ---------------------------------------------------------------------------


def _all_parquet_months() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return sorted(DATA_DIR.glob("scc_data_*.parquet"))


def _all_quarterly_dashboards() -> list[Path]:
    if not DASHBOARDS_DIR.exists():
        return []
    return sorted(DASHBOARDS_DIR.glob("dashboard_*.xlsx"))


_OUTCOME_COLUMNS = ("order_status", "exit_price", "pnl_rupees", "user_notes")


def _read_order_place_notes() -> pd.DataFrame:
    """Read user-filled outcome columns from EVERY quarterly Excel."""
    try:
        import openpyxl  # noqa: F401 — absence is harmless
    except Exception as e:
        logger.debug(f"openpyxl unavailable: {e}")
        return pd.DataFrame()

    workbooks = _all_quarterly_dashboards()
    if not workbooks:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for wb_path in workbooks:
        try:
            sheet = pd.read_excel(wb_path, sheet_name="Order Place", engine="openpyxl")
        except Exception as e:
            logger.debug(f"Skipping {wb_path}: {e}")
            continue
        if sheet.empty:
            continue

        rename_map = {
            "Timestamp IST": "timestamp_ist",
            "Symbol": "symbol",
            "Strike": "strike",
            "Option": "option_type",
            "Order Status": "order_status",
            "Exit Price": "exit_price",
            "P&L": "pnl_rupees",
            "User Notes": "user_notes",
        }
        cols_present = [c for c in rename_map if c in sheet.columns]
        sheet = sheet[cols_present].rename(columns=rename_map)

        if not any(c in sheet.columns for c in _OUTCOME_COLUMNS):
            continue
        outcome_cols_in_frame = [c for c in _OUTCOME_COLUMNS if c in sheet.columns]
        mask = sheet[outcome_cols_in_frame].notna().any(axis=1)
        sheet = sheet[mask].copy()
        if sheet.empty:
            continue
        frames.append(sheet)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def sync_excel_notes_to_parquet() -> dict:
    """Best-effort back-fill of outcome columns from Excel into Parquet."""
    try:
        notes = _read_order_place_notes()
    except Exception as e:
        return {"alerts_updated": 0, "skipped_reason": f"read_failed: {e}"}

    if notes.empty:
        return {"alerts_updated": 0, "skipped_reason": "no notes filled yet"}

    months = _all_parquet_months()
    if not months:
        return {"alerts_updated": 0, "skipped_reason": "no parquet files yet"}

    notes["timestamp_ist"] = notes["timestamp_ist"].astype(str)
    if "strike" in notes.columns:
        notes["strike"] = pd.to_numeric(notes["strike"], errors="coerce")
    if "symbol" in notes.columns:
        notes["symbol"] = notes["symbol"].astype(str)
    if "option_type" in notes.columns:
        notes["option_type"] = notes["option_type"].astype(str)

    # Auto-generate outcome_remark wherever order_status is set.
    if "order_status" in notes.columns:
        from src.dashboard.remarks import generate_outcome_remark

        def _row_remark(row: pd.Series) -> str | None:
            status = row.get("order_status")
            if pd.isna(status) or status is None:
                return None
            return generate_outcome_remark(
                alert_data={"bot_remark": ""},
                outcome=str(status),
                exit_price=(
                    float(row["exit_price"])
                    if "exit_price" in row and pd.notna(row["exit_price"])
                    else None
                ),
                pnl=(
                    float(row["pnl_rupees"])
                    if "pnl_rupees" in row and pd.notna(row["pnl_rupees"])
                    else None
                ),
            )

        notes["outcome_remark"] = notes.apply(_row_remark, axis=1)

    alerts_updated = 0
    for parquet_path in months:
        try:
            df = pd.read_parquet(parquet_path)
        except Exception as e:
            logger.debug(f"Skipping {parquet_path}: {e}")
            continue
        if df.empty or "event_type" not in df.columns:
            continue

        merge_cols = [
            c for c in ("timestamp_ist", "symbol", "strike", "option_type")
            if c in df.columns and c in notes.columns
        ]
        if not merge_cols:
            continue

        # Make merge keys robust to dtype mismatch.
        df_keys = df.copy()
        df_keys["timestamp_ist"] = df_keys["timestamp_ist"].astype(str)
        if "strike" in merge_cols:
            df_keys["strike"] = pd.to_numeric(df_keys["strike"], errors="coerce")
        if "symbol" in merge_cols:
            df_keys["symbol"] = df_keys["symbol"].astype("object").map(
                lambda v: "" if v is None else str(v)
            )
        if "option_type" in merge_cols:
            df_keys["option_type"] = df_keys["option_type"].astype("object").map(
                lambda v: "" if v is None else str(v)
            )

        notes_keys = notes.copy()
        notes_keys["timestamp_ist"] = notes_keys["timestamp_ist"].astype(str)
        if "strike" in merge_cols:
            notes_keys["strike"] = pd.to_numeric(notes_keys["strike"], errors="coerce")
        if "symbol" in merge_cols:
            notes_keys["symbol"] = notes_keys["symbol"].astype("object").map(
                lambda v: "" if v is None else str(v)
            )
        if "option_type" in merge_cols:
            notes_keys["option_type"] = notes_keys["option_type"].astype("object").map(
                lambda v: "" if v is None else str(v)
            )

        outcome_cols = [
            c for c in (*_OUTCOME_COLUMNS, "outcome_remark")
            if c in notes_keys.columns
        ]
        if not outcome_cols:
            continue

        merged = df_keys.merge(
            notes_keys[merge_cols + outcome_cols],
            on=merge_cols,
            how="left",
            suffixes=("", "_excel"),
        )

        updated_count = 0
        for col in outcome_cols:
            excel_col = f"{col}_excel"
            if excel_col not in merged.columns:
                excel_col = col
            if excel_col not in merged.columns:
                continue
            mask = (merged["event_type"] == "alert") & merged[excel_col].notna()
            if not mask.any():
                continue
            if col not in df.columns:
                df[col] = None
            df.loc[mask, col] = merged.loc[mask, excel_col].values
            updated_count += int(mask.sum())

        if updated_count > 0:
            _write_parquet(parquet_path.stem.replace("scc_data_", ""), df)
            alerts_updated += updated_count

    if alerts_updated == 0:
        return {"alerts_updated": 0, "skipped_reason": "no matching alerts"}
    return {"alerts_updated": int(alerts_updated)}


# ---------------------------------------------------------------------------
# Helpers used by excel_builder
# ---------------------------------------------------------------------------


def load_parquet_for_quarter(year: int, quarter: int) -> pd.DataFrame:
    """Concat the 3 months of a calendar quarter into one DataFrame."""
    start_month = (quarter - 1) * 3 + 1
    months = [f"{year:04d}-{start_month + i:02d}" for i in range(3)]
    frames = []
    for m in months:
        p = _parquet_path(m)
        if p.exists():
            try:
                frames.append(pd.read_parquet(p))
            except Exception as e:
                logger.warning(f"Skipping {p}: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def quarter_for_date(d: datetime | None = None) -> tuple[int, int]:
    """Return (year, quarter) for the IST today (or for ``d``)."""
    if d is None:
        d = datetime.now(IST)
    return d.year, (d.month - 1) // 3 + 1
```

### 3.3 — `data/schema.md` (committed)

This document is checked into git — it's the long-lived spec future-you
reads in 2027 to understand the Parquet columns. Reproduced in full:

````markdown
# SCC Unified Parquet Schema — Phase 5.2

This document describes the columns in `data/scc_data_YYYY-MM.parquet`.
The files are the canonical ML / backtest store. They are regenerable
at any time from `logs/signals.jsonl`, `logs/alerts.jsonl`, and
`logs/gap_log.jsonl` via `scripts/update_dashboard.py`.

The quarterly Excel files in `logs/dashboards/` are a *human-facing*
projection of these Parquet files. They are not the source of truth.
The only Excel-only columns that flow *back* to Parquet are the
user-filled outcome columns in the Order Place sheet.

---

## File naming

```
data/scc_data_YYYY-MM.parquet
```

One file per calendar month, ordered by `timestamp_ist`. Files are
pyarrow-compatible; load with `pd.read_parquet`.

Reading a quarter:

```python
import pandas as pd, glob
df = pd.concat([pd.read_parquet(f) for f in glob.glob("data/scc_data_2026-0[4-6].parquet")])
```

---

## event_type values

Every row carries an `event_type`. Other columns are populated
*conditional* on event_type.

| event_type              | When the bot writes it                                        |
|-------------------------|---------------------------------------------------------------|
| `scan`                  | One per closed 5-min candle per strike per scan loop. Full indicator snapshot + condition reasons. Default event_type when none is set in JSONL. |
| `alert`                 | One per 5/5-pass scan. Includes SL/TP/lot math AND `bot_remark` / `bot_tags`. |
| `rejection`             | One per silent rejection (typically a C0 fast-fail on spot/VWAP disagreement, or a re-entry blocker). |
| `data_issue`            | Mid-session start where `get_latest_snapshot()` raised `Insufficient lookback`. Distinguished from rejections so analytics stay clean. |
| `would_alert_extended`  | Phase 5.2: a 4/5 scan where the only failing condition is C1 and the option is between `c1_max_distance_pct` (30) and `c1_extended_zone_max_pct` (50) above VWAP. |
| `gap`                   | One per bot startup. Sourced from `gap_log.jsonl`. Holds the directional gap decision, per-symbol gap %, and the toggle state. |

---

## Common columns (every row)

| Column          | Type   | Notes                                                            |
|-----------------|--------|------------------------------------------------------------------|
| `timestamp_ist` | str    | ISO 8601 with `+05:30` offset. Always IST. Primary sort key.    |
| `event_type`    | str    | One of the values above.                                         |
| `date`          | str    | `YYYY-MM-DD` derived from timestamp_ist.                         |
| `month`         | str    | `YYYY-MM`. Used by the writer to pick the target Parquet file.   |
| `symbol`        | str    | `NIFTY` / `BANKNIFTY` / null for gap rows that span both.        |
| `_logged_at`    | str    | Bot's wall-clock when it wrote the JSONL line.                   |

---

## Indicator columns (event_type ∈ {scan, alert, would_alert_extended})

| Column             | Type   | Notes                                                |
|--------------------|--------|------------------------------------------------------|
| `strike`           | int    | The option strike scanned.                           |
| `relation`         | str    | `ITM` / `ATM` / `OTM`.                               |
| `option_type`      | str    | `CE` / `PE`.                                         |
| `expiry`           | str    | `YYYY-MM-DD` of contract expiry.                     |
| `trading_symbol`   | str    | Human-readable (e.g. `NIFTY26JUN24050CE`).           |
| `spot_price`       | float  | Latest spot index close at scan time.                |
| `spot_vwap`        | float  | Spot session VWAP.                                   |
| `option_close`     | float  | Option's latest 5-min close.                         |
| `option_vwap`      | float  | Option's session VWAP (hlc3-based).                  |
| `rsi`              | float  | Option RSI(14) Wilder.                               |
| `rsi_ma`           | float  | Option RSI MA(20) simple.                            |
| `oi`               | float  | Option current OI.                                   |
| `oi_ma`            | float  | Option OI MA(20) simple.                             |
| `volume`           | float  | Option current candle volume.                        |
| `volume_ma`        | float  | Option volume MA(20) simple.                         |
| `is_green`         | bool   | Whether the current candle is bullish.               |
| `vix`              | float  | Session India VIX (locked at bot start).             |
| `vix_regime`       | str    | `Low Vol` / `Normal` / `Elevated` / `High Vol`.      |
| `opt_above_vwap_pct` | float | Phase 5.2: `(option_close - option_vwap) / option_vwap * 100`. Signed. |

---

## Condition columns (event_type ∈ {scan, alert, would_alert_extended})

| Column                | Type      | Notes                                              |
|-----------------------|-----------|----------------------------------------------------|
| `conditions_passed`   | list[str] | E.g. `["C0", "C2", "C3", "C4"]`.                   |
| `conditions_failed`   | list[str] | E.g. `["C1"]` for would_alert_extended.            |
| `all_passed`          | bool      | True only when 5/5 passed.                         |
| `summary`             | str       | `C0 ✓ C1 ✓ C2 ✗ C3 ✓ C4 ✓`-style one-liner.        |
| `reasons.C0` … `C4`   | str       | Per-condition reason text (flattened from nested). |

The flattened `reasons.CN` columns let you query `df["reasons.C1"]`
directly without un-nesting.

---

## Alert-only columns (event_type == "alert")

| Column           | Type   | Notes                                                  |
|------------------|--------|--------------------------------------------------------|
| `entry`          | float  | Limit entry = option_close at the alert candle.        |
| `sl`             | float  | Computed SL price.                                     |
| `sl_method`      | int    | 1 (point buffer) or 2 (percentage).                    |
| `tp1`            | float  | First take-profit price.                               |
| `tp2`            | float  | Final take-profit price.                               |
| `tp1_r`          | float  | TP1 multiple of R (1.5 normal / 2.0 expiry).           |
| `tp2_r`          | float  | TP2 multiple of R (2.5 normal / 3.0 expiry).           |
| `risk_per_unit`  | float  | `entry - sl`.                                          |
| `lots`           | int    | Computed lots to reach target_risk_per_trade.          |
| `total_risk`     | float  | `lots * lot_size * risk_per_unit`.                     |
| `lot_size`       | int    | Broker-verified lot size.                              |
| `day_type`       | str    | `Normal` / `Expiry`.                                   |
| `vix_multiplier` | float  | The SL multiplier the regime imposed.                  |
| `spot_position`  | str    | `Above VWAP ✓` (CE) or `Below VWAP ✓` (PE).            |
| `time`           | str    | `HH:MM` IST.                                           |

### Bot remark columns (alert only)

| Column                   | Type | Notes                                              |
|--------------------------|------|----------------------------------------------------|
| `bot_remark`             | str  | Human-readable: "5/5 strong — opt 8% above VWAP, RSI 67 healthy zone, OI 18% below MA, vol 2.1× MA, first alert of day." |
| `bot_tags`               | str  | Comma-separated ML tags, no spaces. |
| `telegram_short_remark`  | str  | Trimmed for the Telegram alert "Insight:" line. |

### Outcome columns (alert only — populated by user via Excel)

These columns are back-filled by `sync_excel_notes_to_parquet`.

| Column            | Type   | Notes                                                |
|-------------------|--------|------------------------------------------------------|
| `order_status`    | str    | `TP2_HIT` / `TP1_HIT` / `SL_HIT` / `PARTIAL` / `WOULD_SKIP` / null. |
| `exit_price`      | float  | Filled manually in Order Place sheet.                |
| `pnl_rupees`      | float  | Sign convention: positive = profit.                  |
| `outcome_remark`  | str    | Auto-generated from `bot_remark` + `order_status`.   |
| `user_notes`      | str    | Free-form user observation.                          |

---

## Rejection-only columns (event_type == "rejection")

| Column                | Type | Notes                                                  |
|-----------------------|------|--------------------------------------------------------|
| `strike`              | int  | May be null when rejection happened before strike resolution. |
| `option_type`         | str  | `CE` / `PE`.                                           |
| `rejection_blocker`   | str  | Which condition / guardrail failed (e.g. `C0`, `RE_ENTRY_BLOCKED`). |
| `rejection_reason`    | str  | One-line human explanation.                            |

---

## Gap-only columns (event_type == "gap")

One row per bot startup.

| Column                    | Type   | Notes                                              |
|---------------------------|--------|----------------------------------------------------|
| `decision`                | str    | `NORMAL`, `GAP_UP`, `GAP_DOWN`, `GAP_UP_DISABLED`, `GAP_DOWN_DISABLED`. Legacy: `GAP_DAY`, `GAP_DETECTED_BUT_DISABLED`. |
| `enabled`                 | bool   | Gap-day rule toggle at the time of detection.       |
| `threshold_pct`           | float  | The threshold % in force.                           |
| `direction`               | str    | `both` / `up` / `down`.                             |
| `any_triggered`           | bool   | At least one symbol breached threshold.             |
| `nifty_open`              | float  | Today's 09:15 open for NIFTY.                       |
| `nifty_prev_close`        | float  | Previous trading-day close for NIFTY.               |
| `nifty_gap_pct`           | float  | Signed gap percentage for NIFTY.                    |
| `nifty_triggers`          | bool   | NIFTY breached threshold this morning.              |
| `nifty_error`             | str    | Diagnostic if gap math could not be computed.       |
| (same six for `banknifty_*`) |     |                                                    |

---

## data_issue-only columns (event_type == "data_issue")

| Column           | Type | Notes                                                  |
|------------------|------|--------------------------------------------------------|
| `strike`         | int  | The strike that was being scanned.                     |
| `option_type`    | str  | `CE` / `PE`.                                           |
| `issue_type`     | str  | Typically `INSUFFICIENT_LOOKBACK`.                     |
| `issue_message`  | str  | Indicator-calc error text (e.g. "need 33 candles").    |

---

## Forward-compatibility notes

- **Adding a column:** future bot versions append columns. The writer's
  `pd.concat` preserves new columns as nulls in old rows. Don't rename
  existing columns; deprecate and add new ones.
- **Adding a new event_type:** the writer accepts any string. Update
  this doc and the Excel builder if the new type warrants its own
  sheet or chart bucket.
- **Removing a column:** never delete. Backfill with null in old files.

---

## Example pandas queries

### What did the bot remark on the first NIFTY alert each day?

```python
df = pd.read_parquet("data/scc_data_2026-05.parquet")
alerts = df[df["event_type"] == "alert"]
first_per_day = alerts.groupby("date").first()
print(first_per_day[["symbol", "strike", "option_type", "bot_remark"]])
```

### How often did "strong" entries hit TP2?

```python
df = df[df["event_type"] == "alert"].copy()
df["is_strong"] = df["bot_remark"].fillna("").str.contains("strong", case=False)
counts = df.groupby(["is_strong", "order_status"]).size().unstack(fill_value=0)
print(counts)
```

### Cumulative P&L curve

```python
df = df[df["event_type"] == "alert"].sort_values("timestamp_ist")
df = df[df["pnl_rupees"].notna()]
df["cum_pnl"] = df["pnl_rupees"].cumsum()
df.set_index("timestamp_ist")["cum_pnl"].plot()
```

### Alerts grouped by C1 distance zone

```python
alerts = df[df["event_type"].isin(["alert", "would_alert_extended"])].copy()
alerts["c1_zone"] = pd.cut(
    alerts["opt_above_vwap_pct"],
    bins=[-100, 10, 20, 25, 30, 50, 100],
    labels=["fresh", "clean", "mid", "late_kept", "extended", "outside"],
)
print(alerts.groupby(["event_type", "c1_zone"]).size())
```

### Distribution of bot_tags across alerts

```python
from collections import Counter
tags = df[df["event_type"] == "alert"]["bot_tags"].dropna()
counter = Counter(t for row in tags for t in row.split(","))
print(counter.most_common(20))
```
````

---

## Section 4 — EXCEL DASHBOARD LAYER

### 3.4 — `src/dashboard/excel_builder.py`

Reads the monthly Parquet files (via `load_parquet_for_quarter`) and
emits a quarterly workbook at
`logs/dashboards/dashboard_YYYY_QN.xlsx`. Eight sheets in this order:

1. **Strategy Dashboard** — KPI tiles + 4 charts
2. **Daily Summary** — one row per trading day with directional gap label
3. **All Alerts** — full alert list with `opt_above_vwap_pct`, `bot_remark`, `bot_tags`
4. **Order Place** — auto cols + manual cols, outcome cell coloring
5. **All Signals** — `scan` / `alert` / `would_alert_extended` (last
   highlighted light orange)
6. **Rejections** — grouped by blocker
7. **Gap History** — directional labels with color swatches
8. **Config Snapshot** — current config values

Idempotent: re-running rebuilds from scratch using latest Parquet. The
function `_resolve_excel_path(year, quarter)` returns
`logs/dashboards/dashboard_YYYY_QN.xlsx`. Quarters: Q1=Jan–Mar,
Q2=Apr–Jun, Q3=Jul–Sep, Q4=Oct–Dec.

**Style palette** (hex):

| Element                  | Hex      | Notes                       |
|--------------------------|----------|-----------------------------|
| Header background        | `1F4E78` | Deep navy, white bold font  |
| `TP2_HIT` fill           | `6FBF73` | Strong green                |
| `TP1_HIT` fill           | `C8E6C9` | Light green                 |
| `SL_HIT` fill            | `EF9A9A` | Red                         |
| `WOULD_SKIP` fill        | `E0E0E0` | Grey                        |
| `PARTIAL` fill           | `FFE082` | Yellow                      |
| `GAP_UP` cell            | `FFCDD2` | Light red                   |
| `GAP_DOWN` cell          | `BBDEFB` | Light blue                  |
| `GAP_UP_DISABLED` cell   | `FFE0B2` | Orange                      |
| `would_alert_extended` row | `FFE0B2` | Light orange              |
| `all_passed` row         | `FFF59D` | Yellow                      |
| KPI tile palette         | rotating: navy / green / orange / purple / teal / red |

**Full source:**

```python
"""Phase 5.2 — Quarterly Excel dashboard builder.

Reads the unified monthly Parquet files in ``data/`` and produces a
human-facing workbook at ``logs/dashboards/dashboard_YYYY_QN.xlsx``.

Idempotent: re-running ``update_dashboard`` rebuilds the workbook from
scratch using the latest Parquet state.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.dashboard.data_writer import (
    DASHBOARDS_DIR,
    load_parquet_for_quarter,
    quarter_for_date,
)

IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Style palette
# ---------------------------------------------------------------------------

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_TITLE_FONT = Font(name="Calibri", bold=True, color="1F4E78", size=16)
_SUBTITLE_FONT = Font(name="Calibri", italic=True, color="595959", size=10)
_BODY_FONT = Font(name="Calibri", size=11)
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(top=_THIN, bottom=_THIN, left=_THIN, right=_THIN)

OUTCOME_FILLS = {
    "TP2_HIT": PatternFill("solid", fgColor="6FBF73"),
    "TP1_HIT": PatternFill("solid", fgColor="C8E6C9"),
    "SL_HIT": PatternFill("solid", fgColor="EF9A9A"),
    "WOULD_SKIP": PatternFill("solid", fgColor="E0E0E0"),
    "PARTIAL": PatternFill("solid", fgColor="FFE082"),
}

GAP_FILLS = {
    "GAP_UP": PatternFill("solid", fgColor="FFCDD2"),
    "GAP_DOWN": PatternFill("solid", fgColor="BBDEFB"),
    "GAP_UP_DISABLED": PatternFill("solid", fgColor="FFE0B2"),
    "GAP_DOWN_DISABLED": PatternFill("solid", fgColor="BBDEFB"),
    "GAP_DAY": PatternFill("solid", fgColor="FFCDD2"),                  # legacy
    "GAP_DETECTED_BUT_DISABLED": PatternFill("solid", fgColor="FFE0B2"),# legacy
}

RELATION_FILLS = {
    "ITM": PatternFill("solid", fgColor="F4F4F4"),
    "ATM": PatternFill("solid", fgColor="FFF9C4"),
    "OTM": PatternFill("solid", fgColor="EDE7F6"),
}

EXTENDED_FILL = PatternFill("solid", fgColor="FFE0B2")
ALL_PASSED_FILL = PatternFill("solid", fgColor="FFF59D")

KPI_FILLS = [
    PatternFill("solid", fgColor="1F4E78"),
    PatternFill("solid", fgColor="2E7D32"),
    PatternFill("solid", fgColor="EF6C00"),
    PatternFill("solid", fgColor="6A1B9A"),
    PatternFill("solid", fgColor="00838F"),
    PatternFill("solid", fgColor="C62828"),
]


def _resolve_excel_path(year: int, quarter: int) -> Path:
    return DASHBOARDS_DIR / f"dashboard_{year:04d}_Q{quarter}.xlsx"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_headers(ws: Worksheet, headers: Iterable[str], row: int = 1) -> None:
    for col_idx, header in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col_idx, value=header)
        c.font = _HEADER_FONT
        c.fill = _HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 26


def _autofit(ws: Worksheet, df: pd.DataFrame, header_row: int = 1) -> None:
    for col_idx, col in enumerate(df.columns, start=1):
        max_len = max([len(str(col))] + [len(str(v)) for v in df[col].head(200).tolist()])
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(12, max_len + 2), 48)


def _write_dataframe(ws: Worksheet, df: pd.DataFrame, header_row: int = 1) -> int:
    if df.empty:
        ws.cell(row=header_row, column=1, value="(no data yet)").font = _SUBTITLE_FONT
        return 0
    _set_headers(ws, [_pretty(c) for c in df.columns], row=header_row)
    sr = header_row + 1
    for row_offset, (_, row) in enumerate(df.iterrows()):
        for col_idx, col in enumerate(df.columns, start=1):
            value = row[col]
            if pd.isna(value):
                value = None
            ws.cell(row=sr + row_offset, column=col_idx, value=value).font = _BODY_FONT
    _autofit(ws, df, header_row=header_row)
    return len(df)


def _pretty(col: str) -> str:
    mapping = {
        "opt_above_vwap_pct": "Opt Above VWAP %",
        "bot_remark": "Bot Remark",
        "bot_tags": "Bot Tags",
        "outcome_remark": "Outcome Remark",
        "user_notes": "User Notes",
        "order_status": "Order Status",
        "exit_price": "Exit Price",
        "pnl_rupees": "P&L",
        "timestamp_ist": "Timestamp IST",
    }
    if col in mapping:
        return mapping[col]
    return col.replace("_", " ").title()


def _outcome_fill_for(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return OUTCOME_FILLS.get(str(value).strip().upper())


def _gap_fill_for(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return GAP_FILLS.get(str(value).strip().upper())
```

(The full `excel_builder.py` continues with the eight sheet builders.
Each builder reads its slice of `df` by `event_type` and produces the
sheet described above. The builders preserve the exact column lists
from `data/schema.md`. For the complete in-tree implementation see the
existing source — its behaviour is fully specified by the data schema
and the style palette table above, so a rebuild from scratch follows
mechanically.)

**Sheet-by-sheet specification:**

| Sheet | Source rows | Columns shown | Cell coloring | Freeze pane |
|---|---|---|---|---|
| Strategy Dashboard | All event_types | 12 KPI tiles + 4 charts | KPI tile palette | n/a |
| Daily Summary | All event_types, grouped by `date` | date, gap_decision, nifty_gap_pct, banknifty_gap_pct, scans, alerts, extended, rejections, nifty_alerts, banknifty_alerts | gap_decision cell colored by GAP_FILLS | A2 |
| All Alerts | `event_type=="alert"` | timestamp_ist, date, time, symbol, strike, relation, option_type, expiry, spot_price, entry, sl, tp1, tp2, lots, total_risk, vix, vix_regime, day_type, opt_above_vwap_pct, rsi, rsi_ma, oi, oi_ma, volume, volume_ma, bot_remark, bot_tags | bot_remark/bot_tags columns wrap text, width 60 | A2 |
| Order Place | `event_type=="alert"` | Auto: timestamp_ist, date, time, symbol, strike, relation, option_type, entry, sl, tp1, tp2, lots, total_risk, bot_remark. Manual: order_status, exit_price, pnl_rupees, outcome_remark, user_notes | order_status colored by OUTCOME_FILLS, pnl_rupees green/red by sign | A2 |
| All Signals | `event_type in {scan, alert, would_alert_extended}` | timestamp_ist, date, time, event_type, symbol, strike, relation, option_type, spot_price, spot_vwap, option_close, option_vwap, opt_above_vwap_pct, rsi, rsi_ma, oi, oi_ma, volume, volume_ma, is_green, all_passed, summary | would_alert_extended rows EXTENDED_FILL; all_passed rows ALL_PASSED_FILL; others by RELATION_FILLS | A2 |
| Rejections | `event_type=="rejection"` | timestamp_ist, date, symbol, strike, option_type, rejection_blocker, rejection_reason | — | A2 |
| Gap History | `event_type=="gap"` | timestamp_ist, date, decision, enabled, threshold_pct, direction, any_triggered, nifty_open, nifty_prev_close, nifty_gap_pct, banknifty_open, banknifty_prev_close, banknifty_gap_pct | decision cell colored by GAP_FILLS | A2 |
| Config Snapshot | live `load_config()` | Setting, Value | — | n/a |

**The four Strategy Dashboard charts:**

1. **Wins vs Losses by Strike Relation** — `BarChart` col, style 11.
   Buckets: ITM Win, ITM Loss, ATM Win, ATM Loss, OTM Win, OTM Loss.
   Wins = TP2_HIT + TP1_HIT, Losses = SL_HIT.
2. **Alerts by VIX Regime** — `BarChart` bar, style 12.
   Buckets: alert counts grouped by `vix_regime`.
3. **Alerts by Time of Day (30-min buckets)** — `BarChart` col, style 13.
   `time` → `f"{hh:02d}:{(mm//30)*30:02d}"`.
4. **Cumulative P&L** — `LineChart` style 12.
   Sort alerts by timestamp, take running sum of `pnl_rupees`, x-axis = date.

Charts are anchored at `A{chart_start_row}` and `E{chart_start_row}`
(top row), then `A{chart_start_row+16}` and `E{chart_start_row+16}`
(bottom row). Aggregation tables are written off-screen at column
anchors 10, 13, 16, 19 so `Reference()` can point at them.

The complete `_build_workbook` entry point creates an empty `Workbook`,
renames the first sheet to "Strategy Dashboard", builds it, then
creates and builds each subsequent sheet in the order above, then
calls `wb.save(_resolve_excel_path(year, quarter))`.

**Public entry point** `update_dashboard()` returns
`{"status": "ok"|"no_data", "output_path": str|None, "alerts_added": int, "signals_added": int, "order_place_added": int, "rejections_added": int, "gaps_added": int, "quarters_touched": int}`.
It walks every (year, quarter) present in the Parquet data (always
including the current quarter so the file exists even on day 1) and
rebuilds each workbook in place.

### 3.5 — `src/dashboard/__init__.py`

```python
from src.dashboard.data_writer import (
    sync_jsonl_to_parquet,
    sync_excel_notes_to_parquet,
)
from src.dashboard.excel_builder import update_dashboard
from src.dashboard.remarks import (
    generate_remark_and_tags,
    generate_outcome_remark,
    telegram_short_remark,
)

__all__ = [
    "sync_jsonl_to_parquet",
    "sync_excel_notes_to_parquet",
    "update_dashboard",
    "generate_remark_and_tags",
    "generate_outcome_remark",
    "telegram_short_remark",
]
```

### 3.6 — `scripts/update_dashboard.py` + `update_dashboard.bat`

Manual entry point. Same sequence as the `finally`-block auto-run:
JSONL → Parquet, then Excel rebuild, then Excel-notes → Parquet
back-sync.

```python
#!/usr/bin/env python
"""Manual sync: refresh Parquet + Excel dashboards from JSONL."""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config_loader import load_secrets
from src.dashboard import (
    sync_jsonl_to_parquet,
    sync_excel_notes_to_parquet,
    update_dashboard,
)

IST = ZoneInfo("Asia/Kolkata")


def main() -> None:
    print("=" * 60)
    print("  SCC Dashboard + Parquet Update")
    print(f"  Time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    load_secrets()

    print("\n[1/3] JSONL → Parquet sync (monthly files)...")
    pq = sync_jsonl_to_parquet()
    print(f"  Rows added: {pq.get('rows_added', 0)}")
    print(f"  Months touched: {pq.get('months_updated', 0)}")

    print("\n[2/3] Updating dashboard.xlsx (quarterly file)...")
    xl = update_dashboard()
    if xl.get("status") == "no_data":
        print("  No data yet — skipped.")
    else:
        print(f"  File: {xl.get('output_path')}")
        print(f"  Alerts added: {xl.get('alerts_added', 0)}")
        print(f"  Signals added: {xl.get('signals_added', 0)}")
        print(f"  Order Place added: {xl.get('order_place_added', 0)}")
        print(f"  Rejections added: {xl.get('rejections_added', 0)}")
        print(f"  Gap rows added: {xl.get('gaps_added', 0)}")

    print("\n[3/3] Excel notes → Parquet sync (best-effort)...")
    notes = sync_excel_notes_to_parquet()
    if notes.get("alerts_updated", 0) > 0:
        print(f"  Outcome columns updated for {notes['alerts_updated']} alerts")
    else:
        print(f"  Skipped: {notes.get('skipped_reason', 'no notes filled yet')}")

    print("\n✓ Done.")
    print("  Human review: logs/dashboards/")
    print("  ML/backtest:  data/")


if __name__ == "__main__":
    main()
```

`update_dashboard.bat`:

```bat
@echo off
call venv\Scripts\activate.bat
echo Updating dashboard + Parquet...
python scripts\update_dashboard.py
echo.
pause
```

---

## STEP 4 — Orchestrator wiring

These are the small deltas inside `src/main.py`. Each one is already
present in the §2.4 source of PHASE_5A as an inert hook with a
`# Phase 5.2:` comment; activating the dashboard module simply makes
each of those hooks live.

### 4.1 — `bot_remark` + `bot_tags` in `_fire_alert`

After building `alert_data` but before `signal_logger.log_alert(...)`:

```python
try:
    context = {
        "time_hhmm": now.strftime("%H:%M"),
        "vix_regime": self.session_vix_info.regime.value,
        "is_expiry_day": is_expiry,
        "daily_sl_count": self.state.get_daily_sl_count(),
        "daily_alert_count": self.session_alert_count,
    }
    snapshot_dict = {
        "option_close": snapshot.close,
        "option_vwap": snapshot.vwap,
        "rsi": snapshot.rsi,
        "rsi_ma": snapshot.rsi_ma,
        "oi": snapshot.oi,
        "oi_ma": snapshot.oi_ma,
        "volume": snapshot.volume,
        "volume_ma": snapshot.volume_ma,
        "opt_above_vwap_pct": signal_record.get("opt_above_vwap_pct", 0.0),
    }
    bot_remark, bot_tags = generate_remark_and_tags(snapshot_dict, context)
    alert_data["bot_remark"] = bot_remark
    alert_data["bot_tags"] = bot_tags
    alert_data["telegram_short_remark"] = telegram_short_remark(bot_remark)
except Exception as e:
    logger.warning(f"Bot remark generation failed: {e}")
    alert_data.setdefault("bot_remark", "")
    alert_data.setdefault("bot_tags", "")
    alert_data.setdefault("telegram_short_remark", "")
```

### 4.2 — "Insight:" line in `TelegramAlerter._format_signal`

In `src/alerts/telegram_bot.py`, change `_format_signal` to read the
short remark from the dict and inject a line between the "Total Risk"
line and the "C0 ✓ ..." line:

```python
insight = (s.get("telegram_short_remark") or "").strip()
insight_line = f"\nInsight: {insight}\n" if insight else "\n"
return (
    "🚨 SHORT COVER CASCADE SIGNAL\n"
    "─────────────────────────────\n"
    ...
    f"Lots: {s['lots']} → Total Risk: ₹{s['total_risk']:,.2f}\n"
    f"({s['lots']} × {s['lot_size']} × ₹{s['risk_per_unit']:.2f})\n"
    f"{insight_line}"
    "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓\n"
    ...
)
```

When `telegram_short_remark` is missing/blank, the rendering is identical
to Phase 5A.

### 4.3 — `_maybe_log_extended_zone` in `_scan_strike`

Already present in PHASE_5A as an inert method (it checks for the
Phase 5B config keys via try/except AttributeError and bails out
silently in 5A). Once the `conditions` section exists in config.yaml
(§2.2 above), the method becomes live. No code change required.

Reproduced here for clarity:

```python
def _maybe_log_extended_zone(self, signal_record: dict, result) -> None:
    """Capture 4/5 scans where C1's late-entry filter is the only blocker
    AND the option sits in the extended zone window.
    """
    cfg = self.config
    try:
        log_enabled = cfg.logging.log_extended_zone
        zone_enabled = cfg.conditions.c1_extended_zone_enabled
        max_pct = cfg.conditions.c1_max_distance_pct
        ext_max = cfg.conditions.c1_extended_zone_max_pct
    except AttributeError:
        return

    if not (log_enabled and zone_enabled):
        return
    if result.all_passed:
        return
    if result.failed_conditions() != ["C1"]:
        return

    pct = float(signal_record.get("opt_above_vwap_pct") or 0.0)
    if not (max_pct < pct <= ext_max):
        return

    extended = dict(signal_record)
    extended["event_type"] = "would_alert_extended"
    self.signal_logger.log_signal(extended)
```

And the call site, inside `_scan_strike` after `log_signal(signal_record)`:

```python
self._maybe_log_extended_zone(signal_record, result)
```

### 4.4 — Dashboard sync in `finally` block (Phase 5.2.1)

The dashboard auto-sync runs from `run_forever()`'s `finally` clause —
it fires exactly once per session whether the bot exited cleanly at
15:30, was Ctrl+C-stopped, or died with an unhandled exception. This
is the **final form**; an earlier 5.2 draft tried to schedule the sync
at 15:35 inside the polling loop, but `run_forever()` exits at 15:30
and the in-loop check never fired. Do not reproduce that path.

Method on `Orchestrator`:

```python
def _run_dashboard_sync_on_exit(self) -> None:
    """Run dashboard sync on bot exit. Best-effort, idempotent.

    Honours:
      - config.dashboard.auto_trigger_at_1535 (toggle, default ON)
      - self.dashboard_synced (prevents double-run in same process)
      - weekday check (skip on Saturday/Sunday)

    Failures are logged + Telegrammed but never re-raised — the bot
    must exit cleanly even if sync fails.
    """
    try:
        auto_trigger = self.config.dashboard.auto_trigger_at_1535
    except AttributeError:
        return
    if not auto_trigger or self.dashboard_synced or datetime.now(IST).weekday() >= 5:
        return
    try:
        logger.info("Bot exiting — running dashboard auto-sync...")
        from src.dashboard import (
            sync_excel_notes_to_parquet,
            sync_jsonl_to_parquet,
            update_dashboard,
        )
        sync_jsonl_to_parquet()
        update_dashboard()
        sync_excel_notes_to_parquet()
        self.dashboard_synced = True
        logger.info("Dashboard auto-sync complete on bot exit")
    except Exception as e:
        logger.exception(f"Dashboard auto-sync on exit failed: {e}")
        try:
            self.telegram.send_exception(
                f"Dashboard auto-sync failed on exit:\n{e}"
            )
        except Exception:
            pass
```

End of `run_forever()`:

```python
try:
    while True:
        ...
except KeyboardInterrupt:
    logger.info("Bot stopped by user (Ctrl+C)")
except Exception as e:
    logger.exception("FATAL error in main loop")
    try:
        if self.telegram is not None:
            self.telegram.send_exception(traceback.format_exc())
    except Exception:
        pass
    sys.exit(1)
finally:
    # Phase 5.2.1: Auto-sync dashboard on exit. Runs exactly once.
    self._run_dashboard_sync_on_exit()
```

And the market-close log line in the main while loop reads:

```python
if now.time() >= MARKET_CLOSE_TIME:
    logger.info(
        "Market closed (15:30 IST). Bot exiting, dashboard sync will run."
    )
    break
```

---

## STEP 5 — `.gitignore`

Add (preserve existing):

```
# Dashboard outputs (regenerable from JSONL)
logs/dashboards/
data/scc_data_*.parquet

# But keep schema documentation
!data/schema.md
```

---

## STEP 6 — Unit tests

Target: ~210 (Phase 5A) + ~65 (Phase 5B) = **~275 tests passing**.

### `tests/test_dashboard_remarks.py` (~15 tests)

```
test_fresh_breakout_tag_under_10pct
test_late_entry_tag_above_22pct
test_strong_rsi_tag_60_to_74
test_strong_oi_tag_above_15pct_below_ma
test_explosive_volume_tag_above_2x
test_verdict_strong_when_all_signals_firm
test_verdict_borderline_when_any_marginal
test_remark_length_under_30_words
test_remark_contains_verdict_prefix
test_tags_comma_separated_no_spaces
test_telegram_short_remark_under_80_chars
test_outcome_remark_tp2_for_strong_setup
test_outcome_remark_sl_for_marginal_setup
test_first_alert_tag_when_count_zero
test_after_sl_tag_when_sl_count_positive
```

### `tests/test_dashboard_data_writer.py` (~15 tests)

```
test_sync_handles_empty_jsonl_returns_zero
test_sync_writes_one_row_per_jsonl_line
test_sync_dedups_on_rerun
test_sync_splits_rows_by_month
test_sync_flattens_reasons_into_top_level_columns
test_sync_flattens_gap_records_into_nifty_banknifty_columns
test_excel_notes_silent_when_no_workbook
test_excel_notes_back_fills_order_status_to_alert_rows
test_excel_notes_preserved_across_sync_runs
test_excel_notes_handles_missing_openpyxl
test_load_parquet_for_quarter_concatenates_three_months
test_load_parquet_skips_missing_months
test_quarter_for_date_q1_q2_q3_q4
test_dedup_key_string_normalised_handles_nones
test_writer_handles_data_issue_event_type
```

### `tests/test_dashboard_excel_builder.py` (~15 tests)

```
test_resolve_excel_path_quarter_format
test_workbook_has_all_eight_sheets_in_order
test_strategy_dashboard_first_sheet
test_strategy_dashboard_charts_present
test_order_place_outcome_coloring_tp2_green
test_order_place_outcome_coloring_sl_red
test_order_place_pnl_colored_by_sign
test_all_alerts_includes_bot_remark_wrap_text
test_all_signals_highlights_would_alert_extended_orange
test_all_signals_highlights_all_passed_yellow
test_daily_summary_colors_directional_gap_decision
test_gap_history_colors_gap_up_light_red
test_idempotent_run_twice_same_workbook
test_no_data_writes_current_quarter_skeleton
test_config_snapshot_lists_all_phase52_keys
```

### `tests/test_c1_extended_zone.py` (~8 tests)

```
test_c1_passes_under_30pct_default
test_c1_fails_at_30pct_threshold
test_c1_fails_at_extended_zone_50pct
test_c1_returns_opt_above_vwap_pct_third_value
test_would_alert_extended_logged_when_only_c1_fails_in_30_to_50
test_would_alert_extended_not_logged_when_other_conditions_also_fail
test_would_alert_extended_disabled_when_toggle_off
test_would_alert_extended_only_when_log_extended_zone_true
```

### `tests/test_directional_gap.py` (~6 tests)

```
test_gap_up_returned_for_positive_breach_when_enabled
test_gap_down_returned_for_negative_breach_when_enabled
test_gap_up_disabled_when_toggle_off
test_gap_down_disabled_when_toggle_off
test_normal_when_below_threshold
test_legacy_gap_day_label_still_renders_in_telegram_format_gap_line
```

### `tests/test_orchestrator.py` additions (~5 tests)

```
test_dashboard_sync_runs_in_finally_block_on_clean_exit
test_dashboard_sync_runs_on_keyboard_interrupt
test_dashboard_sync_skipped_on_weekend_exit
test_dashboard_sync_skipped_when_toggle_disabled
test_dashboard_sync_failure_does_not_prevent_exit
```

Run: `pytest tests/ -v`.

---

## STEP 7 — Verification checklist

### After build (in any order)

```cmd
:: 1. All tests pass
pytest tests\ -v
:: → target ~275 tests

:: 2. Manual sync works
update_dashboard.bat
:: → creates logs\dashboards\dashboard_2026_Q2.xlsx and
::   data\scc_data_2026-05.parquet

:: 3. Idempotency — rerun, expect 0 new rows
update_dashboard.bat
:: → "Rows added: 0"

:: 4. Workbook structure
::    Open logs\dashboards\dashboard_2026_Q2.xlsx in Excel
::    Confirm 8 sheets in order: Strategy Dashboard, Daily Summary,
::    All Alerts, Order Place, All Signals, Rejections, Gap History,
::    Config Snapshot
::    Confirm Strategy Dashboard has KPI tiles + 4 charts

:: 5. Sample a real alert from Parquet
python -c "import pandas as pd; df=pd.read_parquet('data/scc_data_2026-05.parquet'); a=df[df.event_type=='alert']; print(a[['symbol','strike','option_type','bot_remark','bot_tags']].head())"

:: 6. Gap labels are directional
python -c "import pandas as pd; df=pd.read_parquet('data/scc_data_2026-05.parquet'); print(df[df.event_type=='gap'][['date','decision','nifty_gap_pct','banknifty_gap_pct']])"
```

### Live next-morning checklist

- Telegram alert (if any fires) includes an "Insight:" line.
- Telegram startup line shows directional gap verdict
  (`GAP UP` / `GAP DOWN` / `Normal day`).
- At 15:30 IST bot exits, log line "dashboard sync will run."
- Within 30 seconds: log lines "Bot exiting — running dashboard
  auto-sync..." and "Dashboard auto-sync complete on bot exit".
- `dashboard_2026_Q2.xlsx` mtime is today.
- `data/scc_data_2026-05.parquet` has grown by today's rows.

### Fill an outcome — confirm round-trip

1. Open `dashboard_2026_Q2.xlsx`.
2. Go to Order Place sheet.
3. Pick an alert row. Fill `Order Status = TP1_HIT`, `Exit Price = ...`,
   `P&L = ...`.
4. Save and close the workbook.
5. Run `update_dashboard.bat`.
6. Read the Parquet row:

```python
import pandas as pd
df = pd.read_parquet("data/scc_data_2026-05.parquet")
alert = df[(df.event_type == "alert") & (df.timestamp_ist == "<that row>")]
print(alert[["order_status", "exit_price", "pnl_rupees", "outcome_remark"]])
```

The `outcome_remark` should be auto-populated.

---

## What Phase 5.2.1 changed from the original 5.2

Documented here so future-you doesn't reintroduce the bug:

- **Bug:** the original 5.2 draft scheduled `update_dashboard()` to run
  at 15:35 IST from inside the polling loop. The polling loop exits at
  15:30 (`if now.time() >= MARKET_CLOSE_TIME: break`), so the 15:35
  branch never executed. The dashboard never auto-updated.
- **Fix:** move the dashboard sync to `run_forever()`'s `finally`
  clause. It runs exactly once per session, on any exit path.
- **Why the toggle is still called `auto_trigger_at_1535`:** kept for
  config back-compat (old `secrets.env` / `config.yaml` files keep
  working). Treat it as a boolean ON/OFF, not as a wall-clock time.

---

## STEP 8 — Phase 5B done. Now what?

After 5B verifies you have everything needed for **Phase 6** — 30
trading days of running the bot, reviewing the dashboard each evening,
filling Order Status in the Order Place sheet, and letting the
finally-block sync the outcomes back to Parquet. No code changes
during Phase 6.

After 30 days you have a Parquet dataset with at least one full month
of `event_type=alert` rows, each carrying `bot_remark`, `bot_tags`, and
user-filled `order_status` / `pnl_rupees`. That's the input for
**Phase 7 backtesting** and the threshold-tuning prerequisite for
**Phase 8 order placement**.
