# Phase 4 — Risk + State + Strike Selector

**Goal:** Implement the SL/TP/lot-sizing math, daily state tracking
(SL counter, cooldown, killed strikes), and the smart strike selector
(ITM/ATM/OTM scanning). Also bundle three small fixes left over from
Phase 3 verification.

**Time estimate:** 2 hours code + 30 min verification.

**Output:**
- `src/risk/` package — SL Method 1 & 2, VIX regime, TP, lot sizing
- `src/state/` package — daily counters, cooldowns, killed strikes,
  persistent state.json
- `src/data/strike_selector.py` — returns ITM/ATM/OTM strike list
- `scripts/check_risk.py` — preview SL/TP/lots for hypothetical entry
- 3 bug fixes: pattern detection, expiry list count, `--strike ATM`
- Updated `config.yaml` with friendly comments on every section
- ~25 new unit tests (target: ~100 total passing)

**What Phase 4 does NOT do:**
- No Telegram alerts (Phase 5)
- No main orchestrator loop (Phase 5)
- No order placement (Phase 8)

---

## STEP 1 — Manually update config.yaml (Machine 1)

Replace `config/config.yaml` with the user-friendly version below. Every
section now has plain-English comments explaining what each setting does.

```yaml
# =====================================================
#  SHORT COVER CASCADE — Master Control File
# =====================================================
#  Edit this file to change bot behavior.
#  Bot reads config at startup AND between every 5-min candle scan.
#  Exceptions (require bot restart):
#    - feeds.active_feed  (broker switch)
#    - mode.order_place_mode  (safety)
# =====================================================


# ---------- BROKER FEED SELECTION ----------
# Which broker the bot uses for live data and (later) orders.
# Only ONE feed is active at a time. The other doesn't touch the API.
feeds:
  active_feed: kite          # Options: kite OR upstox
  healthcheck_timeout_seconds: 10
  
  upstox:
    enabled: ON              # ON = available to switch to. OFF = totally disabled.
    token_validity_days: 365 # 365 = use Upstox Analytics tab long-token (no daily refresh)
                             # 1   = daily OAuth refresh required
  kite:
    enabled: ON
    token_validity_days: 1   # SEBI rule: Kite tokens expire daily for individuals.
                             # Run scripts/refresh_token_kite.py every morning.


# ---------- MODE CONTROLS (most-changed settings) ----------
# These are the master switches. Change these frequently as you progress
# through phases.
mode:
  alert_mode: ON             # ON = send Telegram alerts on valid signals
  order_place_mode: OFF      # ON = place real orders (Phase 8 only, requires restart)
  paper_trade_mode: ON       # ON = simulate orders in logs only, no real money


# ---------- INSTRUMENT SELECTION ----------
# Which underlyings the bot watches. Disable one to focus on the other.
instruments:
  nifty_enabled: ON
  banknifty_enabled: ON
  
  # Lot sizes — bot auto-verifies these from Kite/Upstox at 9:15 AM.
  # If broker reports a different value, bot logs a warning and uses broker value.
  nifty_lot_size: 65
  banknifty_lot_size: 30


# ---------- STRIKE SELECTION ----------
# Which strikes around ATM the bot scans on every 5-min candle close.
# ATM = nearest strike to current spot
# ITM = one strike in-the-money (deeper-value, higher delta, earlier signals)
# OTM = one strike out-of-the-money (cheaper, faster moves, original strategy default)
strike:
  max_deviation_from_atm: 1            # Hard cap — never go beyond ± 1 strike
  late_entry_threshold_percent: 30     # If option is >30% above VWAP already, skip (chasing)
  
  # Which strikes to SCAN and ALERT on (Phase 5+).
  # NOTE: This block was rewritten in Phase 5B from the original 3-way
  # (itm/atm/otm) schema to seven per-level booleans. Each strike depth
  # is now an independent ON/OFF toggle. Non-contiguous combos are
  # allowed (e.g. itm1 ON, itm2 OFF, itm3 ON).
  alert_strikes:
    itm3: OFF                          # Alert on ITM-3 strike
    itm2: ON                           # Alert on ITM-2 strike
    itm1: ON                           # Alert on ITM-1 strike
    atm:  ON                           # Alert on ATM strike
    otm1: OFF                          # Alert on OTM-1 strike
    otm2: OFF                          # Alert on OTM-2 strike
    otm3: OFF                          # Alert on OTM-3 strike
  
  # Which strikes to AUTO-ORDER on (Phase 8+ only)
  # Safer to start with ATM only. Add others after you trust the bot.
  order_strikes:
    itm: OFF                           # Start OFF — enable after gaining confidence
    atm: ON                            # ATM is the safest default to auto-order
    otm: OFF                           # Start OFF — enable after gaining confidence


# ---------- STOP LOSS CONTROL ----------
# How the bot computes the SL price after a valid signal.
stop_loss:
  method: 1                            # 1 = point buffer (default, from strategy doc)
                                       # 2 = percentage-based (alternative)
  use_vix_multiplier: ON               # ON = multiply SL buffer by VIX regime factor
                                       # OFF = use base buffer only (riskier in high vol)
  hard_exit_red_candle_below_vwap: ON  # ON = exit immediately if full red candle below VWAP
                                       #     (overrides SL — emergency rule)


# ---------- RISK / REWARD ----------
# How much to risk per trade and where to exit profitably.
risk_reward:
  target_risk_per_trade: 3000          # Target ₹ risk per trade (sweet spot)
  risk_range_min: 2500                 # Acceptable lower bound (don't trade if below)
  risk_range_max: 3500                 # Acceptable upper bound (cap)
  
  # TP multipliers (R = entry price − SL price; TP = entry + R × multiplier)
  normal_day_tp1_r: 1.5                # Non-expiry: first exit at 1.5R
  normal_day_tp2_r: 2.5                # Non-expiry: final exit at 2.5R
  expiry_day_tp1_r: 2.0                # Expiry day: first exit at 2.0R (bigger targets)
  expiry_day_tp2_r: 3.0                # Expiry day: final exit at 3.0R
  
  move_sl_to_breakeven_after_tp1: ON   # After TP1, move remaining SL to entry price
  trail_sl_after_tp1: OFF              # Optional: trail SL to previous candle low


# ---------- POSITION SIZING ----------
# How many lots to take per trade.
position_sizing:
  lot_cap_enabled: ON                  # ON = enforce hard caps below (recommended)
  nifty_max_lots: 5                    # Hard ceiling for NIFTY
  banknifty_max_lots: 3                # Hard ceiling for BankNifty
  # If OFF: lots determined only by ₹3000 risk formula (risky for cheap premiums)


# ---------- DAILY CIRCUIT BREAKERS ----------
# Kill switches that stop trading for the day. First trigger wins.
circuit_breakers:
  daily_sl_count_breaker: ON           # ON = stop after N stop-losses
  max_sl_per_day: 2                    # Stop the day after 2 SL hits
  
  daily_loss_breaker: ON               # ON = stop after ₹X cumulative loss
  max_loss_per_day_rupees: 6000        # Stop the day if total loss >= ₹6000


# ---------- ORDER PLACEMENT ----------
# How the bot places orders (Phase 8 only — ignored in alert-only mode).
orders:
  order_type: limit                    # Options: limit OR market
  cancel_if_price_touches_tp1: ON      # ON = cancel unfilled limit order if price hits TP1
  fallback_to_market_if_limit_disabled: ON


# ---------- TIME RULES ----------
# All times in IST (Asia/Kolkata).
time_rules:
  normal_start_time: "09:45"           # No signals before 9:45 (opening noise)
  gap_day_start_time: "10:15"          # On gap-up/down days, wait until 10:15
  
  gap_day_filter_enabled: ON           # ON = use gap day rules
  gap_threshold_percent: 1.0           # Gap day = spot opens >1% from prev close
  
  last_entry_time: "14:30"             # No new entries after 2:30 PM
  soft_squareoff_time: "14:55"         # Start closing positions at 2:55 PM
  hard_squareoff_time: "15:00"         # Hard close (cannot be disabled in code)


# ---------- RE-ENTRY RULES ----------
# Conditions for re-entering after a stop-loss hit.
re_entry:
  cooldown_minutes_after_sl: 15        # Wait at least N minutes after any SL
  same_strike_kill_after_2_sl: ON      # ON = strike is dead-for-the-day after 2 SLs on it


# ---------- CONDITION THRESHOLDS ----------
# Numeric thresholds used inside C0–C4 logic.
conditions:
  c3_rsi_min: 50                       # RSI must be ABOVE this (default 50)
  c3_rsi_max: 80                       # RSI must be BELOW this (overbought guard)


# ---------- TELEGRAM ALERTS (Phase 5) ----------
# Configure which alerts the bot sends to your Telegram chat.
telegram:
  send_signal_alerts: ON               # The main alert when 5/5 conditions pass
  send_rejection_alerts: OFF           # Verbose: also send when conditions fail (debugging)
  send_eod_summary: ON                 # End-of-day summary at 3:30 PM
  send_circuit_breaker_alerts: ON      # When daily SL count / loss cap hit
  send_startup_alert: ON               # When bot starts each morning


# ---------- LOGGING ----------
# How much detail goes into logs/.
logging:
  log_level: INFO                      # DEBUG / INFO / WARNING / ERROR
  log_every_signal_check: ON           # Log every condition evaluation (Phase 6 backtest data)
  log_indicator_values: ON             # Include VWAP/RSI/MAs in each log entry


# ---------- BOT BEHAVIOR ----------
# Internal bot tuning. Usually don't change.
bot:
  scan_buffer_seconds: 5               # Wait 5 sec after candle close before scanning
                                       # (lets Kite's candle data fully sync)
  api_retry_count: 3                   # Retry broker API calls N times on failure
  api_retry_delay_seconds: 2           # Wait N seconds between retries
  state_persistence_enabled: ON        # ON = save daily state to logs/state.json
```

