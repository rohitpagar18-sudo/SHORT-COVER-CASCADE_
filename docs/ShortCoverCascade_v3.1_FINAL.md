**SHORT COVER CASCADE STRATEGY**

**v3.1 FINAL**

**1\.**      **NIFTY & BankNifty Options — 5-Minute Timeframe — Alert \+ Auto-Trade Ready**

| Version | 3.1 FINAL |
| :---- | :---- |
| **Instrument** | NIFTY & BankNifty CE or PE (ATM ± 1 strike only) |
| **Timeframe** | 5 minutes |
| **Session** | All trading days, best on weekly expiry |
| **Studies** | VWAP, OI \+ MA(20), RSI(14) \+ MA(20), Volume \+ MA(20), India VIX |
| **Data Source** | Upstox SDK (live) |
| **Mode** | Alert-first via Telegram, auto-order after validation |

 

# **2\. CORE LOGIC IN ONE PARAGRAPH**

Option writers (sellers) get forced to buy back their sold positions when the market moves sharply against them. This forced buying creates a cascade that drives option premium up violently and fast. This strategy detects the START of that cascade using 5 simultaneous conditions (C0 \+ C1 \+ C2 \+ C3 \+ C4). All 5 must be true on the same closed 5m candle for a valid entry signal.

# **3\. STRATEGY TOGGLES (CONFIGURABLE)**

These toggles let the strategy adapt to changing market conditions. Defaults are set for typical conditions and can be changed in the bot config.

| Toggle | Default | Effect When OFF |
| :---- | :---- | :---- |
| VIX regime adjustment | ON | SL uses fixed buffer without VIX multiplier |
| Gap day delay (10:15 AM start) | ON | Normal 9:45 AM start applies on gap days |
| Limit order mode | ON | Falls back to market order at signal candle close |
| SL Method | Method 1 (point buffer) | Switches to Method 2 (percentage) |
| Daily SL circuit breaker | ON | No daily stop, continues all day |
| Same-strike kill after 2 SLs | ON | Same strike can be re-entered all day |
| Lot cap (5 NIFTY / 3 BankNifty) | ON | Lots only limited by ₹3,000 risk formula |
| Daily max loss ₹6,000 cap | ON | Only 2-SL rule applies, no rupee cap |

# **4\. STRIKE SELECTION**

•         Pick the strike nearest to spot at the time of signal

•         ATM is most preferred

•         Maximum deviation allowed: ATM ± 1 strike

•         Deeper OTM \= lower delta \= skip

# **5\. THE 5 CONDITIONS**

**All 5 conditions (C0 \+ C1 \+ C2 \+ C3 \+ C4) must be true on the same closed 5m candle. Any one failing \= no entry.**

## **CONDITION 0 — SPOT TREND FILTER \[C0\]**

This is checked FIRST. If C0 fails, do not even look at the option chart.

**Rules:**

•         For CE trades: NIFTY / BankNifty spot 5m candle CLOSE must be ABOVE its own VWAP

•         For PE trades: NIFTY / BankNifty spot 5m candle CLOSE must be BELOW its own VWAP

*That's it. No buffer zone, no higher-high / lower-low check. Simple above/below VWAP on spot.*

## **CONDITION 1 — OPTION PRICE ABOVE VWAP \[C1\]**

On the option chart:

•         Current 5m candle CLOSE must be above option's own VWAP

•         Candle must be GREEN (close \> open)

•         Red candle closing above VWAP \= invalid, wait for next candle

**Late entry rule: If the candle has moved 30% or more above VWAP already, do not chase. Wait for retracement back near VWAP, then re-check all conditions on a fresh green candle.**

## **CONDITION 2 — OI DECLINING BELOW MA \[C2\] \+ PRICE RISING \[C2\] (COMBINED CHECK)**

**Rule: Option OI green line must close BELOW the red MA(20) line on the signal candle.**

Why this works as a short-covering signal: OI falling \+ price rising \= writers buying back their short positions. The 'price rising' half is already enforced by C1's green-candle requirement, so C2 itself only checks the OI side. Together C1 \+ C2 form the full short-covering confirmation.

