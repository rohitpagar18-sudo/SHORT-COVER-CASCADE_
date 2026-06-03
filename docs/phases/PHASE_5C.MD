# Phase 5C — Holiday Guard Cleanup Utilities

**Goal:** Retroactively tag JSONL rows written during NSE holidays and
add a VIX second-source confirmation that prevents the holiday detector
from mis-firing on broker connectivity glitches.

The market-status detection itself (`MarketStatus` enum,
`_check_market_status()`, `_confirm_holiday_via_vix()`, `holiday_abort`
gate in `setup()` / `scan_once()` / `run_forever()`) lives in
`PHASE_5A.md`. This document covers the downstream cleanup tools and
the `is_holiday_scan` schema column.

## What's in this phase

1. `scripts/mark_holiday_scans.py` — idempotent script that tags
   JSONL rows written during holiday runs with `is_holiday_scan=True`
2. `is_holiday_scan` column added to `data/schema.md`
3. Unit tests for the holiday guard (`_check_market_status()`,
   `scan_once()` gating, mark script)
4. VIX second-source confirmation tests (supplement to 5A test list)

## What this phase does NOT do

- No changes to main orchestrator logic (that's Phase 5A)
- No backtest harness (Phase 7)
- No new strategy conditions

---

## STEP 1 — `scripts/mark_holiday_scans.py`

Idempotent retroactive tagger. Detects holiday-run dates by looking for
`today_n=0` evidence in `gap_log.jsonl` (the bot wrote this pattern
before the holiday guard existed). Adds `is_holiday_scan=True` to all
matching rows in `signals.jsonl` and `alerts.jsonl`. Run BEFORE
`update_dashboard.bat` to keep holiday rows out of backtest queries.

```python
"""Retroactively tags rows in signals.jsonl and alerts.jsonl that were
written during NSE holidays. Idempotent. Run BEFORE update_dashboard.bat.

Evidence: gap_log.jsonl rows where any per_symbol error contains
'today_n=0' identify holiday-run dates.

Usage: python scripts/mark_holiday_scans.py
"""

import json
from pathlib import Path


def _holiday_dates_from_gap_log(p: Path) -> set[str]:
    out: set[str] = set()
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        per_sym = row.get("per_symbol") or {}
        zero_today = any(
            "today_n=0" in str(s.get("error", ""))
            for s in per_sym.values()
            if isinstance(s, dict)
        )
        if zero_today:
            date_str = str(row.get("timestamp_ist", ""))[:10]
            if date_str:
                out.add(date_str)
    return out


def _mark_file(path: Path, holiday_dates: set[str]) -> int:
    if not path.exists():
        return 0
    new_lines: list[str] = []
    marked = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue
        row_date = str(row.get("timestamp_ist", ""))[:10]
        if row_date in holiday_dates and not row.get("is_holiday_scan"):
            row["is_holiday_scan"] = True
            marked += 1
        new_lines.append(json.dumps(row, ensure_ascii=False))

    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    return marked


def main() -> None:
    gap = Path("logs/gap_log.jsonl")
    holiday_dates = _holiday_dates_from_gap_log(gap)

    if not holiday_dates:
        print("No holiday-run dates detected in gap_log.jsonl.")
        return

    print(f"Holiday dates: {sorted(holiday_dates)}")

    total = 0
    for filename in ("logs/signals.jsonl", "logs/alerts.jsonl"):
        path = Path(filename)
        n = _mark_file(path, holiday_dates)
        if n:
            print(f"  {filename}: marked {n} rows with is_holiday_scan=True")
        else:
            print(f"  {filename}: 0 rows to mark")
        total += n

    if total:
        print(f"\nTotal: {total} rows marked. Next: run update_dashboard.bat")
    else:
        print("Nothing to mark (all rows already tagged or no matching rows).")


if __name__ == "__main__":
    main()
```

---

## STEP 2 — `data/schema.md` update

Add one row to the **Common columns** table:

| Column              | Type | Notes                                                      |
|---------------------|------|------------------------------------------------------------|
| `is_holiday_scan`   | bool | Present only on rows written before the holiday guard existed. `True` = row recorded on an NSE holiday (no live candles). Exclude from all backtests/ML queries: `df[df.get("is_holiday_scan", False) != True]` |

---

## STEP 3 — Unit tests

### `tests/test_orchestrator.py` — holiday guard additions

These supplement the existing `test_orchestrator.py` tests. The VIX
confirmation tests are listed separately below.

**Helpers (add near the top of the test file):**

```python
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

IST = ZoneInfo("Asia/Kolkata")


def _make_candles(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.to_datetime(dates).tz_localize("Asia/Kolkata"),
        "open":   [100.0] * len(dates),
        "high":   [101.0] * len(dates),
        "low":    [99.0]  * len(dates),
        "close":  [100.5] * len(dates),
        "volume": [1000]  * len(dates),
        "oi":     [500000]* len(dates),
    })


def _orch_with_mocked_now(mocker, now_iso: str):
    from src.main import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.market_status = None
    orch.holiday_abort = False
    orch.feed = MagicMock()
    fixed_now = datetime.fromisoformat(now_iso).replace(tzinfo=IST)
    mocker.patch("src.main.datetime").now.return_value = fixed_now
    return orch, fixed_now
```

**Tests — `_check_market_status()` decision tree:**

```
test_market_status_saturday_returns_weekend
    now = "2026-05-30 11:00" (Saturday)
    assert result.status.value == "weekend"
    assert feed.get_5min_candles.not_called()

test_market_status_sunday_returns_weekend
    now = "2026-05-31 11:00" (Sunday)
    assert result.status.value == "weekend"

test_market_status_before_0915_returns_pre_open
    now = "2026-05-29 08:45" (Friday)
    assert result.status.value == "pre_open"
    assert feed.get_5min_candles.not_called()

test_market_status_no_today_candles_after_0930_returns_holiday
    now = "2026-05-28 10:00"
    candles = prior day only (2026-05-27 rows)
    assert result.status.value == "holiday"
    assert result.today_candle_count == 0

test_market_status_today_candles_present_returns_open
    now = "2026-05-29 10:30"
    candles = 3 rows with 2026-05-29 timestamps
    assert result.status.value == "open"
    assert result.today_candle_count == 3

test_market_status_no_candles_before_0930_returns_pre_open
    now = "2026-05-29 09:20"
    candles = prior day only
    assert result.status.value == "pre_open"

test_market_status_api_error_returns_unknown_not_holiday
    now = "2026-05-29 10:30"
    get_5min_candles raises RuntimeError("Kite timeout")
    assert result.status.value == "unknown"
    assert "API error" in result.reason or "timeout" in result.reason.lower()
```

**Test — `scan_once()` gating:**

```
test_scan_once_returns_immediately_when_holiday_abort_true
    orch.holiday_abort = True
    call orch.scan_once()
    assert feed.get_5min_candles.not_called()
    assert signal_logger.log_signal.not_called()
    assert signal_logger.log_alert.not_called()
```

**Tests — VIX second-source confirmation (supplement to 5A list):**

```
test_holiday_confirmed_when_both_candles_and_vix_stale
    candle check → HOLIDAY; VIX timestamp 120 min old
    assert result.status == HOLIDAY
    assert "VIX confirms" in result.reason

test_holiday_overridden_when_vix_is_fresh
    candle check → HOLIDAY; VIX timestamp 2 min old
    assert result.status == UNKNOWN
    assert "VIX fresh" or "VIX updated" in result.reason
    assert orch.holiday_abort is False

test_vix_check_skipped_when_first_check_is_open
    candle check → OPEN
    assert feed.get_india_vix_with_timestamp.not_called()

test_vix_check_failure_defaults_to_trusting_first_check
    candle check → HOLIDAY; get_india_vix_with_timestamp raises
    assert result.status == HOLIDAY
    assert "errored" in result.reason

test_vix_check_no_timestamp_field_defaults_to_holiday
    candle check → HOLIDAY; get_india_vix_with_timestamp returns (13.1, None)
    assert result.status == HOLIDAY
    assert "VIX timestamp unavailable" in result.reason
```

### `tests/test_mark_holiday_scans.py`

```python
import json
import os
from pathlib import Path

import pytest


def _write_gap_log(logs: Path, has_holiday: bool) -> None:
    gap = logs / "gap_log.jsonl"
    if has_holiday:
        gap.write_text(json.dumps({
            "timestamp_ist": "2026-05-28T09:16:00+05:30",
            "per_symbol": {
                "NIFTY": {"error": "insufficient_data: today_n=0, prev_n=5"},
                "BANKNIFTY": {"error": "insufficient_data: today_n=0, prev_n=5"},
            },
        }) + "\n")
    else:
        gap.write_text(json.dumps({
            "timestamp_ist": "2026-05-27T09:16:00+05:30",
            "per_symbol": {"NIFTY": {"gap_pct": 0.3, "triggers": False}},
        }) + "\n")


def _run_script(tmp_path: Path) -> None:
    from scripts.mark_holiday_scans import main as mark_main
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        mark_main()
    finally:
        os.chdir(cwd)


def test_mark_holiday_scans_marks_correct_dates(tmp_path):
    logs = tmp_path / "logs"; logs.mkdir()
    _write_gap_log(logs, has_holiday=True)
    sig = logs / "signals.jsonl"
    sig.write_text(
        json.dumps({"timestamp_ist": "2026-05-28T10:00:00+05:30", "symbol": "NIFTY"}) + "\n" +
        json.dumps({"timestamp_ist": "2026-05-27T10:00:00+05:30", "symbol": "NIFTY"}) + "\n"
    )

    _run_script(tmp_path)

    lines = [json.loads(l) for l in sig.read_text().splitlines() if l.strip()]
    holiday_row = next(r for r in lines if r["timestamp_ist"].startswith("2026-05-28"))
    normal_row  = next(r for r in lines if r["timestamp_ist"].startswith("2026-05-27"))
    assert holiday_row.get("is_holiday_scan") is True
    assert "is_holiday_scan" not in normal_row


def test_mark_holiday_scans_idempotent(tmp_path):
    logs = tmp_path / "logs"; logs.mkdir()
    _write_gap_log(logs, has_holiday=True)
    sig = logs / "signals.jsonl"
    sig.write_text(json.dumps({"timestamp_ist": "2026-05-28T10:00:00+05:30"}) + "\n")

    _run_script(tmp_path)
    first_state = sig.read_text()
    _run_script(tmp_path)
    second_state = sig.read_text()

    assert first_state == second_state


def test_mark_holiday_scans_handles_no_holiday_dates(tmp_path):
    logs = tmp_path / "logs"; logs.mkdir()
    _write_gap_log(logs, has_holiday=False)
    sig = logs / "signals.jsonl"
    sig.write_text(json.dumps({"timestamp_ist": "2026-05-27T10:00:00+05:30"}) + "\n")

    _run_script(tmp_path)

    row = json.loads(sig.read_text().strip())
    assert "is_holiday_scan" not in row


def test_mark_holiday_scans_marks_alerts_jsonl_too(tmp_path):
    logs = tmp_path / "logs"; logs.mkdir()
    _write_gap_log(logs, has_holiday=True)
    (logs / "signals.jsonl").write_text(
        json.dumps({"timestamp_ist": "2026-05-28T10:00:00+05:30"}) + "\n"
    )
    alerts = logs / "alerts.jsonl"
    alerts.write_text(
        json.dumps({"timestamp_ist": "2026-05-28T11:00:00+05:30", "event_type": "alert"}) + "\n"
    )

    _run_script(tmp_path)

    row = json.loads(alerts.read_text().strip())
    assert row.get("is_holiday_scan") is True
```

Run: `pytest tests/ -v` — expect all prior tests to still pass.

---

## STEP 4 — Verification checklist

```cmd
:: 1. Mark any existing holiday rows
python scripts\mark_holiday_scans.py
:: Expect: "Holiday dates: ['2026-05-28']" and a non-zero marked count
:: (or "No holiday-run dates detected" if logs are clean)

:: 2. Run dashboard update to propagate the flag to Parquet
update_dashboard.bat

:: 3. Confirm is_holiday_scan is in Parquet
python -c "import pandas as pd; df=pd.read_parquet('data/scc_data_2026-05.parquet'); print(df[df.get('is_holiday_scan', False)==True][['timestamp_ist','event_type','is_holiday_scan']].head())"

:: 4. Confirm clean data excludes holiday rows
python -c "import pandas as pd; df=pd.read_parquet('data/scc_data_2026-05.parquet'); clean=df[df.get('is_holiday_scan', False)!=True]; print(f'Total: {len(df)}, Clean: {len(clean)}')"

:: 5. All tests pass
pytest tests\ -v
```

### Live session checklist

- On a normal trading day: log shows "Market status: open" with candle count > 0.
- On a weekend: log shows "WEEKEND — All scans suppressed." No API call made.
- On a holiday: log shows "HOLIDAY — All scans suppressed." VIX check follows;
  if VIX is stale it says "VIX confirms: ...min ago." If VIX is somehow fresh
  it says "Candles stale but VIX fresh" and status flips to UNKNOWN (scans proceed).
- Pre-09:15 weekday: status starts as PRE_OPEN, run_forever re-checks every
  5 minutes until status is OPEN or HOLIDAY.
- No `signals.jsonl` rows written on confirmed holidays.

---

## Phase 5C Addendum — Internet Reconnect Resilience + Session-Only EOD

**Goal:** Survive long internet outages (1–3 h ISP drops) without the
bot exiting, and make the Telegram end-of-day summary reflect *only the
latest* `src.main` run when `run.bat` is restarted mid-day.

Zero strategy impact — this is a runtime-robustness layer that sits
underneath the orchestrator (Phase 5A) and the dashboard sync (Phase
5B). No new conditions, scan logic, or order plumbing.

### What this addendum delivers

1. `src/data/kite_feed.py` — after the existing bounded retry budget in
   `get_5min_candles()` is exhausted, if the failure looks like a
   network outage we enter an **uncapped reconnect waiting loop** that
   probes DNS, sleeps 30 s, flushes the urllib3 keep-alive pool, and
   retries the API call. Non-network errors (auth, stale token, bad
   instrument) still surface immediately.
2. `run.bat` — `powercfg /change standby-timeout-ac 0` before launching
   the bot, and `30` after exit. Prevents the laptop from sleeping
   during a long outage and missing every 5-min candle until someone
   wakes it.
3. `src/main.py` + `src/alerts/telegram_bot.py` — session counters
   (`session_scan_count`, `session_alert_count`,
   `session_nifty_alerts`, `session_bn_alerts`) are explicitly reset in
   `setup()` with a `Session counters reset ...` log line. The EOD
   summary now includes `session_started_at` so the Telegram message
   shows the window the counts cover.

### What this addendum does NOT do

- No retry/reconnect logic in `upstox_feed.py` — Upstox is the inactive
  feed today. When we revisit Upstox, mirror the Kite changes there.
- No retry around the broker `connect()` step. Reconnect is only wired
  through the hot scan path (`get_5min_candles`), which is the only
  call that happens repeatedly during the trading day.
- No detection of the *start* of an outage from the bot's side (e.g.
  ping monitoring). We only kick in when an API call has already failed.

