*** FIXES AFTER PHASE_5B ***
## PROMPT 1 — Holiday Guard Fix (paste this to Claude Code)
Read CLAUDE.md, then docs/phases/PHASE_5A.md sections covering setup(),
scan_once(), and run_forever(). Then look at logs/gap_log.jsonl — note
the "today_n=0" pattern on 2026-05-28 (Bakri Id holiday).

PROBLEM:
On NSE holidays/weekends, Kite returns stale prior-day candles. The bot
has no guard against this. Today (28 May 2026) it ran all day on a
holiday and wrote ghost rows to signals.jsonl. This corrupts Phase 7
backtest d0jata.

FIX PHILOSOPHY:
Single source of truth = broker's own candle data. No hardcoded holiday
lists. We ask: "Does today have live candles?" and act on the answer.

Three layers:
  1. Detect market status using candle data (dynamic, re-evaluated)
  2. Gate every scan on the status flag
  3. Retroactively tag rows already written during today's holiday run

============================================================
TASK 1 — Add market-status detection to src/main.py
============================================================

Add at module level (after imports):

    from enum import Enum

    class MarketStatus(Enum):
        UNKNOWN = "unknown"
        WEEKEND = "weekend"
        HOLIDAY = "holiday"
        PRE_OPEN = "pre_open"
        OPEN = "open"

    @dataclass
    class MarketStatusResult:
        status: MarketStatus
        reason: str
        today_candle_count: int
        latest_candle_date: str | None
        checked_at: str

Add to Orchestrator.__init__() alongside existing flags:

    self.market_status: MarketStatusResult | None = None
    self.holiday_abort: bool = False

Add this method to Orchestrator:

    def _check_market_status(self) -> MarketStatusResult:
        """
        Decide whether NSE is open today, using candle data as truth.

        Decision tree (first match wins):

          A. Weekend: today is Sat/Sun → WEEKEND (no API call)

          B. Pre-09:15 weekday → PRE_OPEN (no API call)
             (On a weekday holiday this branch fires until 09:15; the
              candle check below promotes it to HOLIDAY after 09:30.)

          C. Candle check (API call — the real arbiter):
             Fetch last 10 spot candles for NIFTY.
             Count how many have today's IST date.
               - today_count > 0           → OPEN
               - today_count == 0, ≥ 09:30 → HOLIDAY (definitive)
               - today_count == 0, < 09:30 → PRE_OPEN (opening window)

          D. Any exception in the candle fetch → UNKNOWN
             UNKNOWN is fail-open: scans proceed. Never use UNKNOWN
             as evidence of a holiday — it's a transient check failure.

        Always logs the outcome at INFO. Never raises.
        """

Implementation hints:
  - now = datetime.now(IST); today_d = now.date()
  - ts_dates = pd.to_datetime(candles["timestamp"]).dt.date
  - today_count = int((ts_dates == today_d).sum())
  - latest_date = str(ts_dates.max()) if len(candles) else None
  - Use dt_time(9, 15) and dt_time(9, 30) thresholds

============================================================
TASK 2 — Wire status check into setup()
============================================================

In setup(), AFTER _verify_token_freshness() and BEFORE _detect_gap_day():

    self.market_status = self._check_market_status()
    status = self.market_status.status

    if status in (MarketStatus.WEEKEND, MarketStatus.HOLIDAY):
        logger.warning(
            f"{status.value.upper()} — {self.market_status.reason}. "
            "All scans suppressed. Bot will idle until 15:30 / Ctrl+C."
        )
        self.holiday_abort = True
    elif status == MarketStatus.PRE_OPEN:
        logger.info("Pre-open — will recheck market status each polling loop.")
    else:
        logger.info(f"Market status: {status.value}")

