# PHASE 5.2 — Strategy Dashboard + ML Data Store + Bot Remarks
(paste into Claude Code AFTER PRE_PHASE_5_2_CHECK reports green)

This is the BIG phase 5.2 prompt. It implements:
1. Quarterly rotating Excel dashboards with charts and KPI tiles
2. Monthly Parquet ML data files (single unified table)
3. Two-pass bot remarks (entry-time + outcome-time) with structured tags
4. Directional gap labels (GAP_UP, GAP_DOWN, etc)
5. Configurable C1 filter with extended-zone logging
6. Outcome cell coloring (green/red/yellow/grey)
7. Best-effort Excel→Parquet notes sync
8. Auto-trigger at 15:35 IST + manual update_dashboard.bat

```cmd
cd C:\trading\short-cover-cascade
claude
```

Paste the entire block below:

````
Read CLAUDE.md fully. Then read src/main.py and src/conditions/ (all
condition files). Check that logs/signals.jsonl, logs/alerts.jsonl,
and logs/gap_log.jsonl exist with data from at least 1 trading day.

Current task: Phase 5.2 — Strategy Dashboard + ML Data + Bot Remarks.

CRITICAL INSTRUCTIONS:
1. If any file already exists, OVERWRITE it.
2. Use load_secrets() helper before load_config() in every entry point.
3. The orchestrator gets ONLY two small changes:
   a. Generate bot_remark + bot_tags at alert time
   b. Auto-trigger dashboard at 15:35 IST
4. Strategy logic is NOT modified. C1 filter is parameterized to use
   config.conditions.c1_max_distance_pct (default 30).
5. All other strategy decisions are LOCKED. Do not change them.

ARCHITECTURE OVERVIEW:

  logs/                                  ← Bot runtime (existing)
    signals.jsonl, alerts.jsonl, gap_log.jsonl, bot.log
    dashboards/                          ← NEW — quarterly Excel files
      dashboard_2026_Q2.xlsx
      dashboard_2026_Q3.xlsx

  data/                                  ← NEW — ML/backtest store
    schema.md                            ← Column documentation
    scc_data_2026-05.parquet             ← One unified file per month
    scc_data_2026-06.parquet

  src/dashboard/                         ← NEW — dashboard module
    __init__.py
    data_writer.py                       ← JSONL → Parquet + Excel notes back
    excel_builder.py                     ← Parquet → quarterly .xlsx
    remarks.py                           ← Generate bot_remark + bot_tags

DATA FLOW:

  Bot runs all day → writes raw JSONL
        ↓
  [15:35 auto OR manual update_dashboard.bat]
        ↓
  data_writer.sync_jsonl_to_parquet() → data/scc_data_YYYY-MM.parquet
        ↓
  excel_builder.update_dashboard() → logs/dashboards/dashboard_YYYY_QN.xlsx
        ↓
  data_writer.sync_excel_notes_to_parquet() → back-fill outcome columns

KEY DESIGN PRINCIPLES:
1. Quarterly Excel rotation, monthly Parquet files
2. Idempotent: run twice → 0 new rows
3. Manual columns in Order Place sheet preserved across runs
4. Excel-not-found never crashes the bot — sync is best-effort
5. event_type column distinguishes scan / alert / rejection / gap /
   data_issue / would_alert_extended
6. Bot writes BOTH human-readable remark AND structured tags

=========================================================
--- TASK 0: Update CLAUDE.md ---
=========================================================

Add a new section "Phase 5.2 Decisions" to CLAUDE.md after the
existing "Strategy Decisions Locked In (Phases 0-4)" section:

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

### Update Triggers
- Auto: orchestrator calls dashboard sync at 15:35 IST after EOD
- Manual: update_dashboard.bat anytime
- Sync is idempotent and best-effort (never blocks bot runtime)

=========================================================
--- TASK 1: Update requirements.txt ---
=========================================================

Add (preserve existing entries):
openpyxl>=3.1.0
pyarrow>=14.0.0
pandas>=2.0.0

=========================================================
--- TASK 2: Update config/config.yaml ---
=========================================================