Why we don't rely on OI alone: OI can drop simply due to strike rotation as spot moves. Pairing OI decline with C1's green candle ensures we're seeing short covering, not strike migration.

 

C2 to combined form, OR add a one-line note to C2: "Note: C2 logically requires both OI down AND price up. Price-up is enforced via C1's green-candle rule. If C1 is ever modified, restore the price-up check explicitly to C2."

Note: This condition logically depends on price rising in the same candle, which is enforced via C1's green-candle rule. If C1 is ever modified, restore the price-up check explicitly here.

## **OI Interpretation Table (Reference)**

| OI Direction | Price Direction | Meaning | Action |
| :---- | :---- | :---- | :---- |
| Falling | Rising | SHORT COVERING | Valid signal ✓ |
| Rising | Rising | Fresh long buildup | Skip ✗ |
| Falling | Falling | Long unwinding | Skip ✗ |
| Rising | Falling | Fresh short buildup | Skip ✗ |

   
**If OI is NOT below MA → HARD STOP. Do not check C3 or C4.**

## **CONDITION 3 — RSI MOMENTUM ABOVE MA \[C3\]**

**Two valid forms. Both require RSI value \> 50\.**

**FORM A — Fresh Crossover (best):**

•         RSI(14) crosses the red MA(20) line upward on this candle or one candle prior

•         RSI value above 50

**FORM B — Sustained Above MA:**

•         RSI already above MA earlier

•         RSI still clearly above MA

•         RSI value above 50 and rising or flat

**RSI Blockers (any one blocks entry):**

•         RSI above MA but value below 50 → weak momentum → skip

•         RSI value above 80 → overbought → skip

•         RSI above MA but declining sharply → momentum fading → wait

•         RSI below MA → bearish → skip

## **CONDITION 4 — VOLUME ABOVE MA \[C4\]**

•         Current volume bar must be above Volume MA(20)

•         Volume bar must be GREEN (buying volume)

•         Red volume bar above MA \= sellers active, wait one candle

•         Volume bar below MA \= thin market, skip

# **6\. INDIA VIX REGIME SYSTEM**

VIX is read at session start (9:15 AM) via Upstox SDK and fixed for the day. All SL calculations use the VIX regime multiplier (when VIX toggle is ON, which is default).

| India VIX | Regime | Method 1 Multiplier | Method 2 SL% Normal | Method 2 SL% Expiry |
| :---- | :---- | :---- | :---- | :---- |
| Below 12 | Low Vol | 0.75× | 4% | 12% |
| 12 – 16 | Normal | 1.0× | 5% | 15% |
| 16 – 20 | Elevated | 1.25× | 6% | 18% |
| Above 20 | High Vol | 1.5× | 8% | 22% |

   
*Trade log must record VIX value AND regime classification.*

# **7\. STOP LOSS — METHOD 1 (POINT BUFFER, DEFAULT)**

**Formula: SL \= VWAP at entry − (Base Buffer × VIX Multiplier)**

## **Base Buffer — NIFTY**

| Option Price | Normal Day | Expiry Day |
| :---- | :---- | :---- |
| 50 – 100 | VWAP − 5 | VWAP − 15 |
| 100 – 200 | VWAP − 10 | VWAP − 20 |
| 200 – 400 | VWAP − 15 | VWAP − 25 |
| 400+ | VWAP − 20 | VWAP − 35 |

 

## **Base Buffer — BankNifty**

| Option Price | Normal Day | Expiry Day |
| :---- | :---- | :---- |
| 50 – 100 | VWAP − 8 | VWAP − 20 |
| 100 – 200 | VWAP − 15 | VWAP − 28 |
| 200 – 400 | VWAP − 22 | VWAP − 35 |
| 400+ | VWAP − 30 | VWAP − 45 |

   
**Example: NIFTY CE premium 150 on normal day, VIX \= 18 (Elevated → 1.25×):**

•         Base buffer \= 10