CRITICAL: When holiday_abort is True, SKIP gap detection entirely.
Replace the existing _detect_gap_day() call with:

    if self.holiday_abort:
        self.is_gap_day = False
        self.gap_info = {"decision": "SKIPPED_HOLIDAY", "reason": self.market_status.reason}
    else:
        self.is_gap_day, self.gap_info = self._detect_gap_day()

This prevents gap_log.jsonl pollution on holidays.

Add to the startup Telegram payload:

    "market_status": self.market_status.status.value

Update TelegramAlerter._format_startup() to render one line:
  - If status in (weekend, holiday):
      "⛔ Market: {status.upper()} — bot dormant today"
  - Else:
      "Market status: {status}"

============================================================
TASK 3 — Gate scan_once() and add dynamic re-check in run_forever()
============================================================

At the VERY TOP of scan_once(), before everything else:

    if self.holiday_abort:
        logger.debug(
            f"Scan suppressed — status={self.market_status.status.value}"
        )
        return

In run_forever(), before the existing candle_key dedup block, add a
status re-check that runs every 5 minutes IF status is still in flux:

    STATUS_RECHECK_SECONDS = 300

    needs_recheck = (
        not self.holiday_abort
        and self.market_status is not None
        and self.market_status.status in (MarketStatus.PRE_OPEN, MarketStatus.UNKNOWN)
        and (
            last_status_check is None
            or (now - last_status_check).total_seconds() >= STATUS_RECHECK_SECONDS
        )
    )
    if needs_recheck:
        self.market_status = self._check_market_status()
        last_status_check = now
        if self.market_status.status == MarketStatus.HOLIDAY:
            self.holiday_abort = True
            logger.warning(
                "Status upgraded to HOLIDAY after recheck. Suppressing scans."
            )
            try:
                self.telegram.send(
                    f"⛔ NSE HOLIDAY DETECTED at {now.strftime('%H:%M')} — "
                    "bot was started early. All scans suppressed."
                )
            except Exception:
                pass
        elif self.market_status.status == MarketStatus.OPEN:
            logger.info("Status upgraded to OPEN — scan loop is now live.")

Declare `last_status_check: datetime | None = None` near the top of
run_forever() alongside the existing `last_scan_candle` flag.

Note: once status is OPEN we stop re-checking. Mid-day exchange halts
are rare; if one happens, the underlying candle-fetch errors in
_scan_symbol will surface it through normal exception paths.

============================================================
TASK 4 — Cleanup script for today's holiday rows
============================================================

Create scripts/mark_holiday_scans.py:

    """
    Retroactively tags rows in signals.jsonl that were written during
    NSE holidays. Idempotent. Run BEFORE update_dashboard.bat.

    Evidence: gap_log.jsonl rows where any per_symbol error contains
    'today_n=0' identify holiday-run dates.

    Usage: python scripts/mark_holiday_scans.py
    """

    import json
    from pathlib import Path

    def _holiday_dates_from_gap_log(p: Path) -> set[str]:
        out = set()
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

    def main() -> None:
        gap = Path("logs/gap_log.jsonl")
        sig = Path("logs/signals.jsonl")

        holiday_dates = _holiday_dates_from_gap_log(gap)
        if not holiday_dates:
            print("No holiday-run dates detected in gap_log.jsonl.")
            return

        print(f"Holiday dates: {sorted(holiday_dates)}")
        if not sig.exists():
            print("No signals.jsonl — nothing to mark.")
            return

        new_lines = []
        marked = 0
        for line in sig.read_text(encoding="utf-8").splitlines():
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

        tmp = sig.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        tmp.replace(sig)

        print(f"Marked {marked} rows with is_holiday_scan=True")
        if marked:
            print("Next: run update_dashboard.bat to push the flag to Parquet.")

    if __name__ == "__main__":
        main()

Also do the same cleanup for alerts.jsonl using the same logic (loop
both files in main()). Even though no alerts likely fired today, future
holidays should be covered symmetrically.

============================================================
TASK 5 — Document the new column in data/schema.md
============================================================