Add a new "conditions" section (or update if exists):

conditions:
  c1_max_distance_pct: 30   # Reject alerts where opt >30% above own VWAP
                            # Default 30% per strategy doc.
                            # Strikes 30-50% above VWAP logged for analysis
                            # but do NOT fire alerts.
  c1_extended_zone_enabled: true  # Log "would_alert_extended" scans
  c1_extended_zone_max_pct: 50    # Upper bound for extended zone logging

Add to "logging" section:
  log_extended_zone: true   # Write would_alert_extended events

Add a new "dashboard" section:

dashboard:
  auto_trigger_at_1535: true       # Auto-sync at 15:35 IST after EOD
  excel_rotation: "quarterly"      # Excel files rotate per quarter
  parquet_rotation: "monthly"      # Parquet files split monthly
  send_eod_dashboard_link: false   # Future: Telegram link to .xlsx
  
  # Outcome categories user can mark in Excel Order Place sheet
  outcome_categories:
    - TP2_HIT
    - TP1_HIT
    - SL_HIT
    - PARTIAL
    - WOULD_SKIP

=========================================================
--- TASK 3: Update C1 condition to use config ---
=========================================================

Open src/conditions/c1_option_above_vwap.py (or wherever C1 lives).

The current implementation likely hardcodes the 30% filter. Change to:

def check_c1(option_close, option_vwap, is_green, config):
    """
    C1: Option price above its own VWAP on green candle, with
    configurable late-entry filter (default 30%).
    
    Returns:
        (passed: bool, reason: str, opt_above_vwap_pct: float)
    """
    if option_vwap <= 0:
        return False, "VWAP not yet available", 0.0
    
    opt_above_vwap_pct = ((option_close - option_vwap) / option_vwap) * 100
    
    # Must be green and above VWAP
    if not is_green:
        return False, f"candle not green", opt_above_vwap_pct
    if option_close <= option_vwap:
        return False, f"opt {option_close:.2f} not above VWAP {option_vwap:.2f}", opt_above_vwap_pct
    
    # Late-entry filter
    max_pct = config.conditions.c1_max_distance_pct
    if opt_above_vwap_pct > max_pct:
        return False, f"late entry: opt {opt_above_vwap_pct:.1f}% above VWAP (max {max_pct}%)", opt_above_vwap_pct
    
    return True, f"opt {opt_above_vwap_pct:.1f}% above VWAP, green ✓", opt_above_vwap_pct

The orchestrator must capture opt_above_vwap_pct from this return and
include it in the signal record. See TASK 6.

=========================================================
--- TASK 4: Create src/dashboard/remarks.py ---
=========================================================

Bot remark + tag generation. Pure functions — no I/O.

from typing import Dict, List, Tuple


# Threshold maps for tag generation
def _vwap_zone(opt_above_vwap_pct: float) -> Tuple[str, str]:
    """Returns (tag, human_phrase)."""
    p = opt_above_vwap_pct
    if p < 10: return ("fresh_breakout", f"opt {p:.0f}% above VWAP (fresh)")
    if p < 20: return ("clean_entry", f"opt {p:.0f}% above VWAP")
    if p < 25: return ("mid_entry", f"opt {p:.0f}% above VWAP (mid-zone)")
    return ("late_entry", f"opt {p:.0f}% above VWAP (near filter)")


def _rsi_zone(rsi: float) -> Tuple[str, str]:
    if rsi < 55: return ("low_rsi", f"RSI {rsi:.0f} early momentum")
    if rsi < 65: return ("moderate_rsi", f"RSI {rsi:.0f} moderate")
    if rsi < 75: return ("strong_rsi", f"RSI {rsi:.0f} healthy zone")
    return ("high_rsi", f"RSI {rsi:.0f} high momentum")


def _oi_strength(oi: float, oi_ma: float) -> Tuple[str, str]:
    if oi_ma <= 0: return ("oi_unknown", "OI data unclear")
    pct_below = ((oi_ma - oi) / oi_ma) * 100
    if pct_below > 15: return ("strong_oi", f"OI {pct_below:.0f}% below MA (strong cover)")
    if pct_below > 8: return ("moderate_oi", f"OI {pct_below:.0f}% below MA")
    if pct_below > 0: return ("weak_oi", f"OI {pct_below:.0f}% below MA (marginal)")
    return ("no_oi_signal", "OI not below MA — C2 should not have passed")