•         Adjusted buffer \= 10 × 1.25 \= 12.5 points

•         If VWAP \= 150 → SL \= 137.5

**HARD EXIT RULE: If a complete red candle body forms entirely below VWAP (open, high, low, close all below VWAP) → exit immediately even if SL not hit.**

# **8\. STOP LOSS — METHOD 2 (PERCENTAGE, OPTIONAL)**

**Formula: SL \= VWAP − (VWAP × SL%)**

SL% comes directly from VIX Regime Table (Section 5). Multiplier is embedded in those % values.

**Example (Normal day): VWAP \= 150, VIX \= 14 (Normal → 5%):**

•         SL \= 150 − (150 × 5%) \= 142.5

**Example (Expiry day): VWAP \= 150, VIX \= 18 (Elevated → 18%):**

•         SL \= 150 − (150 × 18%) \= 123

**HARD EXIT RULE: Same as Method 1\.**

# **8A\. STOP LOSS — METHOD 3 (METHOD-1 INITIAL + N-SMA TRAIL)**

> CHANGED 2026-06-08: added SL Method 3 (initial Method-1 SL + 19-SMA trail). The strategy now has three SL methods; the legacy "Optional: trail SL to previous candle low" note under §9 is superseded by this method.
>
> CHANGED 2026-06-19: SL method shadow comparison added — dashboard sync now stamps auto_pnl_method1/2/3 and auto_exit_method1/2/3 columns (analysis-only, decision deferred to Phase 7).

**Formula: initial SL \= Method 1; after activate\_after\_minutes (default 15), SL \= N-period SMA of the option close (default N \= 19), re-evaluated every update\_interval\_minutes (default 15).**

Method 3 is the live trailing model. It keeps the §6/§7 initial SL calculation, fixes the TP1/TP2 levels at entry from `R = entry − initial_SL`, and then replaces the static SL with a slow-moving SMA-based trail so winners keep room and losers cap at the Method-1 floor.

•         Entry SL: Method 1 buffer (NIFTY / BankNifty tables in §7) with VIX multiplier.

•         R, TP1, TP2: fixed at entry from `R = entry − initial_SL` using the §9 multipliers (normal 1.5×/2.5×, expiry 2.0×/3.0×). **Targets do not move with the trail.**

•         Trail activation: `activate_after_minutes` after entry (default 15). The first N min uses the Method-1 SL.

•         Update cadence: `update_interval_minutes` (default 15, matches the real-broker trail-modify cadence). The SL re-evaluates at each tick — NOT on every candle.

•         `follow_direction`:
    – `both` (default): SL \= SMA. Trails the SMA up AND down.
    – `ratchet`: SL \= max(prev\_SL, SMA). Never loosens (only ratchets up).

•         **Continues post-TP1.** After TP1 banks the first 50%, the remaining 50% keeps trailing on the SMA. Method 3 **overrides** `move_sl_to_breakeven_after_tp1` — breakeven does not apply when method=3.

•         **Early-entry fallback.** If fewer than N candles exist when the trail would activate (e.g. activate=15 min with N=19 on a slow start), HOLD the Method-1 SL until N candles are available; never trail on a partial SMA.

•         **HARD EXIT RULE:** unchanged from Methods 1/2.

**Example: NIFTY CE entry ₹150, Method-1 SL ₹140, R \= 10:**

•         Through 10:15: SL \= 140 (Method-1).

•         10:15 trail tick — last 19 closes SMA \= 144 → SL → 144 (both) or max(140, 144) \= 144 (ratchet).

•         10:30 tick — SMA \= 151 → SL → 151 (both) or max(144, 151) \= 151 (ratchet).

•         10:45 tick — SMA \= 148 → SL → 148 (both, loosens by 3) OR 151 (ratchet, holds).

Targets remain TP1 \= 165 and TP2 \= 175 throughout. The remaining 50% after a TP1 hit keeps trailing on the same SMA.

# **9\. PROFIT TARGETS**

**Risk (R) \= Entry Price − SL Price**