Add one row to the "Common columns" table:

  | `is_holiday_scan` | bool | Present only on rows written before
  the holiday guard existed. True = row recorded on an NSE holiday
  (no live candles). Exclude in all backtests/ML queries:
  `df[df.get("is_holiday_scan", False) != True]` |

============================================================
After all tasks: report
============================================================

1. Confirm Orchestrator.__init__ now has market_status and holiday_abort
2. Confirm _check_market_status() handles all 4 branches (weekend /
   pre-open / candle-check / API error)
3. Confirm scan_once() first line is the holiday_abort gate
4. Confirm setup() SKIPS _detect_gap_day() when holiday_abort is True
5. Confirm run_forever() has the 5-minute recheck logic for PRE_OPEN/UNKNOWN
6. Run: python scripts/mark_holiday_scans.py
   Paste exact output (expect: "Holiday dates: ['2026-05-28']" and a
   non-zero marked count).
7. Run: pytest tests/ -v
   All existing tests must still pass. (New tests are added in a
   follow-up prompt.)


## PROMPT 2 — Tests for Holiday Guard

Read CLAUDE.md, then src/main.py (the Orchestrator class we just
updated with _check_market_status, holiday_abort, and the run_forever
recheck logic).

Goal: add unit tests covering the holiday-guard fix. Mock
_get_spot_candles so no tests hit the live broker.

Add the following tests to tests/test_orchestrator.py. If the file
doesn't exist, create it. Use pytest + pytest-mock (mocker fixture).

Helper at the top of the test file (or in conftest.py if cleaner):

    import pandas as pd
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from unittest.mock import MagicMock

    IST = ZoneInfo("Asia/Kolkata")

    def _make_candles(dates: list[str]) -> pd.DataFrame:
        """Build a minimal candle DataFrame for a list of YYYY-MM-DD strings."""
        return pd.DataFrame({
            "timestamp": pd.to_datetime(dates).tz_localize("Asia/Kolkata"),
            "open": [100.0] * len(dates),
            "high": [101.0] * len(dates),
            "low":  [99.0]  * len(dates),
            "close":[100.5] * len(dates),
            "volume":[1000] * len(dates),
            "oi":   [500000]* len(dates),
        })

    def _orch_with_mocked_now(mocker, now_iso: str):
        """Build an Orchestrator instance with datetime.now(IST) frozen."""
        from src.main import Orchestrator
        orch = Orchestrator.__new__(Orchestrator)  # skip __init__
        orch.market_status = None
        orch.holiday_abort = False
        orch.feed = MagicMock()
        # Freeze "now" inside src/main
        fixed_now = datetime.fromisoformat(now_iso).replace(tzinfo=IST)
        mocker.patch("src.main.datetime").now.return_value = fixed_now
        return orch, fixed_now

============================================================
TESTS — _check_market_status() decision tree
============================================================

# A. Weekend branch (no API call expected)
def test_market_status_saturday_returns_weekend(mocker):
    orch, _ = _orch_with_mocked_now(mocker, "2026-05-30 11:00")  # Saturday
    result = orch._check_market_status()
    assert result.status.value == "weekend"
    orch.feed.get_5min_candles.assert_not_called()

def test_market_status_sunday_returns_weekend(mocker):
    orch, _ = _orch_with_mocked_now(mocker, "2026-05-31 11:00")  # Sunday
    result = orch._check_market_status()
    assert result.status.value == "weekend"
    orch.feed.get_5min_candles.assert_not_called()

# B. Pre-09:15 weekday — no API call
def test_market_status_before_0915_returns_pre_open(mocker):
    orch, _ = _orch_with_mocked_now(mocker, "2026-05-29 08:45")  # Friday
    result = orch._check_market_status()
    assert result.status.value == "pre_open"
    orch.feed.get_5min_candles.assert_not_called()