def _volume_strength(volume: float, volume_ma: float) -> Tuple[str, str]:
    if volume_ma <= 0: return ("vol_unknown", "vol data unclear")
    ratio = volume / volume_ma
    if ratio > 2.0: return ("explosive_volume", f"vol {ratio:.1f}× MA (explosive)")
    if ratio > 1.5: return ("high_volume", f"vol {ratio:.1f}× MA")
    if ratio > 1.2: return ("moderate_volume", f"vol {ratio:.1f}× MA")
    return ("low_volume", f"vol {ratio:.1f}× MA (marginal)")


def _time_zone(time_hhmm: str) -> Tuple[str, str]:
    h, m = int(time_hhmm[:2]), int(time_hhmm[3:5])
    minutes = h * 60 + m
    if minutes < 600:    return ("opening", "opening hour")
    if minutes < 660:    return ("morning", "morning push")
    if minutes < 720:    return ("mid_morning", "mid-morning")
    if minutes < 780:    return ("lunch", "lunch session")
    if minutes < 840:    return ("early_afternoon", "early afternoon")
    return ("afternoon", "afternoon")


def _vix_context(vix_regime: str) -> Tuple[str, str]:
    m = {"LOW": ("low_vix", "LOW VIX (0.85× SL)"),
         "NORMAL": ("normal_vix", ""),
         "ELEVATED": ("elevated_vix", "ELEVATED VIX (1.25× SL)"),
         "HIGH": ("high_vix", "HIGH VIX (1.5× SL)")}
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


def generate_remark_and_tags(snapshot: dict, context: dict) -> Tuple[str, str]:
    """
    Generates the entry-time bot_remark (human-readable, 3-5 clauses,
    ~25 words) and bot_tags (comma-separated for ML).
    
    snapshot must contain: option_close, option_vwap, rsi, rsi_ma,
                          oi, oi_ma, volume, volume_ma, opt_above_vwap_pct
    context must contain:  time_hhmm, vix_regime, is_expiry_day,
                          daily_sl_count, daily_alert_count
    """
    # Gather all observations
    observations = []
    tags = []
    
    # 1. VWAP zone (always include)
    t, p = _vwap_zone(snapshot["opt_above_vwap_pct"])
    tags.append(t); observations.append(p)
    
    # 2. RSI zone (always include)
    t, p = _rsi_zone(snapshot["rsi"])
    tags.append(t); observations.append(p)
    
    # 3. OI strength
    t, p = _oi_strength(snapshot["oi"], snapshot["oi_ma"])
    tags.append(t); observations.append(p)
    
    # 4. Volume strength
    t, p = _volume_strength(snapshot["volume"], snapshot["volume_ma"])
    tags.append(t); observations.append(p)
    
    # 5. Time of day
    t, p = _time_zone(context["time_hhmm"])
    tags.append(t)
    if p: observations.append(p)
    
    # 6. VIX context (only mention if non-normal)
    t, p = _vix_context(context.get("vix_regime", "NORMAL"))
    tags.append(t)
    if p: observations.append(p)
    
    # 7. Expiry context
    t, p = _expiry_context(context.get("is_expiry_day", False))
    tags.append(t)
    if p: observations.append(p)
    
    # 8. Sequence context
    t, p = _sequence_context(
        context.get("daily_sl_count", 0),
        context.get("daily_alert_count", 0),
    )
    tags.append(t); observations.append(p)
    
    # Choose verdict prefix based on overall quality
    verdict = _verdict(snapshot, observations)
    
    # Limit observations to 3-5 most important for readability
    # Always include: vwap_zone, rsi_zone, oi_strength, volume_strength
    # Then 1-2 contextual: time/vix/expiry/sequence based on relevance
    primary = observations[:4]
    secondary = [o for o in observations[4:] if o][:1]
    
    remark = f"{verdict} — " + ", ".join(primary + secondary) + "."
    return remark, ",".join(tags)


