# Phase 5B — Strategy Dashboard + ML Data Store + Bot Remarks

**Goal:** Layer human-readable Excel dashboards and a machine-readable
Parquet ML store on top of the alert-only bot built in `PHASE_5A.md`.
Add bot-generated entry remarks (`bot_remark` / `bot_tags`), a Telegram
"Insight:" line, directional gap labels (`GAP_UP` / `GAP_DOWN` /
`GAP_UP_DISABLED` / `GAP_DOWN_DISABLED`), a config-driven C1 threshold,
and a `would_alert_extended` event type for capturing 4/5 borderline
scans. Dashboard auto-syncs in the orchestrator's `finally` block so it
runs on clean exit, Ctrl+C, or unhandled exception.

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
  exception. Skipped on weekends and when the toggle is OFF.
- Best-effort Excel→Parquet back-sync of user-filled outcome columns
- Manual entry point: `update_dashboard.bat` / `scripts/update_dashboard.py`

## What Phase 5B does NOT do

- No order placement (Phase 8)
- No backtest harness (Phase 7)
- ~~No paper-trade simulation — outcome columns are filled manually~~
  **Superseded by the Phase 5B addendum (see end of this doc).** Auto
  outcome replay now stamps `auto_*` columns; the manual columns are
  still authoritative and untouched on conflict.
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

data/                                  ← NEW (Phase 5B)
  schema.md                            ← Column documentation (committed)
  scc_data_2026-05.parquet             ← One unified file per month

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

## STEP 1 — Strategy / behaviour deltas

### 1.1 — `requirements.txt`

Add (preserve existing):

```
openpyxl>=3.1.0
pyarrow>=14.0.0
pandas>=2.0.0
```

### 1.2 — `config/config.yaml`

Add a `conditions` section (extend if present):

```yaml
conditions:
  c1_max_distance_pct: 30          # Reject alerts where opt > 30% above own VWAP.
                                   # Strikes 30-50% above VWAP logged for analysis
                                   # but do NOT fire alerts.
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
> The behaviour is "run in `finally` on bot exit". Treat it as the
> on/off switch, not as a wall-clock setting.

### 1.3 — `src/conditions/c1_option_price_vwap.py` (config-driven)

The C1 late-entry filter now reads its threshold from config and returns
`(passed, reason, opt_above_vwap_pct)` — the third value is consumed by
the orchestrator's `would_alert_extended` logic.

```python
"""C1 — Option Price Above VWAP on a Green Candle."""

from __future__ import annotations

from src.indicators.calculator import IndicatorSnapshot


def check_c1(
    snapshot: IndicatorSnapshot, late_entry_threshold_pct: float
) -> tuple[bool, str, float]:
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

Also update `src/conditions/all_conditions.py` so the third return value
`opt_above_vwap_pct` is captured on the result object that the
orchestrator inspects.

### 1.4 — Directional gap labels

Replace the Phase 5A label set (`NORMAL` / `GAP_DAY` /
`GAP_DETECTED_BUT_DISABLED`) with the directional set. This is a
locally-contained change to `_detect_gap_day` and to
`TelegramAlerter._format_gap_line`.

**In `src/main.py`, end of `_detect_gap_day` — replace the tri-state
decision block with:**

```python
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

**In `src/alerts/telegram_bot.py`, expand `_format_gap_line`:**

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

## STEP 2 — Dashboard module (`src/dashboard/`)

### 2.1 — `src/dashboard/remarks.py`

Pure-function bot-remark + tag generator.

```python
"""Phase 5.2 — Bot remark + tag generation.

Pure functions, no I/O. The orchestrator calls ``generate_remark_and_tags``
at alert time; the Excel→Parquet back-sync calls ``generate_outcome_remark``
after the user fills ``order_status`` in the Order Place sheet.
"""

from __future__ import annotations

from typing import List, Tuple


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


# VixRegime.value is "Low Vol" / "Normal" / "Elevated" / "High Vol", but
# callers may also pass the enum NAME ("LOW" / "NORMAL" / ...). Both work.
_VIX_PHRASES = {
    "LOW":       ("low_vix",      "LOW VIX (0.75× SL)"),
    "NORMAL":    ("normal_vix",   ""),
    "ELEVATED":  ("elevated_vix", "ELEVATED VIX (1.25× SL)"),
    "HIGH":      ("high_vix",     "HIGH VIX (1.5× SL)"),
}
_VIX_VALUE_ALIASES = {
    "LOW VOL":   "LOW",
    "NORMAL":    "NORMAL",
    "ELEVATED":  "ELEVATED",
    "HIGH VOL":  "HIGH",
}


def _vix_context(vix_regime: str) -> Tuple[str, str]:
    if not vix_regime:
        return ("normal_vix", "")
    key = str(vix_regime).strip().upper()
    if key in _VIX_PHRASES:
        return _VIX_PHRASES[key]
    aliased = _VIX_VALUE_ALIASES.get(key)
    if aliased:
        return _VIX_PHRASES[aliased]
    return ("normal_vix", "")


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

    verdict = _verdict(snapshot)
    primary = observations[:4]
    secondary = [o for o in observations[4:] if o][:1]
    remark = f"{verdict} — " + ", ".join(primary + secondary) + "."
    return remark, ",".join(tags)


def _verdict(snapshot: dict) -> str:
    """Pick a quality prefix: strong / clean / borderline."""
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
    """Outcome remark based on alert quality + user-marked outcome.

    ``exit_price`` and ``pnl`` may be None (when the user has not filled
    those cells yet) — the helper falls back to a generic word.
    """
    bot_remark = alert_data.get("bot_remark", "") or ""
    is_strong = "strong" in bot_remark
    is_marginal = "borderline" in bot_remark

    exit_str = f"₹{exit_price:.2f}" if exit_price is not None else "exit"

    if outcome == "TP2_HIT":
        if is_strong:
            return f"Held to TP2 ({exit_str}) — strong setup played out. 2.5R captured."
        return f"Held to TP2 ({exit_str}) — 2.5R captured. Outcome confirmed setup."
    if outcome == "TP1_HIT":
        return f"TP1 hit at {exit_str} — 1.5R captured. Reversed before TP2."
    if outcome == "SL_HIT":
        if is_strong:
            return f"SL hit at {exit_str} — unusual reversal on strong setup."
        if is_marginal:
            return f"SL hit at {exit_str} — marginal entry showed in outcome."
        return f"SL hit at {exit_str} — reversed quickly."
    if outcome == "WOULD_SKIP":
        return "Skipped post-review — your judgement overrode 5/5."
    if outcome == "PARTIAL":
        pnl_str = f"₹{pnl:.0f}" if pnl is not None else "n/a"
        return f"Partial exit — manual decision, P&L {pnl_str}."
    return ""


def telegram_short_remark(bot_remark: str) -> str:
    """Trim ``bot_remark`` to verdict + 1-2 observations for Telegram.

    Designed for the "Insight:" line in the alert message. Output is
    typically 50–75 characters; never exceeds ~80.
    """
    if not bot_remark:
        return ""
    parts = bot_remark.split(" — ", 1)
    if len(parts) < 2:
        return bot_remark[:80]
    verdict, rest = parts
    rest_clean = rest.rstrip(".")
    obs = [o.strip() for o in rest_clean.split(",") if o.strip()]
    if len(obs) >= 2:
        return f"{verdict} — {obs[0]}, {obs[1]}"
    return f"{verdict} — {obs[0]}" if obs else verdict
```

### 2.1.1 — `src/conditions/all_conditions.py` delta

The C1 change in §1.3 returns a third value, so the orchestrator's
combined-conditions result object carries it for the orchestrator's
`_maybe_log_extended_zone` check. Also adds a small helper that prefers
the new config key but falls back to the legacy strike-section one.

```python
@dataclass
class AllConditionsResult:
    """Combined outcome of C0–C4 for a single closed candle."""

    all_passed: bool
    results: list[ConditionResult] = field(default_factory=list)
    opt_above_vwap_pct: float = 0.0  # Phase 5.2: C1 distance for logging.

    def failed_conditions(self) -> list[str]:
        return [r.name for r in self.results if not r.passed]

    def passed_conditions(self) -> list[str]:
        return [r.name for r in self.results if r.passed]

    def short_summary(self) -> str:
        """``C0 ✓ C1 ✓ C2 ✗ C3 ✓ C4 ✓`` style one-liner."""
        return " ".join(
            f"{r.name} {'✓' if r.passed else '✗'}" for r in self.results
        )

    def by_name(self, name: str) -> ConditionResult | None:
        for r in self.results:
            if r.name == name:
                return r
        return None