---

### STEP A — `src/data/kite_feed.py`

#### Module-level additions

```python
import socket

_KITE_DNS_PROBE_HOST = "api.kite.trade"
_RECONNECT_SLEEP_SECONDS = 30


def _is_network_error(exc: BaseException | None) -> bool:
    """True when the exception message smells like a connectivity
    outage (getaddrinfo / NewConnectionError / read timeout / etc.).
    Auth and protocol errors return False so the reconnect loop
    cannot spin forever on a non-recoverable failure.
    """
    ...
```

The full needle list lives in the source — keep it broad enough to
cover both Windows (`getaddrinfo failed`) and Linux/Mac (`name or
service not known`, `temporary failure in name resolution`) wording.

#### `get_5min_candles()` after-retry hook

After the existing bounded `for attempt in range(retries + 1)` loop,
add:

```python
if not succeeded:
    if _is_network_error(last_err):
        data = self._wait_for_reconnect_and_refetch(
            token, from_date, to_date, last_err
        )
    else:
        raise RuntimeError(
            f"Kite historical_data failed after {retries + 1} attempts: {last_err}"
        )
```

The rest of the method (DataFrame shaping, `_drop_in_progress_5min`,
trim-to-lookback) is unchanged.

#### New helpers

`_flush_urllib3_pool()` closes the `KiteConnect.reqsession` so the next
call performs a fresh DNS lookup and TCP handshake. urllib3 keep-alive
otherwise holds stale connections from before the outage.