## **Expiry Day**

•         TP1 \= Entry \+ (R × 2\) → exit 50%

•         After TP1 → move SL of remaining 50% to BREAKEVEN

•         TP2 \= Entry \+ (R × 3\) → exit remaining 50%

## **Non-Expiry Day**

•         TP1 \= Entry \+ (R × 1.5) → exit 50%

•         After TP1 → move SL of remaining 50% to BREAKEVEN *(Method 1/2 only — Method 3 keeps trailing per §8A)*

•         TP2 \= Entry \+ (R × 2.5) → exit remaining 50%

> CHANGED 2026-06-08: legacy "Optional: trail SL to previous candle low" footnote removed. Trailing is now a dedicated SL method — see §8A (Method 3, 19-SMA trail).

# **10\. POSITION SIZING**

**Target risk per trade: ₹3,000 (range ₹2,500 – ₹3,500)**

## **Lot Sizes**

•         NIFTY: 65 units per lot (current as of 2026\)

•         BankNifty: 30 units per lot (current as of 2026\)

**IMPORTANT: Verify current lot size from NSE / broker before each trading day starts. Lot size revisions are rare (typically once per year or less), but they do happen — when an exchange rebalances index derivatives. The bot config should pull or confirm lot size at session start (9:15 AM) before placing any orders.**

## **Formula**

•         Risk per unit \= Entry Price − SL Price

•         Lots \= ROUND DOWN (3000 / (Risk per unit × Lot Size))

## **Multi-Layer Risk Control**

Position sizing uses three layers working together — not one. All three apply simultaneously:

•         Layer 1 (Primary): ₹3,000 risk-per-trade formula sets default lot count

•         Layer 2 (Secondary safety net): Hard lot cap — 5 lots NIFTY / 3 lots BankNifty

•         Layer 3 (Outer guardrail): Daily ₹6,000 max loss circuit breaker

*Why the lot cap exists despite SL discipline: when option premium is cheap (₹50-100) with a tight SL, the risk-per-unit can be ₹2-3. The formula then produces 15-20+ lots. A single gap or slippage event on that many lots can blow past your SL faster than the daily loss cap can react. The lot cap is a circuit breaker against tail-risk slippage, not a substitute for SL discipline.*

## **Rules**

•         Minimum: 1 lot (hard floor)

•         Maximum: 5 lots NIFTY / 3 lots BankNifty (hard ceiling — toggle can disable)

•         Always round DOWN, never up

•         When in doubt, use 1 lot less than calculated

## **Changelog**

•         risk_range_min is informational only; only risk_range_max is a hard cap.

# **11\. ORDER PLACEMENT**

## **Default: LIMIT ORDER**

1\.       On valid 5-condition signal, calculate SL, TP1, TP2 BEFORE placing order

2\.       Place LIMIT BUY order at the signal candle's close price

3\.       Send Telegram alert with: entry price, SL, TP1, TP2, lots, VIX regime, strike

4\.       Wait for fill

## **Cancel Rule**

**If the limit order is not filled and option price touches TP1 level before fill → CANCEL the order immediately. Do not chase. Wait for a fresh complete 5-condition signal to re-trigger.**

## **Fallback Mode (Toggle OFF)**

If limit order mode is disabled, place MARKET order at signal candle close.

# **12\. TIME RULES**

| Rule | Time | Reason |
| :---- | :---- | :---- |
| No entry before | 9:45 AM | Opening noise, unstable OI |
| Gap day no entry before | 10:15 AM | VWAP needs more data on gap \>1% |
| Last valid entry | 2:30 PM | Hard stop |
| Soft square-off target | 2:55 PM | Begin closing open positions |
| Hard square-off (absolute) | 3:00 PM | No position may be open past this |

   
**Gap day rule: If NIFTY/BankNifty opens more than 1% from previous close, no entries before 10:15 AM. This is a toggle (default ON). Reason: VWAP gets dominated by opening candles on gap days and gives false signals.**

**Expiry day: 9:45 AM rule is critical. Never trade first 30 minutes on expiry.**