def _verdict(snapshot: dict, observations: List[str]) -> str:
    """Short quality verdict prefix."""
    p = snapshot["opt_above_vwap_pct"]
    rsi = snapshot["rsi"]
    oi_ratio = snapshot["oi"] / snapshot["oi_ma"] if snapshot["oi_ma"] > 0 else 1.0
    vol_ratio = snapshot["volume"] / snapshot["volume_ma"] if snapshot["volume_ma"] > 0 else 1.0
    
    # Strong: all signals firm
    strong = (
        p < 15 and 60 <= rsi < 75 and oi_ratio < 0.85 and vol_ratio > 1.5
    )
    if strong:
        return "5/5 strong"
    
    # Marginal: borderline values
    marginal = (
        rsi < 55 or oi_ratio > 0.93 or vol_ratio < 1.2 or p > 22
    )
    if marginal:
        return "5/5 borderline"
    
    return "5/5 clean"


def generate_outcome_remark(alert_data: dict, outcome: str,
                            exit_price: float = None,
                            pnl: float = None) -> str:
    """
    Generate the outcome remark based on alert quality + outcome.
    Called after user marks Order Status in Excel.
    """
    entry = alert_data.get("entry", 0)
    sl = alert_data.get("sl", 0)
    tp1 = alert_data.get("tp1", 0)
    tp2 = alert_data.get("tp2", 0)
    bot_remark = alert_data.get("bot_remark", "")
    is_strong = "strong" in bot_remark
    is_marginal = "borderline" in bot_remark
    
    if outcome == "TP2_HIT":
        if is_strong:
            return f"Held to TP2 (₹{exit_price:.2f}) — strong setup played out. 2.5R captured."
        return f"Held to TP2 (₹{exit_price:.2f}) — 2.5R captured. Outcome confirmed setup."
    elif outcome == "TP1_HIT":
        return f"TP1 hit at ₹{exit_price:.2f} — 1.5R captured. Reversed before TP2."
    elif outcome == "SL_HIT":
        if is_strong:
            return f"SL hit at ₹{exit_price:.2f} — unusual reversal on strong setup."
        if is_marginal:
            return f"SL hit at ₹{exit_price:.2f} — marginal entry showed in outcome."
        return f"SL hit at ₹{exit_price:.2f} — reversed quickly."
    elif outcome == "WOULD_SKIP":
        return "Skipped post-review — your judgement overrode 5/5."
    elif outcome == "PARTIAL":
        return f"Partial exit — manual decision, P&L ₹{pnl:.0f}."
    return ""


def telegram_short_remark(bot_remark: str) -> str:
    """
    Extract the verdict + 1 key observation for Telegram alert.
    Example input:  "5/5 strong — RSI 67 healthy zone, OI 18% below MA, vol 2× MA..."
    Example output: "5/5 strong — RSI 67, OI 18% below MA"
    """
    if not bot_remark: return ""
    parts = bot_remark.split(" — ", 1)
    if len(parts) < 2: return bot_remark[:80]
    verdict, rest = parts
    obs = rest.split(", ")
    if len(obs) >= 2:
        return f"{verdict} — {obs[0]}, {obs[1]}"
    return f"{verdict} — {obs[0]}" if obs else verdict

=========================================================
--- TASK 5: Update orchestrator to generate remarks ---
=========================================================

In src/main.py, in the _fire_alert method, AFTER computing SL/TP/lots
but BEFORE log_alert / send_signal, generate the remark and tags.

Add an import at the top:
from src.dashboard.remarks import generate_remark_and_tags, telegram_short_remark

In _fire_alert, after computing alert_data:

# Generate bot remark + tags
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
    "opt_above_vwap_pct": signal_record.get("opt_above_vwap_pct", 0),
}
bot_remark, bot_tags = generate_remark_and_tags(snapshot_dict, context)

alert_data["bot_remark"] = bot_remark
alert_data["bot_tags"] = bot_tags

# Compute Telegram short remark
telegram_short = telegram_short_remark(bot_remark)
alert_data["telegram_short_remark"] = telegram_short

