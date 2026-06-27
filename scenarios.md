# Short Cover Cascade — Strategy Scenarios & Rules

---

## How the Bot Works — Step by Step

### Step 1 — Bot scans every 5 minutes (9:45 AM to 2:30 PM)

Every closed 5-min candle, bot checks **5 conditions (C0–C4)** on each enabled strike of NIFTY/BankNifty CE and PE.

| Condition | What it checks |
|-----------|----------------|
| **C0** | Spot price ABOVE VWAP (bullish → CE) or BELOW VWAP (bearish → PE) |
| **C1** | Option candle is GREEN and option price is ABOVE its own VWAP |
| **C2** | Open Interest is FALLING (short writers covering = panic buying) |
| **C3** | OI falling FASTER than its 20-candle average (acceleration) |
| **C4** | Volume SPIKE above 20-candle average |

> **All 5 must pass → Telegram alert fires**

---

### Step 2 — Which strike gets alerted?

Bot scans up to 7 strike depths per scan (config-controlled):

```
ITM3 | ITM2 | ITM1 | ATM | OTM1 | OTM2 | OTM3
```

- **Default enabled:** ITM2, ITM1, ATM only
- Each enabled strike is checked **independently**
- You can get 1, 2, or 3 alerts in the same 5-min candle

---

### Step 3 — Entry, SL, and TP calculated at alert time

```
Entry  =  option close price at alert candle
R      =  VWAP buffer (based on VIX)
SL     =  Entry − R
```

| Day Type | TP1 | TP2 |
|----------|-----|-----|
| Normal day | Entry + (R × 1.5) | Entry + (R × 2.5) |
| Expiry day | Entry + (R × 2.0) | Entry + (R × 3.0) |

> Expiry day targets are LARGER (2R / 3R) because option premiums move faster near expiry.
> Normal day targets are smaller (1.5R / 2.5R). Values live in `config.yaml → risk_reward`.

---

## Scenarios

---

### Scenario A — Same direction alert fires again 10–15 min later

```
09:50  →  NIFTY CE ITM1 alert fires   ✅ TAKEN  (episode starts, 20-min window opens)
10:00  →  NIFTY CE ITM1 alert again   🔁 ECHO   (within 20-min dedup window — ignored)
10:05  →  NIFTY CE ATM  alert fires   🔁 ECHO   (same option_type = same episode)
```

**Rule:** Episode key = `(symbol, option_type)`. All alerts within **20 minutes** of the first alert collapse into one paper trade. Only the **first alert is TAKEN**. The rest are ECHO — no second position opened.

---

### Scenario B — Same direction alert fires again AFTER 30 min

```
09:50  →  NIFTY CE ITM1 alert   ✅ TAKEN   (position open, SL = ₹X)
10:20  →  NIFTY CE ATM  alert   ⛔ SKIPPED  (position still open — position-open gate)
10:45  →  Position hits TP1     💰 50% exited, SL moved to breakeven
11:00  →  Position hits TP2     💰 remaining 50% exited — episode CLOSED
11:05  →  NIFTY CE ITM1 alert   ✅ TAKEN   (new episode — if daily cap not hit)
```

**Rule:** New episode only opens **after prior position is fully exited**. No pyramiding, ever.

---

### Scenario C — CE alert, then PE alert on same index

```
10:00  →  NIFTY CE ITM1 alert   ✅ TAKEN  (CE position open)
10:30  →  NIFTY PE ATM  alert   ✅ TAKEN  (PE is a different episode key)
```

**What happens:** CE and PE have **separate episode keys** — `(NIFTY, CE)` vs `(NIFTY, PE)`. Both can be open simultaneously. No conflict rule.

```
Active at 10:30:   NIFTY CE position (open) + NIFTY PE position (open)
```

> This can happen on a **choppy/sideways day**. Both positions are tracked independently.

---

### Scenario D — CE takes SL hit, then CE alert fires again