# **13\. RE-ENTRY RULES**

Re-entry is allowed if ALL of these are true:

•         Minimum 15-minute cooldown since last SL hit

•         Fresh complete 5-condition signal (C0–C4) on a new candle

•         Daily SL count is under 2

•         Time is before 2:30 PM

•         Same strike has NOT been stopped out twice today

**Same-strike rule: If the same strike is stopped out twice in one session, that strike is dead for the day. Other strikes are still eligible.**

# **14\. DAILY CIRCUIT BREAKERS (WHICHEVER HITS FIRST)**

Two parallel kill switches. The first one to trigger stops trading for the day:

5\.       2 SL hits in one session → stop

6\.       Total daily loss reaches ₹6,000 → stop

**No exceptions. No 'one more try.' Even if 5 perfect signals appear after either trigger, skip.**

# **15\. BLOCKERS (ANY ONE BLOCKS THE TRADE)**

•         ✗ Time before 9:45 AM (or 10:15 AM on gap day)

•         ✗ Time after 2:30 PM

•         ✗ C0 fails (spot direction wrong)

•         ✗ OI green line above red MA (C2 fails)

•         ✗ RSI below 50 even if above MA

•         ✗ RSI above 80

•         ✗ Signal candle is RED body

•         ✗ Volume bar below MA

•         ✗ Red volume bar even if above MA

•         ✗ Strike deeper than ATM ± 1

•         ✗ Less than 30 min to expiry close

•         ✗ Only 4 of 5 conditions met (must be all 5\)

•         ✗ 2 SL hits already today

•         ✗ Daily loss already at ₹6,000

•         ✗ Less than 15 min since previous SL hit

•         ✗ Same strike already stopped out twice today

# **16\. ENTRY EXECUTION FLOW (FOR BOT / AI / HUMAN)**

Execute these steps in exact order when scanning each closed 5m candle:

7\.       Verify NIFTY/BankNifty lot size matches config (pull from broker/NSE at session start, 9:15 AM)

8\.       Check time window (9:45 AM – 2:30 PM, or 10:15 AM start on gap day)

9\.       Check daily SL count (under 2\) and daily loss (under ₹6,000)

10\.   Check cooldown (15 min since last SL hit if any)

11\.   Read India VIX → determine regime

12\.   Check C0 on spot: above VWAP for CE, below VWAP for PE

13\.   If C0 fails → wait for next candle

14\.   Identify ATM ± 1 strike for CE (if spot up) or PE (if spot down)

15\.   Check same-strike rule (not stopped out twice today)

16\.   Check C1 on option: green candle close above option VWAP

17\.   Check C2: OI green line closed below red MA(20)

18\.   Check C3: RSI above MA(20) and RSI \> 50 and RSI \< 80

19\.   Check C4: green volume bar above Volume MA(20)

20\.   If any check fails → wait for next candle

21\.   All checks pass → calculate VWAP, SL (Method 1 or 2), R, lots, TP1, TP2

22\.   Verify lots within hard cap (5 NIFTY / 3 BankNifty) if toggle ON

23\.   Place LIMIT order at signal candle close

24\.   Send Telegram alert with full trade details

25\.   Monitor for fill OR price touching TP1 (cancel trigger)

26\.   On fill: place SL bracket order immediately

27\.   On TP1 hit: exit `tp1_lots` (= `ceil(total_lots / 2)`).
       If `tp2_lots > 0`: move SL to breakeven (Method 1/2) or keep trailing (Method 3), monitor TP2.
       If `tp2_lots == 0` (single-lot trade): position fully closed — no breakeven, no TP2 monitoring.

28\.   On TP2 hit: exit remaining `tp2_lots`, log trade.

**Lot exit rule (50/50, scalable to any lot count):**
`tp1_lots = ceil(total_lots / 2)`, `tp2_lots = total_lots − tp1_lots`.
Odd counts: extra lot exits at TP1. No TP3 leg. No other split modes.
Implemented in `src/risk/lot_sizing.compute_lot_split()` — used by both
paper simulation (5B-A kernel) and Phase 8 live orders.