# C. Candle check after 09:30
def test_market_status_no_today_candles_after_0930_returns_holiday(mocker):
    orch, _ = _orch_with_mocked_now(mocker, "2026-05-28 10:00")  # Bakri Id
    # All candles from prior trading day
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-27 14:55", "2026-05-27 15:00", "2026-05-27 15:25"]
    )
    result = orch._check_market_status()
    assert result.status.value == "holiday"
    assert result.today_candle_count == 0

def test_market_status_today_candles_present_returns_open(mocker):
    orch, _ = _orch_with_mocked_now(mocker, "2026-05-29 10:30")
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-29 09:15", "2026-05-29 09:20", "2026-05-29 09:25"]
    )
    result = orch._check_market_status()
    assert result.status.value == "open"
    assert result.today_candle_count == 3

# D. Opening window (09:15–09:29) with no today candles yet
def test_market_status_no_candles_before_0930_returns_pre_open(mocker):
    orch, _ = _orch_with_mocked_now(mocker, "2026-05-29 09:20")
    orch.feed.get_5min_candles.return_value = _make_candles(
        ["2026-05-28 14:55", "2026-05-28 15:25"]  # prior day only
    )
    result = orch._check_market_status()
    assert result.status.value == "pre_open"

# E. API error fail-open
def test_market_status_api_error_returns_unknown_not_holiday(mocker):
    orch, _ = _orch_with_mocked_now(mocker, "2026-05-29 10:30")
    orch.feed.get_5min_candles.side_effect = RuntimeError("Kite timeout")
    result = orch._check_market_status()
    assert result.status.value == "unknown"
    # UNKNOWN must NOT set holiday_abort indirectly
    assert "API error" in result.reason or "timeout" in result.reason.lower()

============================================================
TESTS — scan_once() gating on holiday_abort
============================================================

def test_scan_once_returns_immediately_when_holiday_abort_true(mocker):
    from src.main import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch.holiday_abort = True
    orch.market_status = MagicMock()
    orch.market_status.status.value = "holiday"
    orch.feed = MagicMock()
    orch.signal_logger = MagicMock()
    orch.state = MagicMock()

    orch.scan_once()

    # No state checks, no feed calls, no logger writes
    orch.feed.get_5min_candles.assert_not_called()
    orch.signal_logger.log_signal.assert_not_called()
    orch.signal_logger.log_alert.assert_not_called()

============================================================
TESTS — Cleanup script
============================================================

def test_mark_holiday_scans_marks_correct_dates(tmp_path):
    import json
    from scripts.mark_holiday_scans import main as mark_main

    logs = tmp_path / "logs"
    logs.mkdir()

    # gap_log shows 2026-05-28 was a holiday (today_n=0 in error)
    gap = logs / "gap_log.jsonl"
    gap.write_text(json.dumps({
        "timestamp_ist": "2026-05-28T09:16:00+05:30",
        "per_symbol": {
            "NIFTY": {"error": "insufficient_data: today_n=0, prev_n=5"},
            "BANKNIFTY": {"error": "insufficient_data: today_n=0, prev_n=5"},
        },
    }) + "\n")

    # signals.jsonl has rows from holiday and from a normal day
    sig = logs / "signals.jsonl"
    sig.write_text(
        json.dumps({"timestamp_ist": "2026-05-28T10:00:00+05:30", "symbol": "NIFTY"}) + "\n" +
        json.dumps({"timestamp_ist": "2026-05-27T10:00:00+05:30", "symbol": "NIFTY"}) + "\n"
    )

    # Run the script with cwd switched to tmp_path
    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        mark_main()
    finally:
        os.chdir(cwd)

    lines = [json.loads(l) for l in sig.read_text().splitlines() if l.strip()]
    holiday_row = next(r for r in lines if r["timestamp_ist"].startswith("2026-05-28"))
    normal_row  = next(r for r in lines if r["timestamp_ist"].startswith("2026-05-27"))
    assert holiday_row.get("is_holiday_scan") is True
    assert "is_holiday_scan" not in normal_row  # untouched