```
09:50  →  NIFTY CE ITM1 alert    ✅ TAKEN
10:05  →  SL hit                 ❌ Full exit, loss booked
                                    ↓ 15-min cooldown starts (until 10:20)
10:10  →  New CE alert fires     ⛔ SKIPPED  (in cooldown window)
10:20  →  Cooldown over
10:25  →  New CE alert fires     ✅ TAKEN   (fresh episode, if cap not hit)
```

**Rule:** After any SL hit, bot waits **15 minutes** before accepting new entries.

---

### Scenario E — 2 SL hits on the same strike → strike is killed

```
09:50  →  NIFTY 24500 CE         ✅ TAKEN
10:00  →  SL hit #1              ❌ (same-strike SL count: 1)
10:20  →  NIFTY 24500 CE         ✅ TAKEN again (after cooldown)
10:35  →  SL hit #2              ❌ (same-strike SL count: 2)
                                    ↓ Strike 24500 CE is now DEAD for today
10:55  →  NIFTY 24500 CE alert   ⛔ SKIPPED  (killed strike)
10:55  →  NIFTY 24450 CE alert   ✅ TAKEN   (different strike — allowed)
```

> **Kill is per strike number + option type.**
> 24500 CE killed ≠ 24500 PE killed (those are independent).

---

### Scenario F — Circuit breaker triggers (too many SL hits in a day)

```
09:50  →  CE trade → SL hit      ❌  (daily SL count: 1)
10:15  →  PE trade → SL hit      ❌  (daily SL count: 2)
10:45  →  CE trade → SL hit      ❌  (daily SL count: 3)  ← CIRCUIT BREAKER FIRES
                                    ↓ Bot stops all entries for the day
                                    ↓ Telegram: "Daily SL limit hit — no more entries today"
11:00  →  Any new alert          ⛔ SKIPPED  (circuit broken for the day)
```

> Live bot circuit breaker: `circuit_breakers.max_sl_per_day = 3` (fires after 3rd SL).
> Paper trade circuit breaker: `paper_trading.circuit_breaker_sl_count = 5` (fires after 5th paper SL).

---

### Scenario G — Multiple strikes fire on the same candle

```
10:30 candle closes:
  →  NIFTY CE ITM2 alert fires
  →  NIFTY CE ITM1 alert fires   ← ITM1 WINS (highest priority)
  →  NIFTY CE ATM  alert fires
```

**Paper trade result:** Only **ITM1 is TAKEN**. ITM2 and ATM become ECHO.

**Priority order:** `ITM1 > ATM > ITM2 > ITM3 > OTM1 > OTM2 > OTM3`

---

### Scenario H — ATM is the only enabled strike AND it gets killed

**Config:** `paper_order_strikes.itm=OFF, atm=ON, otm=OFF` and `same_strike_kill_after_2_sl=ON`

```
09:50  →  NIFTY CE ATM 24500    ✅ TAKEN
10:00  →  SL hit #1             ❌ (same-strike SL count on 24500 CE: 1)
10:20  →  NIFTY CE ATM 24500    ✅ TAKEN again (after cooldown)
10:35  →  SL hit #2             ❌ (same-strike SL count on 24500 CE: 2)
                                    ↓ Strike 24500 CE is DEAD for today
10:55  →  NIFTY CE ATM 24500    ⛔ SKIPPED  (killed strike)
11:00  →  NIFTY CE ITM1 24450   ⛔ SKIPPED  (paper_order_strike: itm=OFF)
11:00  →  NIFTY CE OTM1 24550   ⛔ SKIPPED  (paper_order_strike: otm=OFF)
```
ATM-only + same_strike_kill_after_2sl = ON      

  When ATM is the only enabled strike (paper_order_strikes.itm=OFF,  
  atm=ON, otm=OFF) and that ATM strike accumulates 2 SLs:

  1. ATM strike is killed — key is (NIFTY, 24500, CE)
  2. Telegram alerts keep firing — C0–C4 scanning never stops        
  3. All subsequent entries for NIFTY CE are SKIPPED for the rest of 
  the day:
    - ATM → SKIPPED (killed strike)
    - ITM1/ITM2 → SKIPPED (paper_order_strike not enabled)
    - OTM → SKIPPED (paper_order_strike not enabled)
  4. NIFTY PE is completely unaffected — separate kill key (NIFTY,   
  24500, PE)
  5. BankNifty is unaffected — different symbol
  6. Bot does NOT shut down — only that specific (symbol,
  strike_number, option_type) is dead
  7. If spot drifts and ATM moves to 24550 CE — that's a different   
  strike number, new kill key, allowed again