29\.   On SL hit: exit, increment daily SL counter, start 15-min cooldown timer, mark strike (if 2nd SL on same strike)

30\.   Soft exit at 2:55 PM: begin closing any open position

31\.   Hard deadline 3:00 PM: no position may remain open past 3:00 PM regardless of P\&L

# **17\. TELEGRAM ALERT FORMAT (SUGGESTED)**

Realistic example using current 2026 lot size (NIFTY \= 65):

🚨 SHORT COVER CASCADE SIGNAL

─────────────────────────────

Instrument: NIFTY 24500 CE

Date: 2026-05-20 | Time: 10:35 AM

Day Type: Normal (Non-Expiry)

VIX: 14.2 (Normal Regime, 1.0×)

Spot: 24530 (Above VWAP ✓)

Lot Size: 65 (verified at 9:15 AM)

 

ENTRY: ₹152.50 (LIMIT)

SL: ₹140.00 (Method 1, base −10 × 1.0)

TP1: ₹171.25 (R × 1.5, exit `tp1_lots` = ceil(lots/2))

TP2: ₹183.75 (R × 2.5, exit `tp2_lots` = lots − tp1_lots)

 

Risk per unit: ₹12.50

Lots: 3 → Total Risk: ₹2,437.50

(3 lots × 65 units × ₹12.50)

 

C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓

─────────────────────────────

Cancel if price touches ₹171.25 before fill.

   
*Note on the lots/risk math: 3 lots × 65 units \= 195 units × ₹12.50 risk per unit \= ₹2,437.50 total risk. This sits within the ₹2,500–₹3,500 target band (slightly under because lot rounding goes DOWN, never up).*

# **18\. TRADE LOG (FILL AFTER EVERY TRADE)**

| Date |   |
| :---- | :---- |
| **Instrument** | NIFTY / BankNifty |
| **Strike** |   |
| **Lot size used** | 65 / 30 / other |
| **India VIX** |   |
| **VIX regime** | Low / Normal / Elevated / High |
| **Day type** | Normal / Expiry / Gap day |
| **Spot direction** | Above / Below VWAP |
| **Entry time** |   |
| **Entry price** |   |
| **VWAP at entry** |   |
| **SL method** | Method 1 / Method 2 |
| **VIX multiplier applied** |   |
| **SL price** |   |
| **Risk per unit (R)** |   |
| **Lots** |   |
| **Total trade risk (₹)** |   |
| **TP1 price** |   |
| **TP2 price** |   |
| **C0 valid** | Y / N |
| **C1 valid** | Y / N |
| **C2 valid** | Y / N |
| **C3 valid** | Y / N |
| **C4 valid** | Y / N |
| **Order type** | Limit / Market |
| **Fill status** | Filled / Cancelled |
| **Exit type** | SL / TP1 only / TP1+TP2 / Manual / Time |
| **Exit price** |   |
| **Net P\&L (₹)** |   |
| **Re-entry \# of day** |   |
| **Notes / Lesson** |   |

# **19\. ONE-LINE SUMMARY**

 

***"Spot above/below VWAP confirms direction, OI closes below MA(20) while a green candle closes above option VWAP (= short covering), RSI is between 50 and 80 and above its MA(20), green volume bar above its MA(20), VIX regime is known, time is within window — only then place limit order."***

 

# **20\. DEPLOYMENT PHASES**

## **Phase 1 (mandatory): Alert-Only Mode**

•         Using Upstox and Bot sends Telegram alerts only, no orders placed

•         Run for minimum 30 trading days

•         Log every alert and what would have happened

•         Compare alert outcomes to manual judgment

## **Phase 2: Auto-Order Mode (only after Phase 1 success)**

•         Move to automated order placement

•         Start with 1-lot minimum for first 2 weeks

•         Scale up only after confirming bot behavior matches expectations

•         Keep all toggles available for quick adjustment

 

 

*End of v3.1 FINAL specification.*