def test_mark_holiday_scans_idempotent(tmp_path):
    """Running the script twice produces the same result, not double-marked."""
    import json
    from scripts.mark_holiday_scans import main as mark_main

    logs = tmp_path / "logs"; logs.mkdir()
    gap = logs / "gap_log.jsonl"
    gap.write_text(json.dumps({
        "timestamp_ist": "2026-05-28T09:16:00+05:30",
        "per_symbol": {"NIFTY": {"error": "insufficient_data: today_n=0"}},
    }) + "\n")
    sig = logs / "signals.jsonl"
    sig.write_text(json.dumps({"timestamp_ist": "2026-05-28T10:00:00+05:30"}) + "\n")

    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        mark_main()
        first_state = sig.read_text()
        mark_main()
        second_state = sig.read_text()
    finally:
        os.chdir(cwd)

    assert first_state == second_state  # second run did not double-mark

def test_mark_holiday_scans_handles_no_holiday_dates(tmp_path):
    """If gap_log has no today_n=0 evidence, nothing is marked."""
    import json
    from scripts.mark_holiday_scans import main as mark_main

    logs = tmp_path / "logs"; logs.mkdir()
    gap = logs / "gap_log.jsonl"
    # Normal-day gap log entry — no today_n=0
    gap.write_text(json.dumps({
        "timestamp_ist": "2026-05-27T09:16:00+05:30",
        "per_symbol": {"NIFTY": {"gap_pct": 0.3, "triggers": False}},
    }) + "\n")
    sig = logs / "signals.jsonl"
    sig.write_text(json.dumps({"timestamp_ist": "2026-05-27T10:00:00+05:30"}) + "\n")

    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        mark_main()
    finally:
        os.chdir(cwd)

    row = json.loads(sig.read_text().strip())
    assert "is_holiday_scan" not in row

============================================================
After writing tests, run:
  pytest tests/test_orchestrator.py -v

Report:
1. Exact pytest output for the new tests (count + pass/fail)
2. Any test that needed a fixture or helper adjustment
3. Confirm total test count across the whole suite still grows (no
   existing tests broken)



## Telegram send failed: Event loop is closed at 15:03:15 when bot tried to send EOD summary.
Read CLAUDE.md, then src/alerts/telegram_bot.py.

PROBLEM:
On 2026-05-28 at 15:03:15, this error appeared:
  Telegram send failed: Unknown error in HTTP implementation:
  RuntimeError('Event loop is closed')

Root cause: TelegramAlerter.send() creates a new asyncio loop on every
call and closes it. python-telegram-bot's HTTPXRequest pool keeps
state across calls and breaks when the loop it was bound to is closed.
After many sends in one session (startup, signals, EOD, exceptions),
the next call eventually hits a closed loop.

FIX:
Replace python-telegram-bot with a direct synchronous HTTP call via
requests. The Telegram Bot API is plain HTTPS — no async needed for
our single-chat single-message use case.

============================================================
TASK 1 — Rewrite src/alerts/telegram_bot.py
============================================================