---

## STEP 2 — Paste this prompt into Claude Code (Machine 1)

```cmd
cd C:\trading\short-cover-cascade
claude
```

Paste the entire block below:

````
Read CLAUDE.md fully. Read docs/ShortCoverCascade_v3_1_FINAL.md
Sections 5 (VIX regime), 6 (SL Method 1), 7 (SL Method 2),
8 (Profit Targets), 9 (Position Sizing), 12 (Time Rules),
13 (Re-entry), 14 (Circuit Breakers) before starting.

Then read docs/phases/PHASE_4.md.

Current phase: Phase 4 — Risk + State + Strike Selector.

CRITICAL INSTRUCTION: If any file already exists, OVERWRITE it.
Use load_secrets() helper before load_config() in all scripts.

CRITICAL CORRECTNESS RULES:
1. Every risk function is PURE — takes primitives or dataclasses,
   returns a dataclass result. No I/O, no broker calls.
2. State module reads/writes to logs/state.json. Atomic writes (write 
   to .tmp, rename to .json) so a crash can't corrupt state.
3. All money values are floats — but rounded to 2 decimals when logged.
4. Times are IST (Asia/Kolkata) timezone-aware datetimes.
5. The config schema must be UPDATED to include strike.alert_strikes 
   and strike.order_strikes sub-models (pydantic).