`_wait_for_reconnect_and_refetch(token, from_date, to_date, initial_err)`:

```
loop:
  try socket.getaddrinfo("api.kite.trade", 443)
  except gaierror / OSError:
    log "Internet down, waiting..."; sleep 30; continue
  log "Internet restored, resuming..."
  flush urllib3 pool
  try historical_data(...)
    return result
  except network-shaped error:
    log "DNS up but API still failing"; sleep 30; continue
  except other:
    raise  # not a connectivity problem, don't swallow
```

There is intentionally **no timeout** on this loop. The bot's job is to
stay alive across an arbitrary outage, not to give up after N minutes.
A user-initiated Ctrl+C still works because `time.sleep` is
interruptible.

#### Log line contract

The reconnect handler must produce these exact phrases so log greps in
post-mortem analysis are predictable:

- `Internet down, waiting...` (every 30 s while DNS or API is down)
- `Internet restored, resuming...` (once DNS resolves again)

---

### STEP B — `run.bat`

Wrap the `python -m src.main` line:

```bat
powercfg /change standby-timeout-ac 0
python -m src.main
set EXITCODE=%ERRORLEVEL%
powercfg /change standby-timeout-ac 30
endlocal & exit /b %EXITCODE%
```

`powercfg` requires admin-level rights only when changing the active
plan, not for `standby-timeout-ac` — it works for any user. The 30-min
restore on exit matches Windows 11 default so a normal user power
profile resumes after the bot is done.