Replace the entire file with this implementation:

    """Telegram alert sender (synchronous HTTP, no asyncio).

    Direct calls to api.telegram.org via requests.post. No
    python-telegram-bot dependency, no asyncio event loop juggling.
    All send_* methods return True on success, False on failure;
    failures are logged but never raised.
    """

    from __future__ import annotations

    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import requests
    from loguru import logger

    IST = ZoneInfo("Asia/Kolkata")

    TELEGRAM_API_BASE = "https://api.telegram.org"
    SEND_TIMEOUT_SECONDS = 10


    class TelegramAlerter:
        """Send formatted alerts to a single Telegram chat."""

        def __init__(self) -> None:
            self.token = os.getenv("TELEGRAM_BOT_TOKEN")
            self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if not self.token or not self.chat_id:
                raise RuntimeError(
                    "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing from secrets.env"
                )
            self._url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"

        # ----- public sending API -----

        def send(self, message: str) -> bool:
            """POST to Telegram. Returns True on 2xx, False otherwise."""
            try:
                resp = requests.post(
                    self._url,
                    data={
                        "chat_id": self.chat_id,
                        "text": message,
                    },
                    timeout=SEND_TIMEOUT_SECONDS,
                )
                if resp.status_code // 100 == 2:
                    return True
                logger.error(
                    f"Telegram send failed: HTTP {resp.status_code} "
                    f"body={resp.text[:300]}"
                )
                return False
            except requests.RequestException as e:
                logger.error(f"Telegram send failed: {e}")
                return False
            except Exception as e:
                logger.error(f"Telegram send unexpected error: {e}")
                return False

        # Keep all existing send_* methods (send_startup, send_signal,
        # send_circuit_breaker, send_eod_summary, send_exception) and all
        # _format_* methods EXACTLY as they currently are — they all
        # ultimately route through self.send(message), so they need no
        # changes. Preserve every formatter byte-for-byte including the
        # _format_gap_line, _format_market_status_line, and the Phase 5B
        # "Insight:" line in _format_signal.

============================================================
TASK 2 — requirements.txt
============================================================

- Confirm `requests>=2.31` is already in requirements.txt (it should
  be — it's in Phase 0). If missing, add it.
- python-telegram-bot is no longer used by the bot at runtime. You may
  leave it in requirements.txt (no harm) or remove it. Recommend
  leaving it for now to avoid breaking anything else that imports it.

============================================================
TASK 3 — Tests
============================================================

Update tests/test_telegram.py:

- Remove any mocks of `Bot` from python-telegram-bot.
- Mock `requests.post` instead.

Required tests (replace existing equivalents):

    def test_telegram_send_returns_true_on_2xx(mocker):
        mocker.patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "TEST_TOKEN",
            "TELEGRAM_CHAT_ID": "12345",
        })
        mock_resp = mocker.MagicMock(status_code=200, text="ok")
        mocker.patch("requests.post", return_value=mock_resp)
        from src.alerts.telegram_bot import TelegramAlerter
        ok = TelegramAlerter().send("hi")
        assert ok is True

    def test_telegram_send_returns_false_on_non_2xx(mocker):
        mocker.patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "TEST_TOKEN",
            "TELEGRAM_CHAT_ID": "12345",
        })
        mock_resp = mocker.MagicMock(status_code=400, text="bad request")
        mocker.patch("requests.post", return_value=mock_resp)
        from src.alerts.telegram_bot import TelegramAlerter
        ok = TelegramAlerter().send("hi")
        assert ok is False

    def test_telegram_send_returns_false_on_timeout(mocker):
        mocker.patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "TEST_TOKEN",
            "TELEGRAM_CHAT_ID": "12345",
        })
        import requests
        mocker.patch("requests.post", side_effect=requests.Timeout())
        from src.alerts.telegram_bot import TelegramAlerter
        ok = TelegramAlerter().send("hi")
        assert ok is False

    def test_telegram_missing_secrets_raises(mocker):
        mocker.patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
        }, clear=False)
        import pytest
        from src.alerts.telegram_bot import TelegramAlerter
        with pytest.raises(RuntimeError):
            TelegramAlerter()

    def test_send_signal_passes_formatted_message_to_send(mocker):
        # Confirm _format_signal still works and routes through send()
        mocker.patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "T",
            "TELEGRAM_CHAT_ID": "1",
        })
        from src.alerts.telegram_bot import TelegramAlerter
        alerter = TelegramAlerter()
        spy = mocker.patch.object(alerter, "send", return_value=True)
        signal_data = {
            "symbol": "NIFTY", "strike": 24050, "option_type": "CE",
            "relation": "ATM", "expiry": "2026-06-02",
            "date": "2026-05-29", "time": "10:35", "day_type": "Normal",
            "vix": 14.2, "vix_regime": "Normal", "vix_multiplier": 1.0,
            "spot": 24030.0, "spot_position": "Above VWAP ✓",
            "lot_size": 65, "entry": 152.50, "sl": 140.00,
            "sl_method": 1, "tp1": 171.25, "tp2": 183.75,
            "tp1_r": 1.5, "tp2_r": 2.5,
            "risk_per_unit": 12.50, "lots": 3, "total_risk": 2437.50,
            "telegram_short_remark": "",
        }
        alerter.send_signal(signal_data)
        spy.assert_called_once()
        msg = spy.call_args[0][0]
        assert "NIFTY 24050 CE" in msg
        assert "C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓" in msg