=========================================================
--- TASK 0: Update src/config_loader.py for new config sections ---
=========================================================

Add pydantic models for the new sub-sections:

class AlertStrikesConfig(BaseModel):
    # NOTE: Phase 4 originally shipped the 3-way (itm/atm/otm) schema.
    # Phase 5B (and a later refinement) replaced it with seven
    # per-level booleans so each strike depth can be toggled
    # independently. See docs/phases/PHASE_5B.MD §C for the current
    # schema, defaults, and CE/PE mirroring rules.
    itm3: bool
    itm2: bool
    itm1: bool
    atm:  bool
    otm1: bool
    otm2: bool
    otm3: bool

class OrderStrikesConfig(BaseModel):
    # Phase 8 auto-order schema. Intentionally still 3-way — alert
    # and order are decoupled so we can alert on many depths and
    # order on just ATM.
    itm: bool
    atm: bool
    otm: bool

class StrikeConfig(BaseModel):
    max_deviation_from_atm: int
    late_entry_threshold_percent: float
    alert_strikes: AlertStrikesConfig
    order_strikes: OrderStrikesConfig

Keep all existing models working. Add validators:
- AlertStrikesConfig: at least one of the seven levels must be ON
  (otherwise bot would never alert)
- OrderStrikesConfig: at least one must be ON if mode.order_place_mode
  is ON (validator runs at config load time)
- VIX regime: derived, not set from config (regime is computed from VIX value)

=========================================================
--- TASK 1: Create src/risk/vix_regime.py ---
=========================================================

VIX regime classifier — from strategy doc Section 5.

from dataclasses import dataclass
from enum import Enum

class VixRegime(Enum):
    LOW = "Low Vol"          # VIX below 12
    NORMAL = "Normal"        # VIX 12 - 16
    ELEVATED = "Elevated"    # VIX 16 - 20
    HIGH = "High Vol"        # VIX above 20

@dataclass
class VixRegimeInfo:
    regime: VixRegime
    method1_multiplier: float       # 0.75 / 1.0 / 1.25 / 1.5
    method2_sl_normal_pct: float    # 4 / 5 / 6 / 8
    method2_sl_expiry_pct: float    # 12 / 15 / 18 / 22