**What the bot does:**
- **Telegram alerts KEEP FIRING** — C0–C4 scanning never stops. You still get alert messages.
- **Paper trades: SKIPPED for rest of day on NIFTY CE** — ATM is killed and no other strike is enabled.
- **NIFTY PE is unaffected** — kill key is `(NIFTY, 24500, CE)`. PE has its own independent key.
- **BankNifty is unaffected** — completely separate symbol.
- **Bot does NOT shut down** — only that specific `(symbol, strike, option_type)` combo is dead.

> If you want re-entry on a different ATM level (e.g. spot drifts and new ATM = 24550), that's a
> different strike number → different kill key → allowed.

---

## Daily Limits at a Glance

| Gate | Rule | Live bot config | Paper config |
|------|------|-----------------|--------------|
| Entry window | 9:45 AM – 2:30 PM | configurable | same |
| Gap day start | 10:00 AM (if gap >1% from prev close) | configurable | same |
| Hard close | 3:00 PM — cannot be disabled | fixed | same |
| Max paper trades/day | 5 trades | N/A | `max_trades_per_day: 5` |
| SL circuit breaker | Stop entries for the day | `max_sl_per_day: 3` | `circuit_breaker_sl_count: 5` |
| Loss circuit breaker | ₹6,000 loss → stop for the day | `max_loss_per_day_rupees: 6000` | N/A |
| Cooldown after SL | 15 min wait before next entry | configurable | same |
| Strike kill | 2 SLs on same strike → dead for the day | `same_strike_kill_after_2_sl: ON` | same |
| Dedup window | 20 min (collapses re-fires into one episode) | configurable | same |

---

## Exit Flow — All 3 SL Methods

```
ENTRY
  │
  ├─── Price drops to SL
  │         └── Exit 100%  →  SL_HIT ❌
  │
  ├─── Price rises to TP1
  │         └── Exit tp1_lots at TP1  💰  (lots=1: full exit, no runner)
  │               │       tp1_lots = ceil(lots/2); tp2_lots = lots − tp1_lots
  │               │
  │               ├─ Method 1/2 → SL moves to BREAKEVEN on remaining tp2_lots
  │               ├─ Method 3  → SL keeps trailing 19-SMA (no breakeven)
  │               │
  │               ├─── Remaining tp2_lots hits SL/Breakeven/Trail → PARTIAL ⚠️
  │               └─── Remaining tp2_lots hits TP2 → TP2_HIT 💰💰
  │
  ├─── Red candle entirely below VWAP
  │         └── HARD EXIT (all remaining quantity)  🔴
  │
  └─── 3:00 PM reached
            └── Force-close whatever is open → EOD_FLAT / TP1_HIT
```

| Outcome | Meaning |
|---------|---------|
| `TP2_HIT` | Both TP1 and TP2 hit — full profit |
| `TP1_HIT` | TP1 hit, position force-closed at EOD for 2nd leg |
| `PARTIAL` | TP1 hit, but 2nd leg hit SL/breakeven |
| `SL_HIT` | SL hit before TP1 — full loss |
| `HARD_EXIT` | Red candle below VWAP — emergency exit |
| `EOD_FLAT` | No TP/SL hit, closed at 3:00 PM |

---

## Lot Exit Ladder — 50/50 Rule (scalable to any lot count)