Keep any existing _format_* tests that don't depend on the Bot class.

============================================================
After all tasks: report
============================================================

1. Confirm src/alerts/telegram_bot.py no longer imports
   python-telegram-bot anywhere.
2. Confirm all _format_* helpers are preserved unchanged.
3. Run: python scripts/test_telegram.py
   You should receive "🧪 Telegram test from Short Cover Cascade Bot..."
   in your Telegram chat within 2 seconds.
4. Run: pytest tests/ -v
   All prior tests must still pass. The updated telegram tests must
   be green.


## Simple prompt to add this (paste to Claude Code after Prompt 2 + Telegram fix)

Read CLAUDE.md, then src/main.py — specifically _check_market_status().
Also read src/data/kite_feed.py — the get_india_vix() method.

GOAL:
Add a SECOND confirmation check before declaring HOLIDAY. The current
candle-based check can mis-flag a trading day as HOLIDAY if Kite has
a brief glitch or internet drops for 10–30 minutes. We confirm with
an independent source: India VIX last-update timestamp.

LOGIC:
1. Run existing candle check first (no changes).
2. ONLY if candle check returns HOLIDAY, run VIX freshness check.
3. If VIX timestamp is also stale → confirmed HOLIDAY.
4. If VIX timestamp is fresh → candles lied → flip to UNKNOWN (fail-open).
5. Any error in the second check → trust the first → still HOLIDAY.

============================================================
TASK 1 — Add get_india_vix_with_timestamp() to feeds
============================================================

In src/data/base_feed.py, add abstract method:

    def get_india_vix_with_timestamp(self) -> tuple[float, str | None]:
        """Returns (vix_value, last_trade_time_iso). 
        last_trade_time_iso is the IST ISO timestamp of last VIX update.
        Returns (-1.0, None) on error."""
        raise NotImplementedError

In src/data/kite_feed.py, implement:

    def get_india_vix_with_timestamp(self) -> tuple[float, str | None]:
        try:
            quote = self._kite.quote(["NSE:INDIA VIX"])
            data = quote.get("NSE:INDIA VIX", {})
            value = float(data.get("last_price", -1.0))
            last_trade_time = data.get("last_trade_time")  # datetime obj
            if last_trade_time:
                # Kite returns naive datetime in IST
                from zoneinfo import ZoneInfo
                ist = ZoneInfo("Asia/Kolkata")
                ts_iso = last_trade_time.replace(tzinfo=ist).isoformat()
            else:
                ts_iso = None
            return value, ts_iso
        except Exception as e:
            from loguru import logger
            logger.warning(f"VIX with timestamp fetch failed: {e}")
            return -1.0, None

In src/data/upstox_feed.py, implement similarly using Upstox quote API
(field name may differ — check Upstox docs for the timestamp field).
If Upstox doesn't expose timestamp, return (vix_value, None) and the
second check will skip gracefully.

============================================================
TASK 2 — Add VIX freshness check to _check_market_status()
============================================================

