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

One file per calendar month, ordered by `timestamp_ist`. Bot events
that cross midnight on the last day of the month still land in the
month indicated by the IST date. Files are pyarrow-compatible; load
with `pd.read_parquet`.

Reading a quarter:

```python
import pandas as pd
import glob

df = pd.concat([pd.read_parquet(f) for f in glob.glob("data/scc_data_2026-0[4-6].parquet")])
```

---

## event_type values

Every row carries an `event_type` column. It is the primary axis you
filter on. Other columns are populated *conditional* on event_type;
see the per-bucket lists below.

| event_type              | When the bot writes it                                        |
|-------------------------|---------------------------------------------------------------|
| `scan`                  | One per closed 5-min candle per strike per scan loop. Full indicator snapshot + condition reasons. Default event_type when none is set in JSONL. |
| `alert`                 | One per 5/5-pass scan. Includes SL/TP/lot math AND `bot_remark` / `bot_tags`. |
| `rejection`             | One per silent rejection (typically a C0 fast-fail on spot/VWAP disagreement, or a re-entry blocker). |
| `data_issue`            | Mid-session start where `get_latest_snapshot()` raised `Insufficient lookback`. Distinguished from rejections so analytics stay clean. |
| `would_alert_extended`  | Phase 5.2: a 4/5 scan where the **only** failing condition is C1 and the option is between `c1_max_distance_pct` (30) and `c1_extended_zone_max_pct` (50) above VWAP. Captures candidates for tuning C1 later. |
| `gap`                   | One per bot startup. Sourced from `gap_log.jsonl`. Holds the directional gap decision, per-symbol gap %, and the toggle state. |

---

## Common columns (every row, every event_type)

| Column          | Type   | Notes                                                            |
|-----------------|--------|------------------------------------------------------------------|
| `timestamp_ist` | str    | ISO 8601 with `+05:30` offset. Always IST. Primary sort key.    |
| `event_type`    | str    | One of the values above.                                         |
| `date`          | str    | `YYYY-MM-DD` derived from timestamp_ist. Convenient for groupby. |
| `month`         | str    | `YYYY-MM`. Used by the writer to pick the target Parquet file.   |
| `symbol`        | str    | `NIFTY` / `BANKNIFTY` / null for gap rows that span both.        |
| `_logged_at`    | str    | Bot's wall-clock when it wrote the JSONL line.                   |
| `is_holiday_scan` | bool | Present only on rows written before the holiday guard existed. True = row recorded on an NSE holiday (no live candles). Exclude in all backtests/ML queries: `df[df.get("is_holiday_scan", False) != True]` |

Rows where the bot didn't have a symbol context (e.g. gap-day startup)
have a null `symbol`. The detail is in `per_symbol_*` columns for gap.

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

### Bot remark columns (alert only — Phase 5.2)

| Column                   | Type | Notes                                              |
|--------------------------|------|----------------------------------------------------|
| `bot_remark`             | str  | Human-readable: "5/5 strong — opt 8% above VWAP, RSI 67 healthy zone, OI 18% below MA, vol 2.1× MA, first alert of day." |
| `bot_tags`               | str  | Comma-separated ML tags, no spaces: `fresh_breakout,strong_rsi,strong_oi,explosive_volume,morning,normal_vix,normal_day,first_alert`. |
| `telegram_short_remark`  | str  | Trimmed for the Telegram alert "Insight:" line. |

### Outcome columns (alert only — populated by user via Excel)

These columns are *back-filled* by `sync_excel_notes_to_parquet`.
On a fresh sync (before the user has filled anything) they are null.

| Column            | Type   | Notes                                                |
|-------------------|--------|------------------------------------------------------|
| `order_status`    | str    | One of `TP2_HIT`, `TP1_HIT`, `SL_HIT`, `PARTIAL`, `WOULD_SKIP` (or null). |
| `exit_price`      | float  | Filled manually in Order Place sheet.                |
| `pnl_rupees`      | float  | Filled manually. Sign convention: positive = profit. |
| `outcome_remark`  | str    | Auto-generated from `bot_remark` + `order_status`.   |
| `user_notes`      | str    | Free-form user observation.                          |

### Auto outcome columns (alert only — Phase 5B-A virtual replay)

Populated by `sync_auto_outcomes_to_parquet`. This is a **post-hoc
virtual** model: the bot does not place orders, but after EOD it
walks each alert's subsequent 5-min option candles and stamps what
would have happened under the strategy doc's exit rules (Section 9).