def classify_vix(vix_value: float) -> VixRegimeInfo:
    """
    Args:
        vix_value: live India VIX value
    Returns:
        VixRegimeInfo with all multipliers/percentages from strategy doc.
    Boundary rule:
        12.0 itself is NORMAL (not LOW). So "below 12" is strict <.
        20.0 itself is HIGH. So "above 20" is strict >.
        Boundaries at 12, 16, 20 belong to the higher regime.
    """

Hardcode the table from strategy doc Section 5. These values do NOT come 
from config — they're strategy-level constants. (Toggle for VIX adjustment 
ON/OFF lives in config; the actual numbers don't.)

=========================================================
--- TASK 2: Create src/risk/stop_loss.py ---
=========================================================

Two SL methods from strategy doc Section 6 & 7.

from dataclasses import dataclass

@dataclass
class SLResult:
    sl_price: float
    method: int                    # 1 or 2
    base_buffer: float             # method 1: in points; method 2: 0
    vix_multiplier: float          # 0.75 / 1.0 / 1.25 / 1.5, or 1.0 if disabled
    final_buffer_or_pct: float     # actual buffer used (after VIX adjustment)
    reason: str                    # human-readable explanation

# Strategy doc Section 6 — NIFTY base buffer tables
NIFTY_NORMAL_DAY_BUFFER = [
    # (price_min, price_max_exclusive, buffer_points)
    (50, 100, 5),
    (100, 200, 10),
    (200, 400, 15),
    (400, float("inf"), 20),
]
NIFTY_EXPIRY_DAY_BUFFER = [
    (50, 100, 15),
    (100, 200, 20),
    (200, 400, 25),
    (400, float("inf"), 35),
]
BANKNIFTY_NORMAL_DAY_BUFFER = [
    (50, 100, 8),
    (100, 200, 15),
    (200, 400, 22),
    (400, float("inf"), 30),
]
BANKNIFTY_EXPIRY_DAY_BUFFER = [
    (50, 100, 20),
    (100, 200, 28),
    (200, 400, 35),
    (400, float("inf"), 45),
]

def get_base_buffer(symbol: str, option_price: float, is_expiry_day: bool) -> float:
    """Look up base buffer from the tables above. Raises if symbol unknown."""

def compute_sl_method1(
    vwap_at_entry: float,
    option_price: float,
    symbol: str,
    is_expiry_day: bool,
    vix_info: VixRegimeInfo,
    use_vix_multiplier: bool,
) -> SLResult:
    """
    SL = VWAP - (base_buffer * vix_multiplier if enabled else 1.0)
    
    If option price is below 50, raise ValueError (strategy doesn't 
    cover that range — option too cheap).
    """

def compute_sl_method2(
    vwap_at_entry: float,
    is_expiry_day: bool,
    vix_info: VixRegimeInfo,
) -> SLResult:
    """
    SL = VWAP - (VWAP * SL_PERCENT)
    SL_PERCENT comes from VIX regime (already includes regime multiplier).
    """

def check_hard_exit_red_candle(
    candle_open: float,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    vwap_at_entry: float,
) -> tuple[bool, str]:
    """
    Strategy doc: 'If complete red candle body forms entirely below VWAP 
    -> exit immediately even if SL not hit.'
    
    Returns (should_exit, reason).
    """

=========================================================
--- TASK 3: Create src/risk/profit_targets.py ---
=========================================================

TP calculator from strategy doc Section 8.

from dataclasses import dataclass

@dataclass
class TPResult:
    tp1: float
    tp2: float
    risk_per_unit: float      # entry - sl
    risk_to_tp1_ratio: float  # 1.5 or 2.0
    risk_to_tp2_ratio: float  # 2.5 or 3.0
    is_expiry_day: bool

def compute_tps(
    entry_price: float,
    sl_price: float,
    is_expiry_day: bool,
    config,                    # AppConfig
) -> TPResult:
    """
    R = entry - sl
    
    If expiry day:
        TP1 = entry + R * config.risk_reward.expiry_day_tp1_r  (default 2.0)
        TP2 = entry + R * config.risk_reward.expiry_day_tp2_r  (default 3.0)
    Else:
        TP1 = entry + R * config.risk_reward.normal_day_tp1_r  (default 1.5)
        TP2 = entry + R * config.risk_reward.normal_day_tp2_r  (default 2.5)
    
    Raise ValueError if R <= 0 (SL above entry — invalid).
    """

=========================================================
--- TASK 4: Create src/risk/lot_sizing.py ---
=========================================================

Lot sizing from strategy doc Section 9. Three-layer risk control:
1. Primary: ₹3000 risk per trade
2. Secondary: lot cap (5 NIFTY / 3 BankNifty)
3. Outer: daily loss cap (handled by state module)

from dataclasses import dataclass
import math