Then in TelegramAlerter._format_signal, ADD a line above "C0 ✓ C1 ✓..." showing:
    Insight: {telegram_short}

=========================================================
--- TASK 6: Update _scan_strike to log opt_above_vwap_pct ---
=========================================================

C1 now returns (passed, reason, opt_above_vwap_pct). Update the
condition orchestration in src/conditions/all_conditions.py if it
doesn't already pass through the third value.

In _scan_strike of orchestrator, after calling check_all_conditions,
extract opt_above_vwap_pct from the result and add to signal_record:

signal_record["opt_above_vwap_pct"] = result.opt_above_vwap_pct  # or similar

ALSO ADD: handle the extended zone. If the option is between c1_max_distance_pct
(30) and c1_extended_zone_max_pct (50), and all OTHER conditions pass,
log this as event_type="would_alert_extended" — do NOT fire alert.

This requires re-checking conditions with a "what if c1 max were 50%":

# After normal check_all_conditions:
if (not result.all_passed 
    and self.config.logging.log_extended_zone
    and signal_record.get("opt_above_vwap_pct", 0) > self.config.conditions.c1_max_distance_pct
    and signal_record.get("opt_above_vwap_pct", 100) <= self.config.conditions.c1_extended_zone_max_pct):
    # Check if all OTHER conditions would pass
    failed_only_c1 = result.failed_conditions() == ["C1"]
    if failed_only_c1:
        extended_record = dict(signal_record)
        extended_record["event_type"] = "would_alert_extended"
        self.signal_logger.log_signal(extended_record)

=========================================================
--- TASK 7: Update gap detection labels (directional) ---
=========================================================

Open src/main.py, find _detect_gap_day().

The current "decision" field returns NORMAL / GAP_DAY /
GAP_DETECTED_BUT_DISABLED. Replace with directional labels:

  - NORMAL: no symbol breached threshold
  - GAP_UP: any symbol's signed gap_pct >= +threshold, enabled
  - GAP_DOWN: any symbol's signed gap_pct <= -threshold, enabled
  - GAP_UP_DISABLED: same as GAP_UP but rule OFF
  - GAP_DOWN_DISABLED: same as GAP_DOWN but rule OFF

Logic:
  enabled = config.time_rules.gap_day_enabled
  threshold = config.time_rules.gap_day_threshold_pct
  
  any_up = any positive gap >= threshold
  any_down = any negative gap <= -threshold
  
  if any_up and enabled:    decision = "GAP_UP"
  elif any_down and enabled: decision = "GAP_DOWN"
  elif any_up:               decision = "GAP_UP_DISABLED"
  elif any_down:             decision = "GAP_DOWN_DISABLED"
  else:                      decision = "NORMAL"
  
  is_gap_day = decision in ("GAP_UP", "GAP_DOWN")

Update _format_gap_line in src/alerts/telegram_bot.py to handle the
new directional labels. Show:
  "✓ Normal day — 9:45 start" for NORMAL
  "⚠️ GAP UP — 10:15 start" for GAP_UP
  "⚠️ GAP DOWN — 10:15 start" for GAP_DOWN
  "⚠ GAP UP detected (rule OFF) — 9:45 start" for GAP_UP_DISABLED
  "⚠ GAP DOWN detected (rule OFF) — 9:45 start" for GAP_DOWN_DISABLED

=========================================================
--- TASK 8: Create data/schema.md ---
=========================================================

Create data/schema.md documenting the unified Parquet schema.
Include sections:
  - File naming convention
  - event_type values and their meaning
  - Common columns (always populated)
  - Indicator columns (scan, alert, would_alert_extended)
  - Condition columns (with reasons)
  - Alert-only columns (SL/TP/risk)
  - Bot remark columns (bot_remark, bot_tags)
  - Outcome columns (manual fill from Excel)
  - Rejection-only columns
  - Gap-only columns
  - data_issue-only columns
  - Forward compatibility notes
  - Example pandas queries

Be thorough — this is the document the user will read in 2027 when
they want to do ML and need to understand the columns.