The Phase 5A `SetThreadExecutionState` call inside `run_forever()`
already prevents *system* sleep while Python holds it active, but it
is released the moment the bot exits or crashes. Belt-and-suspenders:
disable AC standby through `powercfg` as well, so even if the bot dies
the laptop stays awake until the wrapper script finishes.

---

### STEP C — Session-only EOD counters

The four `session_*` counters are already zero-initialised in
`Orchestrator.__init__` and `__init__` is called once per
`python -m src.main` invocation, so the counts have always been
session-scoped on paper. This addendum makes the contract explicit and
auditable:

1. `__init__` adds `self.session_started_at: str | None = None`.
2. `setup()` re-zeros all four counters and stamps
   `session_started_at = datetime.now(IST).isoformat()`. A
   `Session counters reset (scans=0, alerts=0). EOD summary will only
   count this run, starting <iso>` line lands in `bot.log`.
3. `_compute_eod_summary()` adds `session_started_at` to its dict.
4. `TelegramAlerter._format_eod()` renders a `Session: since HH:MM IST
   (this run only)` line when `session_started_at` is present. The
   field is optional so the formatter stays backward-compatible with
   any caller (tests, replay tools) that builds a summary by hand.

#### Why this matters

If the bot crashes or is `Ctrl+C`'d and someone restarts `run.bat` at
13:00, the new run's EOD message at 15:00 should reflect alerts from
13:00 onwards — not aggregate the morning's alerts too. The Excel
dashboard and `alerts.jsonl` are still the source of truth for the
full trading day; Telegram intentionally shows only what *this* run
saw.