@dataclass
class LotSizeResult:
    lots: int
    units: int                  # lots * lot_size
    risk_per_unit: float        # entry - sl
    total_risk_rupees: float    # units * risk_per_unit
    capped_by_lot_limit: bool   # True if hit the 5/3 cap
    capped_by_risk_range: bool  # True if total_risk outside 2500-3500
    reason: str

def compute_lots(
    entry_price: float,
    sl_price: float,
    symbol: str,
    lot_size: int,             # 65 for NIFTY, 30 for BankNifty
    config,                    # AppConfig
) -> LotSizeResult:
    """
    Step 1: risk_per_unit = entry - sl
    Step 2: raw_lots = floor(target_risk / (risk_per_unit * lot_size))
    Step 3: lots = max(1, raw_lots)  # floor at 1
    Step 4: if config.position_sizing.lot_cap_enabled:
              cap = nifty_max_lots or banknifty_max_lots
              lots = min(lots, cap)
    Step 5: total_risk = lots * lot_size * risk_per_unit
    Step 6: if total_risk > risk_range_max -> NOT capped further (already 
            floored by lot logic) but flag capped_by_risk_range = True 
            for logging.
    
    Always round DOWN, never up.
    """

=========================================================
--- TASK 5: Create src/risk/__init__.py ---
=========================================================

Re-export everything for clean imports:

from src.risk.vix_regime import (
    VixRegime, VixRegimeInfo, classify_vix
)
from src.risk.stop_loss import (
    SLResult, compute_sl_method1, compute_sl_method2, 
    check_hard_exit_red_candle, get_base_buffer
)
from src.risk.profit_targets import TPResult, compute_tps
from src.risk.lot_sizing import LotSizeResult, compute_lots

__all__ = [...]

=========================================================
--- TASK 6: Create src/state/state_manager.py (REWRITE) ---
=========================================================

Replace the existing stub. Real implementation with atomic JSON writes.

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
import json
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

@dataclass
class TradeRecord:
    timestamp: str             # ISO IST
    symbol: str
    strike: int
    option_type: str
    entry: float
    sl: float
    exit_price: float
    exit_type: str             # "SL" / "TP1" / "TP2" / "MANUAL" / "TIME"
    pnl_rupees: float
    re_entry_number: int

@dataclass
class DailyState:
    """State for ONE trading day. Resets at 9:15 AM IST."""
    trading_date: str          # YYYY-MM-DD (IST)
    sl_count: int = 0
    total_loss_rupees: float = 0.0
    total_profit_rupees: float = 0.0
    last_sl_hit_timestamp: Optional[str] = None    # ISO IST or None
    killed_strikes: dict = field(default_factory=dict)  # {"NIFTY_24050_CE": 2}
    re_entry_count: int = 0
    trades_today: list = field(default_factory=list)
    circuit_breaker_triggered: bool = False
    circuit_breaker_reason: Optional[str] = None