def _c1_max_distance(config) -> float:
    """Phase 5.2: prefer config.conditions.c1_max_distance_pct (new),
    fall back to config.strike.late_entry_threshold_percent (legacy).
    """
    conditions = getattr(config, "conditions", None)
    if conditions is not None:
        val = getattr(conditions, "c1_max_distance_pct", None)
        if val is not None:
            return float(val)
    return float(config.strike.late_entry_threshold_percent)


def check_all_conditions(
    option_snapshot: IndicatorSnapshot,
    spot_close: float, spot_vwap: float,
    option_type: str, config,
) -> AllConditionsResult:
    """Run all five conditions. Never short-circuits — logs need the full
    combination that failed."""
    results: list[ConditionResult] = []

    ok, reason = check_c0(spot_close, spot_vwap, option_type)
    results.append(ConditionResult("C0", ok, reason))

    c1_max = _c1_max_distance(config)
    c1_ok, c1_reason, opt_above_vwap_pct = check_c1(option_snapshot, c1_max)
    results.append(ConditionResult("C1", c1_ok, c1_reason))

    ok, reason = check_c2(option_snapshot)
    results.append(ConditionResult("C2", ok, reason))

    ok, reason = check_c3(
        option_snapshot,
        config.conditions.c3_rsi_min, config.conditions.c3_rsi_max,
    )
    results.append(ConditionResult("C3", ok, reason))

    ok, reason = check_c4(option_snapshot)
    results.append(ConditionResult("C4", ok, reason))

    all_passed = all(r.passed for r in results)
    return AllConditionsResult(
        all_passed=all_passed,
        results=results,
        opt_above_vwap_pct=opt_above_vwap_pct,
    )