All 3 SL methods use the **same lot-split rule**. Only the SL behavior on the 2nd leg differs.

**Formula:** `tp1_lots = ceil(lots / 2)`, `tp2_lots = lots − tp1_lots`.
On odd counts the **extra lot goes to TP1** (conservative — book more at the first target).
**No TP3 leg.**

**Special case (lots = 1):** cannot split → **full exit at TP1**. No breakeven step, no TP2 runner.

| Lots | TP1 leg | TP2 leg | Note |
|------|---------|---------|------|
| **1** | 1 lot — full exit at TP1 | 0 lots | Cannot split; no runner. Outcome = TP1_HIT |
| **2** | 1 lot | 1 lot | Clean 50/50 |
| **3** | 2 lots | 1 lot | Odd: extra to TP1 |
| **4** | 2 lots | 2 lots | Clean 50/50 |
| **5** | 3 lots | 2 lots | Odd: extra to TP1 |
| **10** | 5 lots | 5 lots | 50/50 |
| **20** | 10 lots | 10 lots | 50/50 |
| **30** | 15 lots | 15 lots | 50/50 |

> **Implemented in** `src/risk/lot_sizing.compute_lot_split()` — single source of truth for **both paper simulation (5B-A kernel)** and **Phase 8 live orders**.
> Today `position_sizing.nifty_max_lots = 5` and `banknifty_max_lots = 5`; the formula scales unchanged if the cap is raised later.

> **PARTIAL R is lot-dependent:** `PARTIAL R = tp1_fraction × tp1_r`.
> Even lots → `0.5 × tp1_r` (e.g. 0.75R on normal day). 3-lot odd → `(2/3) × 1.5 = 1.0R`.

---

## Paper Trade vs Real Live Order

> **Short answer: The GATES are the same. The EXECUTION is different.**

### What is IDENTICAL in both modes

| Rule | Paper | Real (Phase 8) |
|------|-------|----------------|
| Entry conditions C0–C4 | Same | Same |
| Strike selection priority | Same | Same |
| 20-min episode dedup window | Same | Same |
| Position-open gate | Same | Same |
| 15-min cooldown after SL | Same | Same |
| Same-strike kill after 2 SLs | Same | Same |
| Daily cap (5 trades) | Same | Same |
| Entry window 9:45 AM – 2:30 PM | Same | Same |
| Hard close at 3:00 PM | Same | Same |
| SL / TP1 / TP2 levels | Same | Same |
| Lot split at TP1 (`ceil(lots/2)`, lots=1 → full exit) | Same (virtual) | Same (real orders) |

### What is DIFFERENT

| Aspect | Paper Trade | Real Live Order |
|--------|-------------|-----------------|
| Execution | Virtual — no broker call. P&L simulated from candles after market close | Real LIMIT/MARKET order placed via Kite/Upstox API |
| Which strikes | `paper_order_strikes` — currently **ATM only** | `order_strikes` — currently **ATM only** |
| Circuit breaker SL cap | `paper_trading.circuit_breaker_sl_count: 5` | `circuit_breakers.max_sl_per_day: 3` |
| When outcome is known | EOD — replayed from historical candles at dashboard sync | Real-time — broker fill/SL/TP callback |
| Lot split at TP1 | Virtual P&L weighted by `ceil(lots/2)` / remainder | Two real broker orders |
| Current status | **LIVE NOW** (logging to paper_trades.jsonl) | **Phase 8 — NOT built yet** |

### Key difference: alert strikes vs paper/order strikes

```
alert_strikes:         ITM2=ON  ITM1=ON  ATM=ON   ← all 3 fire Telegram alerts
paper_order_strikes:   itm=OFF  atm=ON   otm=OFF  ← only ATM becomes a paper trade
```

> If an **ITM1 alert fires** → Telegram alert goes out → but paper trade is **SKIPPED** (ITM bucket is OFF in config).
> Only **ATM alerts become paper trades** today.

---

*Last updated: 2026-06-27*
