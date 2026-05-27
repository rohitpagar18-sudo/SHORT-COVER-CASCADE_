# PRE-PHASE 5.2 — Read-Only Validation Check
(paste into Claude Code BEFORE running Phase 5.2 final prompt)

This is a sanity check ONLY. Does not modify any files. Just reads
existing state and reports back. Should take 2 minutes.

```cmd
cd C:\trading\short-cover-cascade
claude
```

Paste the entire block below:

````
READ-ONLY VALIDATION CHECK — NO FILES SHOULD BE MODIFIED.
If you find something missing or wrong, REPORT it. Do not fix.

Read CLAUDE.md, then perform these checks and report back:

=========================================================
CHECK 1 — JSONL logs exist and have data
=========================================================

For each: logs/signals.jsonl, logs/alerts.jsonl, logs/gap_log.jsonl,
logs/bot.log, logs/state.json:
  - Exists? (yes/no)
  - Size in KB
  - Line count (for JSONL files)
  - First-line preview (first 150 chars)
  - Last-line preview (first 150 chars)

=========================================================
CHECK 2 — signals.jsonl schema audit
=========================================================

Take the LAST 20 lines of logs/signals.jsonl and report:
  - event_type values seen and their counts
  - Sample of one "scan" record's keys (list them)
  - Sample of one "rejection" record's keys (if any exist)
  - Sample of one "data_issue" record's keys (if any exist)
  - Are timestamps in IST ISO format with "+05:30" timezone? (yes/no)
  - Any anomalies — missing keys, weird values, parse errors?

=========================================================
CHECK 3 — alerts.jsonl content audit
=========================================================

From logs/alerts.jsonl:
  - Total alerts count
  - List each alert as: date, time, symbol, strike, option_type
  - Verify each has all of: entry, sl, tp1, tp2, lots, total_risk
  - Are any alert records missing key fields?

=========================================================
CHECK 4 — gap_log.jsonl content audit
=========================================================

From logs/gap_log.jsonl:
  - Total records (should equal number of trading days bot has run)
  - For each record, pretty-print: date, decision, NIFTY gap_pct, BankNifty gap_pct
  - Confirm "decision" field uses one of: NORMAL, GAP_UP, GAP_DOWN,
    GAP_UP_DISABLED, GAP_DOWN_DISABLED
    (NOTE: if you see "GAP_DAY" or "GAP_DETECTED_BUT_DISABLED", report
    it — those are old labels from before the Phase 5.2 directional fix.
    They'll be migrated by Phase 5.2 retroactively, just confirm presence.)

=========================================================
CHECK 5 — Folder structure audit
=========================================================

List top-level contents of project root.
For each, report exists or not:
  ✓/✗ src/
  ✓/✗ tests/
  ✓/✗ scripts/
  ✓/✗ config/
  ✓/✗ logs/
  ✓/✗ docs/
  ✓/✗ CLAUDE.md
  ✓/✗ run.bat
  ✓/✗ requirements.txt
  ✓/✗ secrets.env (just confirm exists, don't print contents)

Phase 5.2 will create these — confirm they do NOT exist yet:
  ✗ logs/dashboards/   (Phase 5.2 will create)
  ✗ data/              (Phase 5.2 will create)
  ✗ src/dashboard/     (Phase 5.2 will create)

If any of those already exist, REPORT — could mean a previous attempt
left partial state.

=========================================================
CHECK 6 — Required Python packages
=========================================================

Run: pip show openpyxl pyarrow pandas numpy 2>nul

For each, report installed (yes/no) and version. Phase 5.2 requires:
  - openpyxl >= 3.1.0
  - pyarrow >= 14.0.0
  - pandas >= 2.0.0
  - numpy (already in requirements from earlier phases)

If pyarrow missing, note: user must run pip install pyarrow before
Phase 5.2 (or rely on Claude Code adding it to requirements.txt).

=========================================================
CHECK 7 — Config audit
=========================================================

Read config/config.yaml. Print these sections ONLY (DO NOT print
telegram token or chat_id):

  feed.active_broker
  mode (alert_mode, order_place_mode, paper_trade_mode)
  instruments (nifty_enabled, banknifty_enabled, lot sizes)
  time_rules (all fields — confirm gap_day_enabled, gap_day_threshold_pct,
              gap_day_direction exist from Phase 5.1)
  logging.log_every_signal_check
  telegram: just list field names present (no values)

If gap_day fields missing → Phase 5.1 may not have fully applied.
Report so user can fix before Phase 5.2.

=========================================================
CHECK 8 — Indicator config — C1 filter
=========================================================

Read src/conditions/c1_option_above_vwap.py (or wherever C1 lives).
Find the late-entry filter logic. Report:
  - Current threshold (likely hardcoded to 30%)
  - Is it currently configurable via config.yaml? (yes/no)

Phase 5.2 will make this configurable as
config.conditions.c1_max_distance_pct (default 30) — confirm it's not
already configurable to avoid Phase 5.2 duplicating the logic.

=========================================================
CHECK 9 — Test count
=========================================================

Run: pytest tests/ --collect-only -q
Report the total test count. Should be 207 after Phase 5.1.5 hotfix.

=========================================================
CHECK 10 — Today's bot activity (if bot ran today)
=========================================================

From signals.jsonl, filter to today's date and report:
  - Total scan records today
  - Total rejection records today
  - Total data_issue records today
  - Any "Insufficient lookback" errors? (Should be 0 after 5.1.5 hotfix)
  - First scan time, last scan time

From alerts.jsonl, today only:
  - Alert count
  - Symbols breakdown (NIFTY vs BANKNIFTY)
  - Relations breakdown (ITM/ATM/OTM)

=========================================================
REPORT FORMAT
=========================================================

Present everything as a clean checklist:

  ✓ logs/signals.jsonl: exists, 423 lines, last record 2026-05-27 14:30
  ✓ logs/alerts.jsonl: exists, 5 alerts so far
  ✓ logs/gap_log.jsonl: 3 records (one per trading day)
  ✗ logs/dashboards/: not yet (correct — Phase 5.2 creates)
  ✗ data/: not yet (correct — Phase 5.2 creates)
  ✓ openpyxl 3.1.5 installed
  ✗ pyarrow NOT installed — Phase 5.2 will add to requirements.txt
  ✓ pandas 2.1.3 installed
  ✓ 207 tests collected
  ✓ Today: 142 scans, 35 rejections, 0 data_issues, 1 alert
  ✓ Gap decision labels use OLD format (will be migrated by Phase 5.2)

Then end with one of:
  "READY FOR PHASE 5.2 — proceed"
  "ISSUES DETECTED — see above, do not run Phase 5.2 until resolved"
````

After running this check, paste the FULL output back into the chat.
I'll confirm everything is green before you proceed with Phase 5.2.