```

---

### 2.2 — `src/dashboard/data_writer.py`

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
                logger.warning(
                    f"Skipping malformed JSON in {path.name} line {lineno}: {e}"
                )
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

    # Backfill the common columns so downstream filtering is uniform.
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
    flip None ↔ NaN, which would otherwise break equality compare. The
    string-only key is stable across reads.
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


def _filter_new_rows(
    incoming: pd.DataFrame, existing: pd.DataFrame
) -> pd.DataFrame:
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
# Public — Excel notes → Parquet
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
        import openpyxl  # noqa: F401  (loaded lazily; absence is harmless)
    except Exception as e:
        logger.debug(f"openpyxl unavailable: {e}")
        return pd.DataFrame()

    workbooks = _all_quarterly_dashboards()
    if not workbooks:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for wb_path in workbooks:
        try:
            sheet = pd.read_excel(
                wb_path, sheet_name="Order Place", engine="openpyxl",
            )
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
    """Best-effort back-fill of outcome columns from Excel into Parquet.

    Never raises. Any error is logged at debug level and reported in the
    return dict's ``skipped_reason``.

    Match key is ``(timestamp_ist, symbol, strike, option_type)`` against
    rows with ``event_type == "alert"``.
    """
    try:
        notes = _read_order_place_notes()
    except Exception as e:
        return {"alerts_updated": 0, "skipped_reason": f"read_failed: {e}"}

    if notes.empty:
        return {"alerts_updated": 0, "skipped_reason": "no notes filled yet"}

    months = _all_parquet_months()
    if not months:
        return {"alerts_updated": 0, "skipped_reason": "no parquet files yet"}

    # Normalise key columns on the notes side.
    notes["timestamp_ist"] = notes["timestamp_ist"].astype(str)
    if "strike" in notes.columns:
        notes["strike"] = pd.to_numeric(notes["strike"], errors="coerce")
    if "symbol" in notes.columns:
        notes["symbol"] = notes["symbol"].astype(str)
    if "option_type" in notes.columns:
        notes["option_type"] = notes["option_type"].astype(str)

    # Generate outcome_remark for any row where order_status is set.
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
            on=merge_cols, how="left", suffixes=("", "_excel"),
        )

        updated_count = 0
        for col in outcome_cols:
            excel_col = f"{col}_excel"
            if excel_col not in merged.columns:
                excel_col = col  # merged column not suffixed → use directly
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
            _write_parquet(
                parquet_path.stem.replace("scc_data_", ""), df
            )
            alerts_updated += updated_count

    if alerts_updated == 0:
        return {"alerts_updated": 0, "skipped_reason": "no matching alerts"}
    return {"alerts_updated": int(alerts_updated)}


# ---------------------------------------------------------------------------
# Helper used by excel_builder
# ---------------------------------------------------------------------------


def load_parquet_for_quarter(year: int, quarter: int) -> pd.DataFrame:
    """Concatenate the 3 months of a calendar quarter into one DataFrame.

    Empty months are skipped. Missing files are skipped. Returns an empty
    frame if nothing exists for the quarter.
    """
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

---

### 2.3 — `data/schema.md` (committed)

````markdown
# SCC Unified Parquet Schema — Phase 5.2

This document describes the columns in `data/scc_data_YYYY-MM.parquet`.
Files are regenerable at any time from the three JSONL logs via
`scripts/update_dashboard.py`.

## File naming

```
data/scc_data_YYYY-MM.parquet
```

One file per calendar month, ordered by `timestamp_ist`.

```python
import pandas as pd, glob
df = pd.concat([pd.read_parquet(f) for f in glob.glob("data/scc_data_2026-0[4-6].parquet")])
```

## event_type values

| event_type              | When written                                                  |
|-------------------------|---------------------------------------------------------------|
| `scan`                  | One per closed 5-min candle per strike. Default when none set in JSONL. |
| `alert`                 | One per 5/5-pass scan. Includes SL/TP/lot math + `bot_remark`/`bot_tags`. |
| `rejection`             | Silent rejection (C0 fast-fail, re-entry blocker, etc.).     |
| `data_issue`            | Mid-session start with `Insufficient lookback` ValueError.   |
| `would_alert_extended`  | 4/5 scan, only C1 failing, option 30–50% above VWAP.        |
| `gap`                   | One per bot startup from `gap_log.jsonl`.                    |

## Common columns (every row)

| Column          | Type   | Notes                                                            |
|-----------------|--------|------------------------------------------------------------------|
| `timestamp_ist` | str    | ISO 8601 with `+05:30` offset. Primary sort key.                 |
| `event_type`    | str    | One of the values above.                                         |
| `date`          | str    | `YYYY-MM-DD` derived from timestamp_ist.                         |
| `month`         | str    | `YYYY-MM`. Used to pick the target Parquet file.                 |
| `symbol`        | str    | `NIFTY` / `BANKNIFTY` / null for gap rows.                       |
| `_logged_at`    | str    | Bot's wall-clock when it wrote the JSONL line.                   |

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
| `opt_above_vwap_pct` | float | `(option_close - option_vwap) / option_vwap * 100`. Signed. |

## Condition columns (event_type ∈ {scan, alert, would_alert_extended})

| Column                | Type      | Notes                                              |
|-----------------------|-----------|----------------------------------------------------|
| `conditions_passed`   | list[str] | E.g. `["C0", "C2", "C3", "C4"]`.                   |
| `conditions_failed`   | list[str] | E.g. `["C1"]` for would_alert_extended.            |
| `all_passed`          | bool      | True only when 5/5 passed.                         |
| `summary`             | str       | `C0 ✓ C1 ✓ C2 ✗ C3 ✓ C4 ✓`-style one-liner.        |
| `reasons.C0` … `C4`   | str       | Per-condition reason text (flattened from nested). |

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
| `bot_remark`     | str    | Human-readable: "5/5 strong — opt 8% above VWAP, RSI 67 healthy zone..." |
| `bot_tags`       | str    | Comma-separated ML tags, no spaces.                    |
| `telegram_short_remark` | str | Trimmed for the Telegram alert "Insight:" line.   |

### Outcome columns (alert only — populated by user via Excel)

| Column            | Type   | Notes                                                |
|-------------------|--------|------------------------------------------------------|
| `order_status`    | str    | `TP2_HIT` / `TP1_HIT` / `SL_HIT` / `PARTIAL` / `WOULD_SKIP` / null. |
| `exit_price`      | float  | Filled manually in Order Place sheet.                |
| `pnl_rupees`      | float  | Sign convention: positive = profit.                  |
| `outcome_remark`  | str    | Auto-generated from `bot_remark` + `order_status`.   |
| `user_notes`      | str    | Free-form user observation.                          |

## Rejection-only columns (event_type == "rejection")

| Column                | Type | Notes                                                  |
|-----------------------|------|--------------------------------------------------------|
| `strike`              | int  | May be null when rejection happened before strike resolution. |
| `option_type`         | str  | `CE` / `PE`.                                           |
| `rejection_blocker`   | str  | Which condition / guardrail failed (e.g. `C0`, `RE_ENTRY_BLOCKED`). |
| `rejection_reason`    | str  | One-line human explanation.                            |

## Gap-only columns (event_type == "gap")

| Column                    | Type   | Notes                                              |
|---------------------------|--------|----------------------------------------------------|
| `decision`                | str    | `NORMAL`, `GAP_UP`, `GAP_DOWN`, `GAP_UP_DISABLED`, `GAP_DOWN_DISABLED`. Legacy: `GAP_DAY`, `GAP_DETECTED_BUT_DISABLED`. |
| `enabled`                 | bool   | Gap-day rule toggle at time of detection.          |
| `threshold_pct`           | float  | The threshold % in force.                          |
| `direction`               | str    | `both` / `up` / `down`.                            |
| `any_triggered`           | bool   | At least one symbol breached threshold.            |
| `nifty_open`              | float  | Today's 09:15 open for NIFTY.                      |
| `nifty_prev_close`        | float  | Previous trading-day close for NIFTY.              |
| `nifty_gap_pct`           | float  | Signed gap percentage for NIFTY.                   |
| `nifty_triggers`          | bool   | NIFTY breached threshold this morning.             |
| `nifty_error`             | str    | Diagnostic if gap math could not be computed.      |
| (same six for `banknifty_*`) |     |                                                    |

## data_issue-only columns (event_type == "data_issue")

| Column           | Type | Notes                                                  |
|------------------|------|--------------------------------------------------------|
| `strike`         | int  | The strike that was being scanned.                     |
| `option_type`    | str  | `CE` / `PE`.                                           |
| `issue_type`     | str  | Typically `INSUFFICIENT_LOOKBACK`.                     |
| `issue_message`  | str  | Indicator-calc error text (e.g. "need 33 candles").    |

## Forward-compatibility notes

- **Adding a column:** append columns. `pd.concat` preserves new columns
  as nulls in old rows. Don't rename existing columns; deprecate + add new.
- **Adding a new event_type:** the writer accepts any string. Update
  this doc and the Excel builder if the new type warrants its own sheet.
- **Removing a column:** never delete. Backfill with null in old files.
````

---

### 2.4 — `src/dashboard/excel_builder.py`

```python
"""Phase 5.2 — Quarterly Excel dashboard builder.

Reads the unified monthly Parquet files in ``data/`` and produces a
human-facing workbook at ``logs/dashboards/dashboard_YYYY_QN.xlsx``.

Eight sheets in order:

1. Strategy Dashboard — KPI tiles + 4 charts (visual at-a-glance view)
2. Daily Summary       — one row per trading day with the directional
                         gap label and aggregate counts
3. All Alerts          — every 5/5 alert; includes opt_above_vwap_pct,
                         bot_remark, bot_tags
4. Order Place         — automatic columns + manual columns the user
                         fills in (order status, exit price, P&L,
                         user notes); coloured by outcome
5. All Signals         — full audit including ``would_alert_extended``
                         rows highlighted in light orange
6. Rejections          — grouped by blocker
7. Gap History         — directional labels with colour swatches
8. Config Snapshot     — current config values for this quarter

Idempotent: re-running ``update_dashboard`` will rebuild the workbook
from scratch using the latest Parquet state.
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
from openpyxl.formatting.rule import CellIsRule
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

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")  # deep navy
_HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_TITLE_FONT = Font(name="Calibri", bold=True, color="1F4E78", size=16)
_SUBTITLE_FONT = Font(name="Calibri", italic=True, color="595959", size=10)
_BODY_FONT = Font(name="Calibri", size=11)
_THIN = Side(style="thin", color="BFBFBF")
_BORDER = Border(top=_THIN, bottom=_THIN, left=_THIN, right=_THIN)

OUTCOME_FILLS = {
    "TP2_HIT": PatternFill("solid", fgColor="6FBF73"),      # strong green
    "TP1_HIT": PatternFill("solid", fgColor="C8E6C9"),      # light green
    "SL_HIT": PatternFill("solid", fgColor="EF9A9A"),       # red
    "WOULD_SKIP": PatternFill("solid", fgColor="E0E0E0"),   # grey
    "PARTIAL": PatternFill("solid", fgColor="FFE082"),      # yellow
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


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


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
    """Approximate-autofit column widths from frame contents."""
    for col_idx, col in enumerate(df.columns, start=1):
        max_len = max(
            [len(str(col))] + [len(str(v)) for v in df[col].head(200).tolist()]
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(
            max(12, max_len + 2), 48
        )


def _write_dataframe(
    ws: Worksheet, df: pd.DataFrame, header_row: int = 1, start_row: int | None = None,
) -> int:
    """Write ``df`` to ``ws``. Returns row count written (excluding header)."""
    if df.empty:
        ws.cell(row=header_row, column=1, value="(no data yet)").font = _SUBTITLE_FONT
        return 0
    _set_headers(ws, [_pretty(c) for c in df.columns], row=header_row)
    sr = start_row if start_row is not None else header_row + 1
    for row_offset, (_, row) in enumerate(df.iterrows()):
        for col_idx, col in enumerate(df.columns, start=1):
            value = row[col]
            if pd.isna(value):
                value = None
            ws.cell(row=sr + row_offset, column=col_idx, value=value).font = _BODY_FONT
    _autofit(ws, df, header_row=header_row)
    return len(df)


def _pretty(col: str) -> str:
    """Convert ``opt_above_vwap_pct`` → ``Opt Above VWAP %`` etc."""
    if col == "opt_above_vwap_pct": return "Opt Above VWAP %"
    if col == "bot_remark":         return "Bot Remark"
    if col == "bot_tags":           return "Bot Tags"
    if col == "outcome_remark":     return "Outcome Remark"
    if col == "user_notes":         return "User Notes"
    if col == "order_status":       return "Order Status"
    if col == "exit_price":         return "Exit Price"
    if col == "pnl_rupees":         return "P&L"
    if col == "timestamp_ist":      return "Timestamp IST"
    return col.replace("_", " ").title()


def _outcome_fill_for(value) -> PatternFill | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return OUTCOME_FILLS.get(str(value).strip().upper())


def _gap_fill_for(value) -> PatternFill | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return GAP_FILLS.get(str(value).strip().upper())


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------


def _build_strategy_dashboard(
    ws: Worksheet, df: pd.DataFrame, year: int, quarter: int
) -> None:
    """KPI tiles + 4 charts. Designed to be the first thing the user sees."""
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:H1")
    title = ws.cell(row=1, column=1, value=f"SCC Strategy Dashboard — {year} Q{quarter}")
    title.font = _TITLE_FONT
    title.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:H2")
    subtitle = ws.cell(
        row=2, column=1,
        value=(
            "Auto-generated from Parquet · refreshes at 15:35 IST · "
            "filter the All Alerts / All Signals sheets for detail"
        ),
    )
    subtitle.font = _SUBTITLE_FONT

    alerts = df[df["event_type"] == "alert"] if "event_type" in df.columns else df.iloc[0:0]
    signals = df[df["event_type"].isin(["scan", "alert"])] if "event_type" in df.columns else df.iloc[0:0]
    extended = df[df["event_type"] == "would_alert_extended"] if "event_type" in df.columns else df.iloc[0:0]

    total_alerts = len(alerts)
    nifty_alerts = int(((alerts.get("symbol") == "NIFTY").sum()) if not alerts.empty else 0)
    bn_alerts = int(((alerts.get("symbol") == "BANKNIFTY").sum()) if not alerts.empty else 0)
    total_scans = len(signals)
    extended_count = len(extended)

    outcome_series = alerts.get("order_status") if "order_status" in alerts.columns else pd.Series(dtype=object)
    tp2 = int(((outcome_series == "TP2_HIT").sum()) if not alerts.empty else 0)
    tp1 = int(((outcome_series == "TP1_HIT").sum()) if not alerts.empty else 0)
    sl = int(((outcome_series == "SL_HIT").sum()) if not alerts.empty else 0)
    realised_pnl = float(alerts.get("pnl_rupees", pd.Series(dtype=float)).sum()) if not alerts.empty else 0.0
    filled_outcomes = int(outcome_series.notna().sum()) if not alerts.empty else 0
    win_rate = (tp1 + tp2) / filled_outcomes * 100.0 if filled_outcomes > 0 else 0.0

    kpi_rows = [
        ("Total Alerts", total_alerts, 0),
        ("NIFTY Alerts", nifty_alerts, 1),
        ("BankNifty Alerts", bn_alerts, 2),
        ("Total Scans", total_scans, 3),
        ("Extended-Zone Scans", extended_count, 4),
        ("Win Rate (filled)", f"{win_rate:.1f}%", 5),
        ("TP2 Hit", tp2, 0),
        ("TP1 Hit", tp1, 1),
        ("SL Hit", sl, 2),
        ("Filled Outcomes", filled_outcomes, 3),
        ("Realised P&L (₹)", f"{realised_pnl:,.0f}", 4),
        ("As of", datetime.now(IST).strftime("%Y-%m-%d %H:%M"), 5),
    ]

    base_row = 4
    for idx, (label, value, palette_idx) in enumerate(kpi_rows):
        row_off = (idx // 3) * 4
        col_off = (idx % 3) * 3
        top_row = base_row + row_off
        anchor_col = 1 + col_off

        # Top stripe (KPI accent).
        for c in range(anchor_col, anchor_col + 2):
            cell = ws.cell(row=top_row, column=c)
            cell.fill = KPI_FILLS[palette_idx % len(KPI_FILLS)]
            cell.font = Font(color="FFFFFF", bold=True, size=10)
        ws.cell(row=top_row, column=anchor_col, value=label.upper())

        # Big value cell (merged 2-wide).
        ws.merge_cells(
            start_row=top_row + 1, start_column=anchor_col,
            end_row=top_row + 1, end_column=anchor_col + 1,
        )
        v_cell = ws.cell(row=top_row + 1, column=anchor_col, value=value)
        v_cell.font = Font(size=18, bold=True, color="1F4E78")
        v_cell.alignment = Alignment(horizontal="center", vertical="center")
        v_cell.border = _BORDER
        ws.row_dimensions[top_row + 1].height = 32

    for col_letter in ("A", "B", "C", "D", "E", "F", "G", "H"):
        ws.column_dimensions[col_letter].width = 18

    # ---------- charts ----------
    chart_start_row = base_row + (((len(kpi_rows) - 1) // 3) + 1) * 4 + 2

    def _write_agg_table(
        title: str, items: list[tuple[str, float]], col_anchor: int
    ) -> tuple[int, int, int]:
        """Off-screen aggregation table that the chart references."""
        ws.cell(row=chart_start_row, column=col_anchor, value=title).font = Font(
            bold=True, color="1F4E78"
        )
        ws.cell(row=chart_start_row + 1, column=col_anchor, value="Bucket").font = _HEADER_FONT
        ws.cell(row=chart_start_row + 1, column=col_anchor).fill = _HEADER_FILL
        ws.cell(row=chart_start_row + 1, column=col_anchor + 1, value="Count").font = _HEADER_FONT
        ws.cell(row=chart_start_row + 1, column=col_anchor + 1).fill = _HEADER_FILL
        for i, (k, v) in enumerate(items, start=1):
            ws.cell(row=chart_start_row + 1 + i, column=col_anchor, value=k)
            ws.cell(row=chart_start_row + 1 + i, column=col_anchor + 1, value=v)
        return chart_start_row + 1, chart_start_row + 1 + len(items), col_anchor

    # 1. Wins vs Losses by Strike Relation
    relation_alerts = (
        alerts[alerts.get("relation").notna()]
        if not alerts.empty and "relation" in alerts.columns else pd.DataFrame()
    )
    rel_buckets: list[tuple[str, float]] = []
    if not relation_alerts.empty:
        for relation in ("ITM", "ATM", "OTM"):
            slice_ = relation_alerts[relation_alerts["relation"] == relation]
            wins = int(
                ((slice_.get("order_status") == "TP2_HIT").sum() if "order_status" in slice_.columns else 0)
                + ((slice_.get("order_status") == "TP1_HIT").sum() if "order_status" in slice_.columns else 0)
            )
            losses = int(((slice_.get("order_status") == "SL_HIT").sum()) if "order_status" in slice_.columns else 0)
            rel_buckets.append((f"{relation} Win", wins))
            rel_buckets.append((f"{relation} Loss", losses))
    if not rel_buckets:
        rel_buckets = [("No filled outcomes yet", 0)]

    hdr_row, end_row, anchor = _write_agg_table(
        "Wins / Losses by Strike Relation", rel_buckets, col_anchor=10
    )
    if any(v > 0 for _, v in rel_buckets):
        chart1 = BarChart(); chart1.type = "col"; chart1.style = 11
        chart1.title = "Wins vs Losses by Strike Relation"
        chart1.y_axis.title = "Count"; chart1.x_axis.title = "Bucket"
        data_ref = Reference(ws, min_col=anchor + 1, min_row=hdr_row, max_row=end_row, max_col=anchor + 1)
        cats_ref = Reference(ws, min_col=anchor, min_row=hdr_row + 1, max_row=end_row)
        chart1.add_data(data_ref, titles_from_data=True); chart1.set_categories(cats_ref)
        chart1.dataLabels = DataLabelList(showVal=True)
        ws.add_chart(chart1, f"A{chart_start_row}")

    # 2. Alerts by VIX Regime
    vix_counts = (
        alerts["vix_regime"].fillna("Unknown").value_counts().to_dict()
        if not alerts.empty and "vix_regime" in alerts.columns else {}
    )
    vix_items = list(vix_counts.items()) or [("(no alerts)", 0)]
    hdr2, end2, anc2 = _write_agg_table("Alerts by VIX Regime", vix_items, col_anchor=13)
    if any(v > 0 for _, v in vix_items):
        chart2 = BarChart(); chart2.type = "bar"; chart2.style = 12
        chart2.title = "Alerts by VIX Regime"
        data_ref = Reference(ws, min_col=anc2 + 1, min_row=hdr2, max_row=end2, max_col=anc2 + 1)
        cats_ref = Reference(ws, min_col=anc2, min_row=hdr2 + 1, max_row=end2)
        chart2.add_data(data_ref, titles_from_data=True); chart2.set_categories(cats_ref)
        chart2.dataLabels = DataLabelList(showVal=True)
        ws.add_chart(chart2, f"E{chart_start_row}")

    # 3. Alerts by Time of Day (30-min buckets)
    time_buckets: dict[str, int] = {}
    if not alerts.empty and "time" in alerts.columns:
        for t in alerts["time"].dropna().astype(str):
            try:
                hh, mm = int(t[:2]), int(t[3:5])
            except Exception:
                continue
            anchor_minute = (mm // 30) * 30
            key = f"{hh:02d}:{anchor_minute:02d}"
            time_buckets[key] = time_buckets.get(key, 0) + 1
    time_items = sorted(time_buckets.items()) or [("(no alerts)", 0)]
    hdr3, end3, anc3 = _write_agg_table("Alerts by 30-min Time Bucket", time_items, col_anchor=16)
    if any(v > 0 for _, v in time_items):
        chart3 = BarChart(); chart3.type = "col"; chart3.style = 13
        chart3.title = "Alerts by Time of Day (30-min buckets)"
        chart3.x_axis.title = "Time bucket"; chart3.y_axis.title = "Alerts"
        data_ref = Reference(ws, min_col=anc3 + 1, min_row=hdr3, max_row=end3, max_col=anc3 + 1)
        cats_ref = Reference(ws, min_col=anc3, min_row=hdr3 + 1, max_row=end3)
        chart3.add_data(data_ref, titles_from_data=True); chart3.set_categories(cats_ref)
        chart3.dataLabels = DataLabelList(showVal=True)
        ws.add_chart(chart3, f"A{chart_start_row + 16}")

    # 4. Cumulative P&L line
    cum_items: list[tuple[str, float]] = []
    if not alerts.empty and "pnl_rupees" in alerts.columns:
        pnl_rows = alerts[alerts["pnl_rupees"].notna()].sort_values("timestamp_ist")
        running = 0.0
        for _, r in pnl_rows.iterrows():
            running += float(r["pnl_rupees"])
            label = str(r.get("date") or r.get("timestamp_ist", ""))[:10]
            cum_items.append((label, running))
    if not cum_items:
        cum_items = [("(no filled P&L)", 0.0)]
    hdr4, end4, anc4 = _write_agg_table("Cumulative P&L", cum_items, col_anchor=19)
    if any(isinstance(v, (int, float)) and v != 0 for _, v in cum_items):
        chart4 = LineChart(); chart4.style = 12
        chart4.title = "Cumulative P&L (₹)"
        chart4.x_axis.title = "Date"; chart4.y_axis.title = "Cumulative P&L"
        data_ref = Reference(ws, min_col=anc4 + 1, min_row=hdr4, max_row=end4, max_col=anc4 + 1)
        cats_ref = Reference(ws, min_col=anc4, min_row=hdr4 + 1, max_row=end4)
        chart4.add_data(data_ref, titles_from_data=True); chart4.set_categories(cats_ref)
        ws.add_chart(chart4, f"E{chart_start_row + 16}")


def _build_daily_summary(ws: Worksheet, df: pd.DataFrame) -> int:
    if df.empty or "date" not in df.columns:
        _set_headers(ws, ["Date", "Note"])
        ws.cell(row=2, column=1, value="(no data)").font = _SUBTITLE_FONT
        return 0

    alerts = df[df["event_type"] == "alert"]
    signals = df[df["event_type"].isin(["scan", "alert"])]
    extended = df[df["event_type"] == "would_alert_extended"]
    rejections = df[df["event_type"] == "rejection"]
    gaps = df[df["event_type"] == "gap"]

    dates = sorted({d for d in df["date"].dropna().unique()})

    rows: list[dict] = []
    for d in dates:
        gap_row = gaps[gaps["date"] == d]
        decision = (
            gap_row.iloc[0]["decision"]
            if not gap_row.empty and "decision" in gap_row.columns else "NORMAL"
        )
        nifty_gap = gap_row.iloc[0].get("nifty_gap_pct") if not gap_row.empty else None
        bn_gap = gap_row.iloc[0].get("banknifty_gap_pct") if not gap_row.empty else None
        rows.append({
            "date": d, "gap_decision": decision,
            "nifty_gap_pct": nifty_gap, "banknifty_gap_pct": bn_gap,
            "scans": int(len(signals[signals["date"] == d])),
            "alerts": int(len(alerts[alerts["date"] == d])),
            "extended": int(len(extended[extended["date"] == d])),
            "rejections": int(len(rejections[rejections["date"] == d])),
            "nifty_alerts": int(((alerts["date"] == d) & (alerts.get("symbol") == "NIFTY")).sum())
                if not alerts.empty else 0,
            "banknifty_alerts": int(((alerts["date"] == d) & (alerts.get("symbol") == "BANKNIFTY")).sum())
                if not alerts.empty else 0,
        })

    out = pd.DataFrame(rows)
    written = _write_dataframe(ws, out)

    if "gap_decision" in out.columns and written:
        gap_col_idx = list(out.columns).index("gap_decision") + 1
        for i in range(written):
            cell = ws.cell(row=2 + i, column=gap_col_idx)
            fill = _gap_fill_for(cell.value)
            if fill:
                cell.fill = fill
    ws.freeze_panes = "A2"
    return written


def _build_all_alerts(ws: Worksheet, df: pd.DataFrame) -> int:
    alerts = df[df["event_type"] == "alert"] if "event_type" in df.columns else pd.DataFrame()
    if alerts.empty:
        _set_headers(ws, ["(no alerts yet)"])
        return 0

    show_cols = [
        "timestamp_ist", "date", "time", "symbol", "strike", "relation",
        "option_type", "expiry", "spot_price", "entry", "sl", "tp1", "tp2",
        "lots", "total_risk", "vix", "vix_regime", "day_type",
        "opt_above_vwap_pct", "rsi", "rsi_ma", "oi", "oi_ma",
        "volume", "volume_ma", "bot_remark", "bot_tags",
    ]
    cols = [c for c in show_cols if c in alerts.columns]
    out = alerts[cols].sort_values("timestamp_ist").reset_index(drop=True)
    written = _write_dataframe(ws, out)

    for wrap_col in ("bot_remark", "bot_tags"):
        if wrap_col in out.columns:
            ci = list(out.columns).index(wrap_col) + 1
            ws.column_dimensions[get_column_letter(ci)].width = 60
            for r in range(2, written + 2):
                ws.cell(row=r, column=ci).alignment = Alignment(
                    wrap_text=True, vertical="top"
                )
    ws.freeze_panes = "A2"
    return written


def _build_order_place(ws: Worksheet, df: pd.DataFrame) -> int:
    alerts = df[df["event_type"] == "alert"] if "event_type" in df.columns else pd.DataFrame()

    auto_cols = [
        "timestamp_ist", "date", "time", "symbol", "strike", "relation",
        "option_type", "entry", "sl", "tp1", "tp2", "lots", "total_risk",
        "bot_remark",
    ]
    manual_cols = ["order_status", "exit_price", "pnl_rupees", "outcome_remark", "user_notes"]

    if alerts.empty:
        _set_headers(ws, [_pretty(c) for c in auto_cols + manual_cols])
        ws.cell(row=2, column=1,
                value="(no alerts yet — manual columns activate after first alert)").font = _SUBTITLE_FONT
        return 0

    out = alerts.copy()
    for col in manual_cols:
        if col not in out.columns:
            out[col] = None
    out = out[auto_cols + manual_cols].sort_values("timestamp_ist").reset_index(drop=True)
    written = _write_dataframe(ws, out)

    if "order_status" in out.columns and written:
        status_col_idx = list(out.columns).index("order_status") + 1
        for i in range(written):
            cell = ws.cell(row=2 + i, column=status_col_idx)
            fill = _outcome_fill_for(cell.value)
            if fill:
                cell.fill = fill

    if "pnl_rupees" in out.columns and written:
        pnl_idx = list(out.columns).index("pnl_rupees") + 1
        green = PatternFill("solid", fgColor="C8E6C9")
        red = PatternFill("solid", fgColor="EF9A9A")
        for i in range(written):
            cell = ws.cell(row=2 + i, column=pnl_idx)
            v = cell.value
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            cell.fill = green if fv >= 0 else red

    for wrap_col in ("bot_remark", "outcome_remark", "user_notes"):
        if wrap_col in out.columns:
            ci = list(out.columns).index(wrap_col) + 1
            ws.column_dimensions[get_column_letter(ci)].width = 48
            for r in range(2, written + 2):
                ws.cell(row=r, column=ci).alignment = Alignment(
                    wrap_text=True, vertical="top"
                )

    # Legend strip below the data.
    legend_row = written + 3
    ws.cell(row=legend_row, column=1, value="Outcome legend:").font = Font(bold=True)
    for i, (label, fill) in enumerate(OUTCOME_FILLS.items(), start=2):
        cell = ws.cell(row=legend_row, column=i, value=label)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A2"
    return written


def _build_all_signals(ws: Worksheet, df: pd.DataFrame) -> int:
    if df.empty or "event_type" not in df.columns:
        _set_headers(ws, ["(no signals yet)"])
        return 0

    signals = df[df["event_type"].isin(["scan", "alert", "would_alert_extended"])].copy()
    if signals.empty:
        _set_headers(ws, ["(no signals yet)"])
        return 0

    show_cols = [
        "timestamp_ist", "date", "time", "event_type", "symbol", "strike",
        "relation", "option_type", "spot_price", "spot_vwap",
        "option_close", "option_vwap", "opt_above_vwap_pct",
        "rsi", "rsi_ma", "oi", "oi_ma", "volume", "volume_ma",
        "is_green", "all_passed", "summary",
    ]
    cols = [c for c in show_cols if c in signals.columns]
    if "time" not in signals.columns and "timestamp_ist" in signals.columns:
        signals["time"] = signals["timestamp_ist"].astype(str).str.slice(11, 16)
        cols = [c for c in show_cols if c in signals.columns]

    out = signals[cols].sort_values("timestamp_ist").reset_index(drop=True)
    written = _write_dataframe(ws, out)

    # Highlight: would_alert_extended → light orange; all_passed → yellow;
    # else colour by Relation.
    if written:
        all_passed_col = (
            list(out.columns).index("all_passed") + 1 if "all_passed" in out.columns else None
        )
        event_col = list(out.columns).index("event_type") + 1
        relation_col = (
            list(out.columns).index("relation") + 1 if "relation" in out.columns else None
        )
        for i in range(written):
            event_val = ws.cell(row=2 + i, column=event_col).value
            if event_val == "would_alert_extended":
                for c in range(1, len(out.columns) + 1):
                    ws.cell(row=2 + i, column=c).fill = EXTENDED_FILL
                continue
            ap_val = ws.cell(row=2 + i, column=all_passed_col).value if all_passed_col else False
            if ap_val is True or ap_val == "True":
                for c in range(1, len(out.columns) + 1):
                    ws.cell(row=2 + i, column=c).fill = ALL_PASSED_FILL
                continue
            if relation_col is not None:
                rel = ws.cell(row=2 + i, column=relation_col).value
                fill = RELATION_FILLS.get(str(rel)) if rel else None
                if fill:
                    for c in range(1, len(out.columns) + 1):
                        ws.cell(row=2 + i, column=c).fill = fill
    ws.freeze_panes = "A2"
    return written


def _build_rejections(ws: Worksheet, df: pd.DataFrame) -> int:
    if df.empty or "event_type" not in df.columns:
        _set_headers(ws, ["(no rejections)"])
        return 0
    rej = df[df["event_type"] == "rejection"].copy()
    if rej.empty:
        _set_headers(ws, ["(no rejections)"])
        return 0
    cols = [
        c for c in (
            "timestamp_ist", "date", "symbol", "strike", "option_type",
            "rejection_blocker", "rejection_reason",
        ) if c in rej.columns
    ]
    out = (
        rej[cols].sort_values(["rejection_blocker", "timestamp_ist"]).reset_index(drop=True)
    )
    written = _write_dataframe(ws, out)
    ws.freeze_panes = "A2"
    return written


def _build_gap_history(ws: Worksheet, df: pd.DataFrame) -> int:
    if df.empty or "event_type" not in df.columns:
        _set_headers(ws, ["(no gap history)"])
        return 0
    gaps = df[df["event_type"] == "gap"].copy()
    if gaps.empty:
        _set_headers(ws, ["(no gap history)"])
        return 0
    cols = [
        c for c in (
            "timestamp_ist", "date", "decision", "enabled", "threshold_pct",
            "direction", "any_triggered",
            "nifty_open", "nifty_prev_close", "nifty_gap_pct",
            "banknifty_open", "banknifty_prev_close", "banknifty_gap_pct",
        ) if c in gaps.columns
    ]
    out = gaps[cols].sort_values("timestamp_ist").reset_index(drop=True)
    written = _write_dataframe(ws, out)

    if "decision" in out.columns and written:
        dec_col_idx = list(out.columns).index("decision") + 1
        for i in range(written):
            cell = ws.cell(row=2 + i, column=dec_col_idx)
            fill = _gap_fill_for(cell.value)
            if fill:
                cell.fill = fill
    ws.freeze_panes = "A2"
    return written


def _build_config_snapshot(ws: Worksheet) -> None:
    """Flatten the current config.yaml into a Setting/Value sheet."""
    from src.config_loader import load_config

    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "config" / "config.yaml"
    try:
        cfg = load_config(config_path)
    except Exception as e:
        ws.cell(row=1, column=1, value=f"Failed to load config: {e}").font = _SUBTITLE_FONT
        return

    rows = []
    rows.append(("Generated at", datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")))
    rows.append(("Active feed", cfg.feeds.active_feed))
    rows.append(("Alert mode", cfg.mode.alert_mode))
    rows.append(("Order place mode", cfg.mode.order_place_mode))
    rows.append(("Paper trade mode", cfg.mode.paper_trade_mode))
    rows.append(("NIFTY enabled", cfg.instruments.nifty_enabled))
    rows.append(("BankNifty enabled", cfg.instruments.banknifty_enabled))
    rows.append(("NIFTY lot size", cfg.instruments.nifty_lot_size))
    rows.append(("BankNifty lot size", cfg.instruments.banknifty_lot_size))
    rows.append(("Normal start time", cfg.time_rules.normal_start_time))
    rows.append(("Gap-day start time", cfg.time_rules.gap_day_start_time))
    rows.append(("Last entry time", cfg.time_rules.last_entry_time))
    rows.append(("Hard squareoff time", cfg.time_rules.hard_squareoff_time))
    rows.append(("Gap-day enabled", cfg.time_rules.gap_day_enabled))
    rows.append(("Gap-day threshold %", cfg.time_rules.gap_day_threshold_pct))
    rows.append(("Gap-day direction", cfg.time_rules.gap_day_direction))
    rows.append(("Target risk / trade (₹)", cfg.risk_reward.target_risk_per_trade))
    rows.append(("Risk range", f"₹{cfg.risk_reward.risk_range_min}–{cfg.risk_reward.risk_range_max}"))
    rows.append(("TP1 / TP2 (normal)", f"{cfg.risk_reward.normal_day_tp1_r}R / {cfg.risk_reward.normal_day_tp2_r}R"))
    rows.append(("TP1 / TP2 (expiry)", f"{cfg.risk_reward.expiry_day_tp1_r}R / {cfg.risk_reward.expiry_day_tp2_r}R"))
    rows.append(("Max SL per day", cfg.circuit_breakers.max_sl_per_day))
    rows.append(("Max loss per day (₹)", cfg.circuit_breakers.max_loss_per_day_rupees))
    rows.append(("RSI min / max", f"{cfg.conditions.c3_rsi_min} – {cfg.conditions.c3_rsi_max}"))
    rows.append(("C1 max distance %", cfg.conditions.c1_max_distance_pct))
    rows.append(("C1 extended zone max %", cfg.conditions.c1_extended_zone_max_pct))
    rows.append(("Auto-dashboard at 15:35", cfg.dashboard.auto_trigger_at_1535))

    _set_headers(ws, ["Setting", "Value"])
    for i, (k, v) in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=k).font = _BODY_FONT
        ws.cell(row=i, column=2, value=v).font = _BODY_FONT
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 30


# ---------------------------------------------------------------------------
# Public — update_dashboard
# ---------------------------------------------------------------------------


def update_dashboard() -> dict:
    """Refresh every quarter touched by the data files. Idempotent."""
    DASHBOARDS_DIR.mkdir(parents=True, exist_ok=True)

    now_ist = datetime.now(IST)
    today_q = quarter_for_date(now_ist)

    # Find every (year, quarter) present in the Parquet data.
    from src.dashboard.data_writer import _all_parquet_months  # avoid cycle

    months = _all_parquet_months()
    quarters: set[tuple[int, int]] = set()
    for p in months:
        try:
            month_str = p.stem.replace("scc_data_", "")
            year, month = map(int, month_str.split("-"))
            quarters.add((year, (month - 1) // 3 + 1))
        except Exception:
            continue

    # Always include current quarter so the file exists on day 1.
    quarters.add(today_q)

    if not quarters:
        return {"status": "no_data", "output_path": None}

    latest_written: Path | None = None
    counts = {
        "alerts_added": 0, "signals_added": 0,
        "order_place_added": 0, "rejections_added": 0,
        "gaps_added": 0, "quarters_touched": 0,
    }

    for year, quarter in sorted(quarters):
        df = load_parquet_for_quarter(year, quarter)
        path = _build_workbook(year, quarter, df)
        latest_written = path
        counts["quarters_touched"] += 1
        if not df.empty and "event_type" in df.columns:
            counts["alerts_added"] += int((df["event_type"] == "alert").sum())
            counts["signals_added"] += int(
                df["event_type"].isin(["scan", "alert", "would_alert_extended"]).sum()
            )
            counts["order_place_added"] += int((df["event_type"] == "alert").sum())
            counts["rejections_added"] += int((df["event_type"] == "rejection").sum())
            counts["gaps_added"] += int((df["event_type"] == "gap").sum())

    return {
        "status": "ok",
        "output_path": str(latest_written) if latest_written else None,
        **counts,
    }


def _build_workbook(year: int, quarter: int, df: pd.DataFrame) -> Path:
    wb = Workbook()
    dash = wb.active
    dash.title = "Strategy Dashboard"
    _build_strategy_dashboard(dash, df, year, quarter)

    daily = wb.create_sheet("Daily Summary");   _build_daily_summary(daily, df)
    alerts = wb.create_sheet("All Alerts");     _build_all_alerts(alerts, df)
    order = wb.create_sheet("Order Place");     _build_order_place(order, df)
    signals = wb.create_sheet("All Signals");   _build_all_signals(signals, df)
    rejects = wb.create_sheet("Rejections");    _build_rejections(rejects, df)
    gaps = wb.create_sheet("Gap History");      _build_gap_history(gaps, df)
    cfg_sheet = wb.create_sheet("Config Snapshot"); _build_config_snapshot(cfg_sheet)

    path = _resolve_excel_path(year, quarter)
    wb.save(path)
    logger.info(f"Dashboard written: {path}")
    return path
```

---

### 2.5 — `src/dashboard/__init__.py`

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

### 2.6 — `scripts/update_dashboard.py` + `update_dashboard.bat`

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

## STEP 3 — `.gitignore`

Add (preserve existing):

```
# Dashboard outputs (regenerable from JSONL)
logs/dashboards/
data/scc_data_*.parquet

# But keep schema documentation
!data/schema.md
```

---

## STEP 4 — Unit tests

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

## STEP 5 — Verification checklist

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

:: 5. Sample a real alert from Parquet
python -c "import pandas as pd; df=pd.read_parquet('data/scc_data_2026-05.parquet'); a=df[df.event_type=='alert']; print(a[['symbol','strike','option_type','bot_remark','bot_tags']].head())"

:: 6. Gap labels are directional
python -c "import pandas as pd; df=pd.read_parquet('data/scc_data_2026-05.parquet'); print(df[df.event_type=='gap'][['date','decision','nifty_gap_pct','banknifty_gap_pct']])"
```

### Live next-morning checklist

- Telegram alert (if any fires) includes an "Insight:" line.
- Telegram startup line shows directional gap verdict (`GAP UP` / `GAP DOWN` / `Normal day`).
- At 15:30 IST bot exits, log line "dashboard sync will run."
- Within 30 seconds: log lines "Bot exiting — running dashboard auto-sync..." and "Dashboard auto-sync complete on bot exit".
- `dashboard_2026_Q2.xlsx` mtime is today.
- `data/scc_data_2026-05.parquet` has grown by today's rows.

### Fill an outcome — confirm round-trip

1. Open `dashboard_2026_Q2.xlsx` → Order Place sheet.
2. Pick an alert row. Fill `Order Status = TP1_HIT`, `Exit Price`, `P&L`.
3. Save and close the workbook.
4. Run `update_dashboard.bat`.
5. Confirm `outcome_remark` is auto-populated in the Parquet row.

---

## STEP 6 — Phase 5B done. Now what?

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

---

## Phase 5B Addendum — Robustness fixes (post-first-live-run)

Three small but important fixes folded in after the very first
alert-only live runs surfaced a partial-candle data bug and a need to
make the C0 gate flexible.

### A. Stale / in-progress candle guard (data accuracy)

**Symptom:** Intermittently the orchestrator read the wrong candle
(e.g. close=125.90, volume=57k while the real just-closed candle was
close=133.85, volume=5.65M — the partial-candle volume was ~100× too
small, proving an unfinalised candle was being scanned).

**Root cause:** Broker candle endpoints sometimes include the
currently-forming candle in their response.

**Fixes in code:**
- `src/data/kite_feed.py` and `src/data/upstox_feed.py` both have a
  new module-level helper `_drop_in_progress_5min(df)` that filters
  out any candle whose timestamp is `>= current 5-min boundary`
  (IST). It's called inside `get_5min_candles()` after the response
  is normalised into a DataFrame and before the lookback trim, so
  `.iloc[-1]` is ALWAYS the last fully closed candle.
- `src/main.py` adds `_fetch_closed_candles_with_retry()`. It calls
  the feed, checks that the last candle's timestamp matches the
  expected `(current 5-min boundary) - 5 min`, and retries
  `config.bot.api_retry_count` times with
  `config.bot.api_retry_delay_seconds` between tries. If the data is
  still stale (>6 min old) after all retries — or empty — it raises a
  `_StaleCandleError` which `_scan_strike()` catches and routes to
  `_log_data_issue(... issue_type="STALE_CANDLE", ...)`.
- DEBUG-level log of the last candle's `(timestamp, close, volume)` is
  emitted whenever `config.logging.log_indicator_values` is ON, so
  future mismatches are diagnosable from `bot.log`.
- `config/config.yaml`: `bot.scan_buffer_seconds` raised from `5` to
  `20`. Kite takes ~15-20s to finalise a 5-min candle; scanning too
  early was the trigger for the partial-candle bug.

### B. C0 (spot trend filter) is now toggleable, default OFF

**Goal:** Let users disable the spot-vs-VWAP direction gate so the bot
scans BOTH CE and PE on every selected strike each candle (C1–C4 still
decide). Keeps the original C0 logic available — just behind a switch.

**Fixes in code:**
- `config/config.yaml` under `conditions:` now has
  `c0_spot_trend_filter_enabled: OFF` (new safe default).
- `src/config_loader.py`: `ConditionsConfig` gains
  `c0_spot_trend_filter_enabled: bool = Field(default=False)` and the
  ON/OFF validator. Default `False` so older configs (missing the
  field) load cleanly with the new behaviour.
- `src/conditions/all_conditions.py`: when the toggle is OFF,
  `check_all_conditions()` appends
  `ConditionResult("C0", True, "C0 SKIPPED: spot trend filter disabled in config")`
  so `all_passed` math, the `C0 ✓ C1 ✓ …` summary, and dashboards
  continue to see C0 in the row. The real `check_c0()` is still
  exported and runs only when the toggle is ON.
- `src/main.py` `_scan_symbol()`: when the toggle is OFF the
  CE/PE fast-fail spot/VWAP gate is bypassed and BOTH CE and PE are
  scanned per selected strike. When ON, original Phase 5A behaviour
  is preserved unchanged (a CE option with spot ≤ VWAP gets a C0
  rejection logged and no option chain fetch happens).
- One INFO log per scan per symbol: `Scan plan: NIFTY will check N
  option contracts this candle (c0_filter=OFF)`.

### C. Per-level strike depth toggles (ITM3..ATM..OTM3)

The Phase-4 three-way toggles (`itm/atm/otm`) were superseded by
**seven per-level booleans** so each strike depth can be enabled
independently. The old single-bool `itm`/`otm` flags scanned exactly
one strike in each direction; the new schema lets the operator choose
any combination of depths 1/2/3 — including non-contiguous combos
(e.g. ITM1 ON, ITM2 OFF, ITM3 ON).

`config/config.yaml` defaults — ITM2/ITM1/ATM ON, rest OFF (6
contracts per symbol per scan with C0 off):

```yaml
strike:
  alert_strikes:
    itm3: OFF
    itm2: ON
    itm1: ON
    atm:  ON
    otm1: OFF
    otm2: OFF
    otm3: OFF
```

Strike arithmetic (interval from `get_strike_interval(symbol)` —
NIFTY=50, BANKNIFTY=100, never hardcoded inside the selector):

| Relation | CE strike                | PE strike                |
|----------|--------------------------|--------------------------|
| ITM3     | atm − 3 × interval       | atm + 3 × interval       |
| ITM2     | atm − 2 × interval       | atm + 2 × interval       |
| ITM1     | atm − 1 × interval       | atm + 1 × interval       |
| ATM      | atm                      | atm                      |
| OTM1     | atm + 1 × interval       | atm − 1 × interval       |
| OTM2     | atm + 2 × interval       | atm − 2 × interval       |
| OTM3     | atm + 3 × interval       | atm − 3 × interval       |

If an arithmetic strike is missing from the broker option chain
(illiquid, doesn't exist), it is **skipped silently with a debug
log** — the selector never invents a contract.

`AlertStrikesConfig` (in `src/config_loader.py`) keeps the
"at least one level ON" validator: every toggle OFF is rejected so
the bot can never be silently disabled.

`signals.jsonl` / `alerts.jsonl` / `data/*.parquet` `relation`
column now contains values from `{ITM3, ITM2, ITM1, ATM, OTM1,
OTM2, OTM3}`. Downstream code (`src/dashboard/excel_builder.py`
RELATION_FILLS, Win/Loss-by-Relation aggregation) handles the
seven labels and tolerates any unknown label by appending it at
the end of the display order — no hardcoded 3-relation list.

**Killed-strike tracking** (`src/state/state_manager.py`) keys off
the actual strike *number* (`{SYMBOL}_{STRIKE}_{OPTION_TYPE}`), not
the relation label. So a strike killed when scanned as ITM1 stays
killed when later scanned as ITM2 (after spot drifts) — each strike
number is tracked once across all depth levels.

**One-time migration** (`scripts/migrate_relation_labels.py`):
renames legacy `relation` values in JSONL + Parquet — `ITM → ITM1`,
`OTM → OTM1`; `ATM` is unchanged. Idempotent; safe to re-run.

`order_strikes` (Phase 8 auto-order config) is **unchanged** —
still uses the legacy three-way `itm/atm/otm` schema. Alert and
order paths are intentionally decoupled (alert on more, order on
fewer).

### Tests covering the above (`tests/test_phase5b_fixes.py`)

- `test_kite_get_5min_candles_drops_in_progress_candle`
- `test_upstox_get_5min_candles_drops_in_progress_candle`
- `test_scan_strike_logs_stale_candle_when_last_candle_too_old`
- `test_scan_strike_stale_candle_retries_then_succeeds_when_fresh`
- `test_config_defaults_c0_filter_to_false`
- `test_c0_disabled_appends_skipped_result_passed_true`
- `test_c0_enabled_preserves_current_fast_fail_behavior`
- `test_c0_disabled_scans_both_ce_and_pe`
- `test_c0_enabled_fast_fails_pe_when_spot_above_vwap`
- `test_alert_strikes_otm_off_excludes_otm`
- `test_alert_strikes_itm_atm_on_otm_off_returns_correct_relations`
- `test_config_validator_rejects_all_strikes_off`
- `test_default_toggles_itm1_itm2_atm_on_rest_off`
- `test_enabled_toggles_generate_matching_relations`
- `test_itm_levels_mirror_correctly_for_ce_vs_pe`
- `test_non_contiguous_toggles_allowed`
- `test_all_toggles_off_rejected_by_validator`
- `test_strike_interval_read_from_config_not_hardcoded`
- `test_killed_strike_tracks_by_number_across_levels`

Total suite after this addendum: **312 passed**.

---

## Addendum — Phase 5B-A: Automatic Outcome Tracking (virtual, alert-only)

> NOTE: First-alert collapse, the TAKEN/SKIPPED selection gate, and paper P&L live in Phase 5D (docs/phases/PHASE_5D.md). 5D *calls* this kernel; it does not duplicate it.

This addendum supersedes the original "outcomes are manual" decision.
The bot still does not place orders and still does not run live during
the day. After EOD it replays each 5/5 alert against the day's 5-min
option candles and stamps the result into new `auto_*` columns. Manual
columns remain authoritative — they are never overwritten.

### Why

Phase 6 is a 30-trading-day live alert-only validation. Without an
auto-outcome path, that's 30 days of manual Excel filling before any
data can be evaluated. Auto replay gives the same data immediately
with the same exit rules the strategy doc specifies. It is also the
exit kernel Phase 7's backtest harness will call — one implementation,
not two.

### Exit model

Follows Section 9 of `ShortCoverCascade_v3.1_FINAL.md` exactly. All
numeric inputs come from config — nothing is hardcoded:

- `R = entry − sl`, both read from the logged `alerts.jsonl` row
  (single source of truth — config drift between alert and replay
  cannot change historical R).
- Entry assumption: filled at the logged `entry` on the alert candle.
  Documented in `data/schema.md`.
- Walk each subsequent 5-min option candle in time order:
  - **SL_HIT** if `low <= current_sl` and TP1 not yet hit.
  - **HARD_EXIT** if a complete red candle body forms entirely below
    the option's running session VWAP. Implementation reuses
    `src/indicators/vwap.compute_session_vwap` — no duplicate VWAP
    formula.
  - **TP1** (1.5R normal / 2.0R expiry): on touch, exit 50%. If
    `risk_reward.move_sl_to_breakeven_after_tp1` is ON, move the
    remaining 50%'s SL to entry. (If
    `risk_reward.trail_sl_after_tp1` is ON, replay refuses to stamp
    and logs a loud warning — see "Refusal" below.)
  - **TP2** (2.5R normal / 3.0R expiry): remaining 50% exits.
  - **3:00 PM hard deadline**: any still-open virtual position is
    closed at the last walked candle's close.
- **Intrabar ambiguity**: if one candle's range covers both a stop and
  a target, assume the **stop first** (conservative) and set
  `intrabar_ambiguous = true`.

### Outcome categories

Written into the new `auto_order_status` column. Mirrors the manual
categories but adds two:

| auto_order_status | When |
|-------------------|------|
| `TP2_HIT`         | TP1 then TP2 reached. |
| `TP1_HIT`         | TP1 reached; second leg EOD-flat at >= adjusted SL (i.e. SL never hit). |
| `PARTIAL`         | TP1 reached; second leg hit breakeven/SL or hard-exit. |
| `SL_HIT`          | SL hit before TP1. |
| `EOD_FLAT`        | Neither SL nor TP1 hit by 15:00. |
| `HARD_EXIT`       | Hard-exit rule triggered before TP1. |

### Columns appended (Parquet + Excel Order Place sheet + schema.md)

Append-only, never rename, never overwrite the manual columns.

| Column                | Type   | Notes                                          |
|-----------------------|--------|------------------------------------------------|
| `auto_order_status`   | str    | One of the categories above.                   |
| `auto_exit_price`     | float  | Virtual exit price in ₹ (final leg close).     |
| `auto_exit_time`      | str    | ISO IST timestamp of the exit candle.          |
| `auto_exit_reason`    | str    | Human-readable narrative.                      |
| `auto_pnl_per_unit`   | float  | ₹ per unit, weighted by 50/50 if TP1 hit.      |
| `mfe`                 | float  | Max favorable excursion = max(high) − entry.   |
| `mae`                 | float  | Max adverse excursion = entry − min(low).      |
| `intrabar_ambiguous`  | bool   | True if SL and TP touched in same candle.      |

### Refusal rules (loud, not silent)

- If `risk_reward.trail_sl_after_tp1` is ON, the replay refuses to
  stamp. It logs `WARNING: outcome_replay skipping <alert_id> — config
  risk_reward.trail_sl_after_tp1 is ON, trailing logic not implemented
  in v1.` Rationale: silently modelling breakeven would be wrong; the
  user has explicitly asked for trailing.
- If the day's candle data isn't complete yet (today before 15:00 IST,
  or broker returned fewer candles than expected), leave `auto_*`
  null. The next sync fills it.

### Idempotency + manual precedence

- Re-running `sync_auto_outcomes_to_parquet` never overwrites a non-null
  `auto_order_status` row. Existing `auto_*` values are preserved.
- Manual columns (`order_status`, `exit_price`, `pnl_rupees`,
  `outcome_remark`, `user_notes`) are untouched in every code path.
- Dedup key: `(timestamp_ist, symbol, strike, option_type)`.

### Candle cache (Phase 7-reusable)

- Location: `data/replay_cache/<date>/<symbol>_<strike>_<option_type>.parquet`
- Format: identical to `BaseFeed.get_5min_candles` output (columns
  `timestamp, open, high, low, close, volume, oi`). Phase 7's backtest
  reads these files directly.
- Cached only for **completed** days. A day is complete iff its IST
  date < today, or it is today and `now >= 15:00 IST`.
- Mid-day Ctrl+C of today's session does **not** populate the cache
  for today. Next sync (post-15:00 or next day) does.
- Cache misses for old alerts (pre-feature) are tolerated — those
  alerts simply have null `auto_*` and the user can still fill the
  manual columns.

### Config toggle

`config/config.yaml` adds:

```yaml
dashboard:
  auto_outcome_tracking: OFF   # ON = replay alerts after EOD and
                               # stamp auto_* columns. OFF (default) =
                               # original Phase 5B manual-only flow.
```

### Wiring

`sync_jsonl_to_parquet` → `sync_auto_outcomes_to_parquet(feed)` →
`update_dashboard` → `sync_excel_notes_to_parquet`. The replay step is
a no-op when the toggle is OFF or no feed is available. Best-effort:
any internal error is logged at warning level and never blocks the
remaining steps.

### Tests

- SL-only → `SL_HIT`.
- TP1 then breakeven SL → `PARTIAL` with ~₹0 P&L on second leg.
- TP1 then TP2 → `TP2_HIT`.
- Neither hit by 15:00 → `EOD_FLAT`.
- Single candle covers both SL and TP → `SL_HIT` + `intrabar_ambiguous`.
- Hard-exit rule on red candle below VWAP → `HARD_EXIT`.
- Idempotent rerun preserves manual cells AND prior auto_* values.
- `trail_sl_after_tp1: ON` → no stamp, warning logged.