---

### STEP D — Verification checklist

```cmd
:: 1. Existing test suite still passes.
pytest tests\ -q
:: Expect: 326 passed (no test additions in this addendum).

:: 2. Syntax sanity.
python -c "import src.data.kite_feed, src.main, src.alerts.telegram_bot; print('OK')"

:: 3. (Optional, on the live machine during market hours) Force a
::    network outage by disabling Wi-Fi for 90 seconds, observe:
::      - bot.log shows "Internet down, waiting..." every 30 s
::      - bot stays running (no exit, no traceback)
::      - re-enabling Wi-Fi → "Internet restored, resuming..." within 30 s
::      - the next 5-min candle fetches normally
```

#### Live signs of health

- A clean trading day has zero `Internet down, waiting...` lines.
- A short outage (≤5 min) shows one or two of each phrase, no missed
  alerts after the resume.
- A long outage (1–3 h) keeps the bot alive; missed candles during the
  outage are *expected*. The bot does not back-fill — Phase 7's
  backtest harness reads the JSONL trail and can be re-pointed at the
  raw candle history if you need to reconstruct the missing window.

---

### Files touched by this addendum

| File                                  | Change                                         |
|---------------------------------------|------------------------------------------------|
| `src/data/kite_feed.py`               | reconnect loop + `_is_network_error` + helpers |
| `src/main.py`                         | explicit counter reset + `session_started_at`  |
| `src/alerts/telegram_bot.py`          | EOD formatter adds `Session: since ...` line   |
| `run.bat`                             | `powercfg` wrap around `python -m src.main`    |

No config-schema changes, no new dependencies, no migration required.