class StateManager:
    def __init__(self, state_file: str = "logs/state.json"):
        self.state_file = Path(state_file)
        self._state: Optional[DailyState] = None

    def _get_today_ist(self) -> date:
        return datetime.now(IST).date()

    def _now_ist_iso(self) -> str:
        return datetime.now(IST).isoformat()

    def load_state(self) -> DailyState:
        """
        Loads state.json. If trading_date != today (IST), resets to fresh 
        DailyState for today. Saves the reset state.
        """

    def save_state(self) -> None:
        """
        Atomic write: write to state.json.tmp, then rename to state.json.
        Prevents corruption on crash mid-write.
        """

    def increment_sl_count(self, symbol: str, strike: int, option_type: str) -> None:
        """
        Increments daily SL counter.
        Updates last_sl_hit_timestamp.
        Increments same-strike kill counter.
        Saves state.
        """

    def add_loss(self, amount_rupees: float) -> None:
        """Add to today's total_loss_rupees. Saves state."""

    def add_profit(self, amount_rupees: float) -> None:
        """Add to today's total_profit_rupees. Saves state."""

    def record_trade(self, trade: TradeRecord) -> None:
        """Append to trades_today. Saves state."""

    def get_daily_sl_count(self) -> int:
        return self._state.sl_count

    def get_daily_loss(self) -> float:
        return self._state.total_loss_rupees

    def get_cooldown_remaining_seconds(self) -> int:
        """
        Returns seconds remaining in 15-min cooldown after last SL.
        Returns 0 if no SL today or cooldown elapsed.
        Cooldown duration from config.re_entry.cooldown_minutes_after_sl.
        """

    def is_in_cooldown(self, cooldown_minutes: int) -> bool:
        return self.get_cooldown_remaining_seconds() > 0

    def is_strike_killed(self, symbol: str, strike: int, option_type: str) -> bool:
        """True if this strike has been stopped out >= max_sl_per_strike times today."""

    def can_re_enter(self, config, symbol: str, strike: int, option_type: str) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        Checks ALL re-entry rules from strategy doc Section 12:
          - sl_count < max_sl_per_day
          - daily_loss < max_loss_per_day_rupees
          - not in cooldown
          - same strike not killed
          - circuit breaker not triggered
        """

    def trigger_circuit_breaker(self, reason: str) -> None:
        """Marks day as halted. No more trading."""

    def reset_daily_state(self) -> None:
        """Explicit reset (rare — load_state does this automatically on date change)."""

Pattern: every mutation calls save_state() before returning. Performance 
is fine — state.json is tiny (few KB).

=========================================================
--- TASK 7: Create src/state/__init__.py ---
=========================================================

from src.state.state_manager import (
    StateManager, DailyState, TradeRecord
)

__all__ = ["StateManager", "DailyState", "TradeRecord"]

=========================================================
--- TASK 8: Create src/data/strike_selector.py ---
=========================================================

Smart strike selector — returns ITM/ATM/OTM strikes based on config.

from dataclasses import dataclass

@dataclass
class StrikeChoice:
    strike: int
    # Phase 5B+: per-level relation labels.
    relation: str              # "ITM3" / "ITM2" / "ITM1" / "ATM" / "OTM1" / "OTM2" / "OTM3"
                               #  (or legacy "ITM" / "ATM" / "OTM" from get_order_strikes)
    instrument_key: str        # for fetching candles from feed
    trading_symbol: str        # human-readable, e.g. NIFTY2660224050CE

def get_strike_interval(symbol: str) -> int:
    """NIFTY = 50, BANKNIFTY = 100. Never hardcoded in selectors —
    callers always go through this lookup."""

def _select_relation_strikes(
    atm: int,
    interval: int,
    option_type: str,
) -> dict[str, int]:
    """
    Phase 5B+: returns dict with all 7 per-level relations.
      For CE: ITMn = atm - n*interval,  OTMn = atm + n*interval
      For PE: ITMn = atm + n*interval,  OTMn = atm - n*interval
      ATM = atm (same strike on both sides; distinct contracts via
            instrument_key / trading_symbol).
    """

def get_alert_strikes(
    feed, symbol: str, spot_price: float, option_type: str,
    expiry: str, config,
) -> list[StrikeChoice]:
    """
    Returns the list of StrikeChoice objects to ALERT on.
    Reads config.strike.alert_strikes (7 per-level toggles) to decide
    which depths to include. Returned in display order ITM3..ATM..OTM3
    (filtered to the enabled levels).

    Calls feed.get_option_chain() to resolve each strike to
    instrument_key and trading_symbol. If a strike from the calculation
    isn't in the option chain (illiquid, doesn't exist), skip it
    silently with a debug log.
    """

def get_order_strikes(
    feed, symbol: str, spot_price: float, option_type: str,
    expiry: str, config,
) -> list[StrikeChoice]:
    """Same idea but reads config.strike.order_strikes (still the
    legacy 3-way ITM/ATM/OTM schema — Phase 8). Alert and order paths
    are intentionally decoupled."""

=========================================================
--- TASK 9: Create scripts/check_risk.py ---
=========================================================

User-facing utility. Given hypothetical entry + VIX + symbol, shows the 
full risk-management picture.

Usage:
  python scripts/check_risk.py --symbol NIFTY --entry 152.50 \
      --vwap 150 --vix 14.2 --expiry-day false

Steps:
1. load_secrets(), load_config()
2. Classify VIX -> VixRegimeInfo
3. Get base buffer from tables
4. Compute SL Method 1 and Method 2 (show both)
5. Compute TP1 and TP2 (for normal/expiry as flagged)
6. Compute lots for both SL methods
7. Print formatted comparison table

Output format:
  ============================================================
    Risk Preview — NIFTY @ entry ₹152.50
    VWAP ₹150.00, VIX 14.2 (Normal Regime, 1.0×)
    Day type: Non-expiry
  ============================================================
  Method 1 (Point Buffer):
    Base buffer: 10 points (NIFTY 100-200 range)
    VIX-adjusted: 10 × 1.0 = 10 points
    SL price: 140.00
    Risk per unit: ₹12.50
    Lots: 3  (capped by ₹3000 target)
    Total risk: ₹2,437.50  (3 × 65 × 12.50)
    TP1: ₹171.25 (1.5R, exit 50%)
    TP2: ₹183.75 (2.5R, exit 50%)
  
  Method 2 (Percentage):
    SL %: 5%  (Normal regime)
    SL price: 142.50
    Risk per unit: ₹10.00
    Lots: 4  (capped by lot cap = 5)
    Total risk: ₹2,600.00
    TP1: ₹167.50 (1.5R)
    TP2: ₹177.50 (2.5R)
  ============================================================

=========================================================
--- TASK 10: BUG FIXES from Phase 3 verification ---
=========================================================

BUG FIX A: Pattern detection in scripts/list_expiries.py is wrong.
Currently labels NIFTY as "monthly last-Tuesday" when it has weekly 
Tuesdays. Fix logic:

def detect_pattern(expiries: list[date]) -> str:
    """
    From a sorted list of expiry dates, derive the pattern label.
    
    Logic:
    - If consecutive expiries are exactly 7 days apart (most pairs), 
      it has weekly contracts.
    - If consecutive expiries are 21-35 days apart, it's monthly only.
    - If MIXED (some 7-day, some 4-week gaps), it's "weekly + monthly".
    
    Examples:
    - NIFTY [May 26, Jun 2, Jun 9, Jun 16] -> all 7-day gaps -> 
      "weekly Tuesday + monthly last-Tuesday"  (because the monthlies 
      are folded into the weekly stream — every last-Tuesday IS both)
    - BANKNIFTY [May 26, Jun 30, Jul 28, Sep 29] -> ~28-day gaps -> 
      "monthly last-Tuesday"
    
    Detected pattern is purely from data — no day-of-week assumed.
    """

Also bump the next-N-expiries display from 4 to 8 so the user can spot 
gaps. Bump get_expiry_summary() default to return 8 expiries.

BUG FIX B: scripts/check_conditions.py — support --strike ATM 
(and ATM+1, ATM-1)

Currently argparse rejects "ATM" since type=int. Change to:
  parser.add_argument("--strike", type=str, required=True,
      help="Strike price (e.g. 24050) or ATM / ATM+1 / ATM-1")

Then in main(), parse the value:
  if args.strike.upper().startswith("ATM"):
      atm = feed.get_atm_strike(args.symbol)
      interval = get_strike_interval(args.symbol)
      if args.strike.upper() == "ATM":
          strike = atm
      elif args.strike.upper() == "ATM+1":
          strike = atm + interval
      elif args.strike.upper() == "ATM-1":
          strike = atm - interval
      else:
          raise ValueError(f"Invalid strike spec: {args.strike}")
  else:
      strike = int(args.strike)

Same fix in scripts/check_indicators.py — accept "ATM", "ATM+1", "ATM-1".

BUG FIX C: scripts/list_expiries.py — add expiry COUNT diagnostic.

Add an optional flag --all that prints ALL expiries Kite returns, not 
just the next 8. This will help debug the "August missing for BankNifty" 
question — we'll see if Kite genuinely doesn't have August or if our 
filter is dropping it.

=========================================================
--- TASK 11: Unit tests ---
=========================================================

Create tests/test_risk.py with these tests:

# VIX regime tests
def test_vix_low(): classify_vix(10.5) -> LOW, 0.75×
def test_vix_normal_lower_boundary(): classify_vix(12.0) -> NORMAL
def test_vix_normal(): classify_vix(14.2) -> NORMAL, 1.0×
def test_vix_elevated_boundary(): classify_vix(16.0) -> ELEVATED
def test_vix_elevated(): classify_vix(18.0) -> ELEVATED, 1.25×
def test_vix_high_boundary(): classify_vix(20.0) -> HIGH
def test_vix_high(): classify_vix(25.0) -> HIGH, 1.5×

# SL Method 1 tests (covers all premium bands and both symbols)
def test_sl_m1_nifty_normal_premium100(): ...
def test_sl_m1_nifty_expiry_premium250(): ...
def test_sl_m1_banknifty_normal_premium300(): ...
def test_sl_m1_vix_multiplier_applied(): ...
def test_sl_m1_vix_disabled_via_config(): ...
def test_sl_m1_premium_below_50_raises(): ...

# SL Method 2 tests
def test_sl_m2_normal_day_normal_vix(): ...
def test_sl_m2_expiry_day_elevated_vix(): ...

# Hard exit tests
def test_hard_exit_red_below_vwap(): ...
def test_hard_exit_red_above_vwap_no_exit(): ...
def test_hard_exit_green_no_exit(): ...

# TP tests
def test_tp_normal_day(): entry=152.50, sl=140 -> TP1=171.25, TP2=183.75
def test_tp_expiry_day(): entry=152.50, sl=140 -> TP1=177.50, TP2=190.00
def test_tp_invalid_sl_above_entry_raises(): ...

# Lot sizing tests
def test_lots_nifty_typical(): risk=12.50, target=3000 -> 3 lots (3*65*12.50=2437.50)
def test_lots_banknifty_typical(): ...
def test_lots_capped_by_lot_limit(): cheap option triggers cap at 5
def test_lots_minimum_one(): expensive option with tight SL -> 1 lot floor
def test_lots_round_down_never_up(): ...

# State manager tests (use temp directory)
def test_state_loads_fresh_on_new_day(tmp_path): ...
def test_state_increments_sl(tmp_path): ...
def test_state_killed_strike_after_2_sl(tmp_path): ...
def test_state_cooldown_active(tmp_path): mock now to 5 min after SL
def test_state_cooldown_elapsed(tmp_path): mock now to 16 min after SL
def test_state_circuit_breaker_blocks_re_entry(tmp_path): ...
def test_state_atomic_write_survives_crash(tmp_path): simulate write 
    interruption, verify no corruption
def test_state_persists_across_restarts(tmp_path): create, save, 
    create new manager, verify same state

# Strike selector tests
# NOTE: these were rewritten in Phase 5B for the per-level (ITM3..OTM3)
# schema — see tests/test_phase5b_fixes.py and tests/test_risk.py for
# the current test list.
def test_strikes_ce_atm_plus_minus_1():
    # spot=24030 -> ATM=24050; CE ITMn = atm - n*50, OTMn = atm + n*50.
    pass
def test_strikes_pe_atm_plus_minus_1():
    # PE mirrors: ITMn = atm + n*50, OTMn = atm - n*50.
    pass
def test_strikes_alert_config_filters(): pass  # per-level toggles drop OFF depths
def test_strikes_order_config_filters(): pass  # legacy 3-way schema (Phase 8)

After writing all files, run:
  pytest tests/ -v

Target: ~100 tests passing. Report exact count.

If any tests fail, fix them and re-run before marking phase done.
Report:
1. pytest output (total tests, failures if any)
2. Confirm all new files exist
3. Run scripts/check_risk.py with sample args, paste output
4. Any decisions you had to make on ambiguous strategy doc text
````

---

## STEP 3 — Verification Checklist (Machine 2 — anytime, no live market needed)

```cmd
git pull
call venv\Scripts\activate.bat
pytest tests\ -v
```

Expected: ~100 tests passing.

```cmd
:: Check risk preview script works (no API calls — pure math)
python scripts\check_risk.py --symbol NIFTY --entry 152.50 --vwap 150 --vix 14.2

:: Tomorrow during market hours, test the fixed scripts:
python scripts\refresh_token_kite.py
python scripts\list_expiries.py        # should now show "weekly + monthly" for NIFTY
python scripts\check_conditions.py --symbol NIFTY --strike ATM --option-type CE
```

Verify:
- pytest: ~100 tests pass
- check_risk.py: shows formatted SL/TP/lot preview
- list_expiries.py: NIFTY pattern label now mentions "weekly", not just "monthly last-Tuesday"
- check_conditions.py: accepts `--strike ATM` without error
- BankNifty pattern in list_expiries.py: still "monthly last-Tuesday" (correct, BankNifty has only monthly)

---

## STEP 4 — When you confirm Phase 4 done, send me

1. Exact pytest test count
2. `check_risk.py` sample output
3. `list_expiries.py` output (now with fixed pattern detection)
4. Any test failures and how Claude Code resolved them
5. Confirmation: are you ready to start a new chat for Phase 5?

If Phase 4 verifies clean → **start a new chat, paste the handoff summary, and request Phase 5.** This is our natural stopping point in this conversation.

---

## What Phase 5 will build (preview for new chat)

- Telegram bot integration (signal alerts, EOD summary, startup, errors)
- main.py orchestrator that runs the 5-min candle close loop:
  9:14 AM lot size verify → on each 5-min close → for each symbol →
  get spot → for each option_type (CE/PE) → check C0 → get strikes →
  for each strike → compute indicators → check all conditions → 
  if all 5 pass → compute risk → log to signals.jsonl → send Telegram
- Re-entry rule integration (uses Phase 4's StateManager)
- Circuit breaker enforcement
- 9:45 AM start, 14:30 last entry, 15:00 hard square-off
- Gap day detection

After Phase 5 + 30 days of live data, you'll have a battle-tested 
alert bot ready for Phase 7 backtest analysis and eventually Phase 8 
auto-orders.

**End of Phase 4.**