After the candle-based decision in _check_market_status(), if status
is HOLIDAY, run the second check:

    # Existing candle-based decision tree runs first...
    # ... results in `status = MarketStatus.HOLIDAY` for example ...

    # Second check: confirm via VIX timestamp ONLY when first check
    # says HOLIDAY. Skip the second check for any other status.
    if status == MarketStatus.HOLIDAY:
        confirmed, vix_reason = self._confirm_holiday_via_vix(now)
        if not confirmed:
            logger.warning(
                f"Candle check said HOLIDAY but VIX is fresh ({vix_reason}). "
                "Likely a candle-fetch glitch. Falling back to UNKNOWN — "
                "scans will proceed."
            )
            status = MarketStatus.UNKNOWN
            reason = f"Candles stale but VIX fresh: {vix_reason}"
        else:
            logger.info(f"HOLIDAY confirmed by VIX check: {vix_reason}")
            reason = f"{reason} | VIX confirms: {vix_reason}"

Add the helper method:

    def _confirm_holiday_via_vix(self, now: datetime) -> tuple[bool, str]:
        """
        Second-source holiday confirmation using India VIX timestamp.

        Returns (is_holiday_confirmed, reason).

        Logic:
          - If VIX timestamp < 10 minutes old → market is live → NOT holiday
          - If VIX timestamp >= 10 minutes old → confirms holiday
          - If VIX fetch fails or timestamp is None → trust first check
            (return True, "VIX timestamp unavailable")
        """
        try:
            vix_value, vix_ts_iso = self.feed.get_india_vix_with_timestamp()
        except Exception as e:
            logger.warning(f"VIX confirmation check errored: {e}")
            return True, f"VIX check errored, trusting candle check: {e}"

        if vix_ts_iso is None:
            return True, "VIX timestamp unavailable, trusting candle check"

        try:
            vix_ts = datetime.fromisoformat(vix_ts_iso)
            if vix_ts.tzinfo is None:
                vix_ts = vix_ts.replace(tzinfo=IST)
            age_seconds = (now - vix_ts).total_seconds()
            age_minutes = age_seconds / 60.0
        except Exception as e:
            return True, f"VIX timestamp parse failed: {e}"

        if age_minutes < 10:
            return False, f"VIX updated {age_minutes:.1f} min ago — market is live"
        return True, f"VIX last updated {age_minutes:.1f} min ago — confirms holiday"

============================================================
TASK 3 — Tests
============================================================

Add to tests/test_orchestrator.py:

    def test_holiday_confirmed_when_both_candles_and_vix_stale(mocker):
        """Candle check + VIX both stale → confirmed HOLIDAY."""
        # Setup: 10:00 AM, no today candles, VIX timestamp 2 hours old

    def test_holiday_overridden_when_vix_is_fresh(mocker):
        """Candle check says HOLIDAY but VIX updated 2 min ago → UNKNOWN."""
        # This is the key scenario — connectivity glitch on a trading day

    def test_vix_check_skipped_when_first_check_is_open(mocker):
        """When candle check says OPEN, VIX check should not even be called."""

    def test_vix_check_failure_defaults_to_trusting_first_check(mocker):
        """If VIX fetch errors, still HOLIDAY (don't override the first check)."""

    def test_vix_check_no_timestamp_field_defaults_to_holiday(mocker):
        """If feed returns (value, None) for timestamp, still HOLIDAY."""

============================================================
After all tasks: report
============================================================

1. Confirm get_india_vix_with_timestamp() exists in both KiteFeed and
   UpstoxFeed (Upstox may return None for timestamp — that's OK).
2. Confirm _confirm_holiday_via_vix() is only called when first check
   returns HOLIDAY.
3. Run: pytest tests/ -v
4. Brief sanity test: temporarily edit _check_market_status() to force
   status=HOLIDAY, run the bot once during market hours, confirm the
   log shows "Candle check said HOLIDAY but VIX is fresh ... Falling
   back to UNKNOWN" — then revert the edit.