**Entry-fill assumption:** the virtual position is filled at the
logged `entry` (the alert candle's `option_close`). Slippage is
ignored. This matches the strategy's signal-candle limit-order plan
described in `ShortCoverCascade_v3.1_FINAL.md` Section 11.

The same kernel (`src/dashboard/outcome_replay.replay_exits`) is the
shared exit implementation that Phase 7's backtest harness will call.

These columns NEVER overwrite the manual outcome columns above.
Manual values remain authoritative on conflict.

| Column                | Type   | Notes                                              |
|-----------------------|--------|----------------------------------------------------|
| `auto_order_status`   | str    | One of `TP2_HIT`, `TP1_HIT`, `PARTIAL`, `SL_HIT`, `EOD_FLAT`, `HARD_EXIT`. Null if the day isn't complete yet, candle cache miss, or the trail-SL refusal triggered. |
| `auto_exit_price`     | float  | Virtual exit price (₹). For TP2/TP1 paths it is weighted by the 50/50 split; this column shows the *final-leg* exit price. |
| `auto_exit_time`      | str    | ISO IST timestamp of the candle that produced the exit. |
| `auto_exit_reason`    | str    | Human-readable narrative (e.g. `TP1 then TP2_HIT @ 175.00`). |
| `auto_pnl_per_unit`   | float  | ₹ per unit, summed across both legs at their 50/50 weights. Positive = profit. |
| `mfe`                 | float  | Max favorable excursion = `max(high) − entry` across the walked candles. |
| `mae`                 | float  | Max adverse excursion = `entry − min(low)` across the walked candles. |
| `intrabar_ambiguous`  | bool   | True if at least one candle range covered both a stop and a target. The replay assumes the stop fires first. |

**Refusal:** if `risk_reward.trail_sl_after_tp1` is ON in config, the
replay refuses to stamp (it would otherwise silently model static
breakeven, which misrepresents a trailing strategy). The skipped
alerts log a `WARNING` and keep null `auto_*` columns.

---

## Rejection-only columns (event_type == "rejection")

| Column                | Type | Notes                                                  |
|-----------------------|------|--------------------------------------------------------|
| `strike`              | int  | May be null when rejection happened before strike resolution (e.g. C0 fast-fail). |
| `option_type`         | str  | `CE` / `PE`.                                           |
| `rejection_blocker`   | str  | Which condition / guardrail failed (e.g. `C0`, `RE_ENTRY_BLOCKED`). |
| `rejection_reason`    | str  | One-line human explanation.                            |

---

## Gap-only columns (event_type == "gap")

One row per bot startup. Sourced from `gap_log.jsonl`.

| Column                    | Type   | Notes                                              |
|---------------------------|--------|----------------------------------------------------|
| `decision`                | str    | Phase 5.2: `NORMAL`, `GAP_UP`, `GAP_DOWN`, `GAP_UP_DISABLED`, `GAP_DOWN_DISABLED`. Legacy rows may show `GAP_DAY` or `GAP_DETECTED_BUT_DISABLED`. |
| `enabled`                 | bool   | Gap-day rule toggle at the time of detection.       |
| `threshold_pct`           | float  | The threshold % in force.                           |
| `direction`               | str    | `both` / `up` / `down`.                             |
| `any_triggered`           | bool   | At least one symbol breached threshold.             |
| `nifty_open`              | float  | Today's 09:15 open for NIFTY.                       |
| `nifty_prev_close`        | float  | Previous trading-day close for NIFTY.               |
| `nifty_gap_pct`           | float  | Signed gap percentage for NIFTY.                    |
| `nifty_triggers`          | bool   | NIFTY breached threshold this morning.              |
| `nifty_error`             | str    | Diagnostic if gap math could not be computed.       |
| `banknifty_open`          | float  | Today's 09:15 open for BANKNIFTY.                   |
| `banknifty_prev_close`    | float  | Previous trading-day close for BANKNIFTY.           |
| `banknifty_gap_pct`       | float  | Signed gap percentage for BANKNIFTY.                |
| `banknifty_triggers`      | bool   | BANKNIFTY breached threshold this morning.          |
| `banknifty_error`         | str    | Diagnostic if gap math could not be computed.       |

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

- **Adding a column:** future bot versions are expected to add more
  columns. The writer's `pd.concat` preserves new columns as nulls in
  old rows. Don't rename existing columns; deprecate and add new ones.
- **Adding a new event_type:** the writer accepts any string. Update
  this doc and the Excel builder if the new type warrants its own
  sheet or chart bucket.
- **Removing a column:** never delete. Backfill with null in old
  files so historical Parquet files stay readable.

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
counts = (
    df.groupby(["is_strong", "order_status"])
      .size()
      .unstack(fill_value=0)
)
print(counts)
```

### Cumulative P&L curve (filled outcomes only)

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

---

## Schema versioning

`schema_version` is written on every `scan` (and on every later event
that inherits the scan record) so consumers can guard against drift.

| schema_version | Effective from | What changed                                                        |
|----------------|----------------|---------------------------------------------------------------------|
| 1              | Phase 5 GA     | Original signals.jsonl shape                                        |
| 2              | Phase 5.2      | Added bot_remark / bot_tags / opt_above_vwap_pct / extended-zone    |
| 3              | Phase 6.1      | Added C5 ADX shadow fields (adx / adx_prev / di_plus / di_minus /   |
|                |                | di_aligned / c5_passed / c5_reason / session_candle_index) AND      |
|                |                | option-side DI (option_di_plus / option_di_minus /                  |
|                |                | option_di_aligned — direction-agnostic, +DI>−DI is always desired   |
|                |                | because we always BUY the option). Option DI is informational only  |
|                |                | and does NOT affect C5 pass/fail. Values are explicit `null` when   |
|                |                | c5_adx.enabled is OFF or fewer than 2*period option candles are     |
|                |                | available, so the Parquet pipeline does not choke on schema drift.  |