=========================================================
--- TASK 9: Create src/dashboard/data_writer.py ---
=========================================================

Functions:
  - sync_jsonl_to_parquet() → reads all JSONL, writes new rows to
    monthly Parquet files. Idempotent.
  - sync_excel_notes_to_parquet() → best-effort reads Order Place
    sheet manual columns, writes outcome_* cols back to Parquet.
    Silently skips on any error.

Use the implementation outline from the previous version of this prompt
but ALSO handle the new event_types:
  - "scan" (default for signals)
  - "rejection"
  - "data_issue"
  - "would_alert_extended"
  - "alert"
  - "gap"

Each event type has its specific columns — see schema.md.

Monthly file: data/scc_data_YYYY-MM.parquet
Dedup key: (timestamp_ist, event_type, symbol, strike, option_type)

Note: this file is large. Implement carefully with all event_type
handling. Use the previous Phase 5.2 attempt as base reference.

=========================================================
--- TASK 10: Create src/dashboard/excel_builder.py ---
=========================================================

Functions:
  - update_dashboard() → reads Parquet, writes to current quarter's
    Excel file. Idempotent.
  - _resolve_excel_path(date) → returns logs/dashboards/dashboard_YYYY_QN.xlsx
    where Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec.

Sheets in order:
1. Strategy Dashboard — KPI tiles + 4 charts (bar/line)
2. Daily Summary — one row per day with new directional gap label
3. All Alerts — includes opt_above_vwap_pct, bot_remark, bot_tags
4. Order Place — auto cols + manual cols, OUTCOME CELL COLORING
5. All Signals — full scan audit, includes would_alert_extended in orange
6. Rejections — grouped by blocker
7. Gap History — directional labels with colors
8. Config Snapshot — current config values for this quarter

For Strategy Dashboard sheet:
- KPI tiles built from Parquet aggregates
- 4 charts using openpyxl BarChart / LineChart:
  a. Wins vs Losses by Strike Relation
  b. Alerts by VIX Regime
  c. Alerts by Time of Day (30-min buckets)
  d. Cumulative P&L line chart
- All values computed from data — refreshed each update

For Order Place sheet outcome coloring:
- Color the "Order Status" cell based on its value
- Color the P&L cell green for positive, red for negative
- Bot Remark column is read-only (auto-generated)
- Outcome Remark column is read-only (auto-generated when status filled)
- User Notes column is manual

For All Signals sheet:
- All-passed rows highlighted yellow
- would_alert_extended rows highlighted light orange
- Regular scan rows colored by Relation/Symbol

For Gap History sheet:
- Decision cell colored by directional label:
  GAP_UP → light red, GAP_DOWN → light blue
  GAP_UP_DISABLED → orange, GAP_DOWN_DISABLED → light blue
  NORMAL → no color

Quarter rotation:
- Always write to current quarter's file based on data dates
- If data spans multiple quarters, write to each quarter's file
- Never modify a closed quarter once a new one starts

=========================================================
--- TASK 11: Create src/dashboard/__init__.py ---
=========================================================

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

=========================================================
--- TASK 12: Create scripts/update_dashboard.py ---
=========================================================

Manual entry point. Same as previous version but logs to console which
quarter's file was updated.

#!/usr/bin/env python
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config_loader import load_secrets
from src.dashboard import (
    sync_jsonl_to_parquet,
    sync_excel_notes_to_parquet,
    update_dashboard,
)

IST = ZoneInfo("Asia/Kolkata")

def main():
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
    print(f"  Human review: logs/dashboards/")
    print(f"  ML/backtest:  data/")

if __name__ == "__main__":
    main()

=========================================================
--- TASK 13: Create update_dashboard.bat ---
=========================================================

@echo off
call venv\Scripts\activate.bat
echo Updating dashboard + Parquet...
python scripts\update_dashboard.py
echo.
pause

=========================================================
--- TASK 14: Wire 15:35 auto-trigger ---
=========================================================

In src/main.py:

1. Add to Orchestrator __init__:
   self.dashboard_synced = False

