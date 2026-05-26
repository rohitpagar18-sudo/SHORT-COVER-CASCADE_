# Expiry Day Rules — NSE Index Options

Authoritative reference for the bot. CLAUDE.md links here.

## Rules

| Index     | Weekly        | Monthly                       |
|-----------|---------------|-------------------------------|
| NIFTY     | **Tuesday**   | Last Tuesday of the month      |
| BankNifty | None — discontinued 2024-11-20 | Last Tuesday of the month |
| BSE Sensex | Thursday (BSE — not traded by this bot) | (not traded) |

### Key regulatory dates

- **2024-11-20** — NSE discontinued weekly BankNifty options. Only the
  monthly BankNifty contract remains, expiring on the last Tuesday of
  the month.
- **2025-09-02** — NIFTY weekly expiry day moved to Tuesday (SEBI
  circular). An earlier NSE plan to switch to Monday was deferred and
  superseded.

### Holiday shift rule

If a Tuesday falls on an NSE trading holiday, the contract expires on
the **previous trading day** (typically Monday, but earlier if Monday is
also a holiday or weekend). The bot's "Expiry Day" mode (different TP
multipliers, tighter stops per `config.yaml risk_reward.expiry_day_*`)
must trigger on the actual expiry trading day, not on the calendar
Tuesday.

The bot does NOT maintain its own holiday calendar — it should derive
the actual expiry date from broker instrument metadata (`instruments`
dump for Kite, `option_chain` for Upstox), and use today's date plus
weekday math only as a fallback / validation cross-check.

## 2026 Calendar — May through December

Computed Tuesdays. Holiday-shifted dates are NOT marked here (verify
against broker data). Cross-checked against live Kite NIFTY expiry list
on 2026-05-26: matched 2026-05-26, 2026-06-02 … 2026-06-30, 2026-07-28,
2026-09-29, 2026-12-29.

| Month | NIFTY Weeklies                                            | NIFTY + BankNifty Monthly (last Tue) |
|-------|-----------------------------------------------------------|--------------------------------------|
| May 2026 | 05, 12, 19, 26                                          | **2026-05-26**                      |
| Jun 2026 | 02, 09, 16, 23, 30                                      | **2026-06-30**                      |
| Jul 2026 | 07, 14, 21, 28                                          | **2026-07-28**                      |
| Aug 2026 | 04, 11, 18, 25                                          | **2026-08-25**                      |
| Sep 2026 | 01, 08, 15, 22, 29                                      | **2026-09-29**                      |
| Oct 2026 | 06, 13, 20, 27                                          | **2026-10-27**                      |
| Nov 2026 | 03, 10, 17, 24                                          | **2026-11-24**                      |
| Dec 2026 | 01, 08, 15, 22, 29                                      | **2026-12-29**                      |

(Listed dates are calendar Tuesdays. Always verify against the live
broker instrument dump before trading — the actual contract date can
shift to a Monday on holiday weeks.)

## Phase 3+ implementation notes

When the strike/expiry selection helper is built in Phase 3:

```python
def get_next_expiry(symbol: str, today: date) -> date:
    """Return the next valid expiry trading date for symbol.

    NIFTY      → next Tuesday on/after today, holiday-shifted.
                 If today is Tuesday and post-market, return next Tuesday.
    BANKNIFTY  → last Tuesday of current month if on/after today,
                 else last Tuesday of next month, holiday-shifted.

    Must be config-driven via instruments.<symbol>_*_expiry_day so a
    future regulator change is a config edit, not a code release.
    """
```

The "Expiry Day" mode in the strategy (different TP multipliers per
`config.yaml risk_reward.expiry_day_tp*_r`) is active **only when**
`today == get_next_expiry(symbol, today)` after the holiday shift —
not on the calendar Tuesday in general.

For BankNifty specifically: because there are no weeklies, the
strategy's "Expiry Day" mode triggers only one trading day per month
(the last Tuesday or its holiday-shifted equivalent). All other
BankNifty days run in normal-day mode.