2. In run_forever() main loop, AFTER the eod_sent block:

   # Auto-trigger dashboard at 15:35 IST
   if (self.config.dashboard.auto_trigger_at_1535
       and not self.dashboard_synced
       and now.time() >= dt_time(15, 35)
       and now.weekday() < 5):
       try:
           logger.info("Auto-triggering dashboard update at 15:35")
           from src.dashboard import (
               sync_jsonl_to_parquet,
               sync_excel_notes_to_parquet,
               update_dashboard,
           )
           sync_jsonl_to_parquet()
           update_dashboard()
           sync_excel_notes_to_parquet()
           self.dashboard_synced = True
           logger.info("Dashboard auto-update complete")
       except Exception as e:
           logger.exception(f"Dashboard auto-update failed: {e}")
           try:
               self.telegram.send_exception(f"Dashboard update failed:\n{e}")
           except Exception:
               pass
           self.dashboard_synced = True  # prevent retry storm

=========================================================
--- TASK 15: Update .gitignore ---
=========================================================

Add (preserve existing entries):

# Dashboard outputs (regenerable from JSONL)
logs/dashboards/
data/scc_data_*.parquet

# But keep schema documentation
!data/schema.md

=========================================================
--- TASK 16: Unit tests ---
=========================================================

Create tests/test_dashboard_remarks.py (~15 tests):
  - test_fresh_breakout_tag_under_10pct()
  - test_late_entry_tag_above_22pct()
  - test_strong_rsi_tag_60_to_74()
  - test_strong_oi_tag_above_15pct_below_ma()
  - test_explosive_volume_tag_above_2x()
  - test_verdict_strong_when_all_signals_firm()
  - test_verdict_borderline_when_any_marginal()
  - test_remark_length_under_30_words()
  - test_remark_contains_verdict_prefix()
  - test_tags_comma_separated_no_spaces()
  - test_telegram_short_remark_under_80_chars()
  - test_outcome_remark_tp2_for_strong_setup()
  - test_outcome_remark_sl_for_marginal_setup()
  - test_first_alert_tag_when_count_zero()
  - test_after_sl_tag_when_sl_count_positive()

Create tests/test_dashboard_data_writer.py (~15 tests):
  - All event_types handled
  - Idempotent
  - Monthly split
  - Excel notes best-effort

Create tests/test_dashboard_excel_builder.py (~15 tests):
  - Quarterly path resolution
  - All 8 sheets created
  - Idempotent
  - Charts present on Strategy Dashboard
  - Outcome coloring applied

Create tests/test_c1_extended_zone.py (~8 tests):
  - C1 config threshold respected
  - opt_above_vwap_pct returned correctly
  - would_alert_extended logged when only C1 fails
  - extended zone disabled when toggle off

Create tests/test_directional_gap.py (~6 tests):
  - GAP_UP returned for positive breach when enabled
  - GAP_DOWN returned for negative breach when enabled
  - GAP_UP_DISABLED when toggle off
  - NORMAL when below threshold

Run: pytest tests/ -v
Target: previous 207 + ~60 new = 267 tests passing.

=========================================================
--- TASK 17: Report ---
=========================================================

After completing everything, report:
1. Updated pytest count (target ~267)
2. Confirm logs/dashboards/dashboard_2026_Q2.xlsx was created
3. Sheet names in order (should be 8 sheets, Strategy Dashboard first)
4. Confirm data/scc_data_2026-05.parquet was created
5. data/schema.md exists and is documented
6. Sample bot_remark from a real alert (paste verbatim)
7. Sample bot_tags from a real alert (paste verbatim)
8. Confirm gap labels use directional format (GAP_UP / GAP_DOWN / etc)
9. Idempotency check: run scripts/update_dashboard.py twice.
   Report 0 new rows on second run.
10. Confirm C1 filter now reads from config.conditions.c1_max_distance_pct
11. Confirm orchestrator auto-trigger at 15:35 is wired
12. Confirm Telegram alert now includes "Insight:" line with short remark
````

After Phase 5.2 verifies, you have your full setup. Then Phase 6 begins:
30 trading days of running the bot, reviewing the dashboard each evening,
filling Order Place notes when you want.
