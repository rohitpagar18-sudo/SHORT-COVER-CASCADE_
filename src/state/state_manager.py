"""Persistent daily state manager.

Tracks one trading day's state: SL count, cumulative loss/profit,
cooldown after last SL, killed strikes (>= max_sl_per_strike SLs on the
same strike), trade list, and the circuit-breaker flag.

Writes are ATOMIC: serialise to ``logs/state.json.tmp`` then rename to
``logs/state.json``. A crash mid-write cannot corrupt the live state file.

All timestamps are IST (Asia/Kolkata). The state auto-resets on the
first ``load_state`` call of a new trading day.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Strategy doc Section 13: "Same strike has NOT been stopped out twice today."
# i.e. a strike is "killed" once it accumulates >= 2 SLs.
MAX_SL_PER_STRIKE = 2


@dataclass
class TradeRecord:
    """One completed trade for today's log."""

    timestamp: str             # ISO IST
    symbol: str
    strike: int
    option_type: str           # "CE" or "PE"
    entry: float
    sl: float
    exit_price: float
    exit_type: str             # "SL" / "TP1" / "TP2" / "MANUAL" / "TIME"
    pnl_rupees: float
    re_entry_number: int


@dataclass
class DailyState:
    """State for ONE trading day. Resets at session start each new IST day."""

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


def _strike_key(symbol: str, strike: int, option_type: str) -> str:
    return f"{symbol.strip().upper()}_{int(strike)}_{option_type.strip().upper()}"


def _serialise(state: DailyState) -> dict:
    return asdict(state)


def _deserialise(raw: dict) -> DailyState:
    """Build a DailyState from a JSON dict.

    Trades are kept as raw dicts (we don't currently rebuild ``TradeRecord``
    instances from disk — the bot only appends to ``trades_today``; reads
    from this list are for logging and EOD summaries).
    """
    return DailyState(
        trading_date=raw["trading_date"],
        sl_count=raw.get("sl_count", 0),
        total_loss_rupees=float(raw.get("total_loss_rupees", 0.0)),
        total_profit_rupees=float(raw.get("total_profit_rupees", 0.0)),
        last_sl_hit_timestamp=raw.get("last_sl_hit_timestamp"),
        killed_strikes=dict(raw.get("killed_strikes", {})),
        re_entry_count=raw.get("re_entry_count", 0),
        trades_today=list(raw.get("trades_today", [])),
        circuit_breaker_triggered=bool(raw.get("circuit_breaker_triggered", False)),
        circuit_breaker_reason=raw.get("circuit_breaker_reason"),
    )


class StateManager:
    """Reads / writes ``logs/state.json`` atomically.

    Construct once at bot startup, then call ``load_state()`` to materialise
    today's state. Every mutation method automatically persists to disk
    before returning, so a crash never loses more than the in-flight call.
    """

    def __init__(self, state_file: str | Path = "logs/state.json"):
        self.state_file = Path(state_file)
        self._state: Optional[DailyState] = None

    # ----- time helpers (overridable in tests via monkeypatch) -----

    def _now_ist(self) -> datetime:
        return datetime.now(IST)

    def _get_today_ist(self) -> date:
        return self._now_ist().date()

    def _now_ist_iso(self) -> str:
        return self._now_ist().isoformat()

    # ----- public load / save -----

    def load_state(self) -> DailyState:
        """Load today's state from disk, creating/resetting as needed.

        If the state file is missing OR its ``trading_date`` is not today
        (IST), a fresh ``DailyState`` for today is created and persisted.
        """
        today = self._get_today_ist().isoformat()
        if not self.state_file.exists():
            self._state = DailyState(trading_date=today)
            self.save_state()
            return self._state
        try:
            with self.state_file.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            loaded = _deserialise(raw)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            # Corrupt or out-of-shape state — start fresh.
            self._state = DailyState(trading_date=today)
            self.save_state()
            return self._state

        if loaded.trading_date != today:
            # New trading day — reset.
            self._state = DailyState(trading_date=today)
            self.save_state()
            return self._state

        self._state = loaded
        return self._state

    def save_state(self) -> None:
        """Atomic write — serialise to ``.tmp`` then rename to the live file."""
        if self._state is None:
            raise RuntimeError("StateManager.save_state() called before load_state()")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        payload = json.dumps(_serialise(self._state), indent=2, ensure_ascii=False)
        with tmp.open("w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                # fsync not available on some platforms/streams — best-effort.
                pass
        os.replace(tmp, self.state_file)

    # ----- mutations -----

    def increment_sl_count(self, symbol: str, strike: int, option_type: str) -> None:
        """Record one SL hit: increment counters, update cooldown timer."""
        self._ensure_loaded()
        assert self._state is not None
        self._state.sl_count += 1
        self._state.last_sl_hit_timestamp = self._now_ist_iso()
        key = _strike_key(symbol, strike, option_type)
        self._state.killed_strikes[key] = self._state.killed_strikes.get(key, 0) + 1
        self.save_state()

    def add_loss(self, amount_rupees: float) -> None:
        """Add to today's total loss. Positive amount (in rupees)."""
        self._ensure_loaded()
        assert self._state is not None
        self._state.total_loss_rupees += float(amount_rupees)
        self.save_state()

    def add_profit(self, amount_rupees: float) -> None:
        """Add to today's total profit."""
        self._ensure_loaded()
        assert self._state is not None
        self._state.total_profit_rupees += float(amount_rupees)
        self.save_state()

    def record_trade(self, trade: TradeRecord) -> None:
        """Append a completed trade to today's log."""
        self._ensure_loaded()
        assert self._state is not None
        self._state.trades_today.append(asdict(trade))
        self.save_state()

    def trigger_circuit_breaker(self, reason: str) -> None:
        """Halt trading for the rest of the day."""
        self._ensure_loaded()
        assert self._state is not None
        self._state.circuit_breaker_triggered = True
        self._state.circuit_breaker_reason = reason
        self.save_state()

    def increment_re_entry(self) -> None:
        """Bump the day's re-entry counter (call right before a re-entry order)."""
        self._ensure_loaded()
        assert self._state is not None
        self._state.re_entry_count += 1
        self.save_state()

    def reset_daily_state(self) -> None:
        """Explicit reset (rare — ``load_state`` auto-resets on date change)."""
        today = self._get_today_ist().isoformat()
        self._state = DailyState(trading_date=today)
        self.save_state()

    # ----- read-only queries -----

    def get_daily_sl_count(self) -> int:
        self._ensure_loaded()
        assert self._state is not None
        return self._state.sl_count

    def get_daily_loss(self) -> float:
        self._ensure_loaded()
        assert self._state is not None
        return self._state.total_loss_rupees

    def get_daily_profit(self) -> float:
        self._ensure_loaded()
        assert self._state is not None
        return self._state.total_profit_rupees

    def get_strike_sl_count(
        self, symbol: str, strike: int, option_type: str
    ) -> int:
        self._ensure_loaded()
        assert self._state is not None
        return self._state.killed_strikes.get(
            _strike_key(symbol, strike, option_type), 0
        )

    def is_strike_killed(
        self, symbol: str, strike: int, option_type: str
    ) -> bool:
        """True if this strike has accumulated >= MAX_SL_PER_STRIKE SLs today."""
        return self.get_strike_sl_count(symbol, strike, option_type) >= MAX_SL_PER_STRIKE

    def get_cooldown_remaining_seconds(self, cooldown_minutes: int = 15) -> int:
        """Return seconds left in the post-SL cooldown.

        Returns 0 if no SL has been hit today or the cooldown has elapsed.
        """
        self._ensure_loaded()
        assert self._state is not None
        if not self._state.last_sl_hit_timestamp:
            return 0
        last = datetime.fromisoformat(self._state.last_sl_hit_timestamp)
        if last.tzinfo is None:
            last = last.replace(tzinfo=IST)
        cooldown_until = last + timedelta(minutes=cooldown_minutes)
        delta = (cooldown_until - self._now_ist()).total_seconds()
        return max(0, int(delta))

    def is_in_cooldown(self, cooldown_minutes: int = 15) -> bool:
        return self.get_cooldown_remaining_seconds(cooldown_minutes) > 0

    def can_re_enter(
        self, config, symbol: str, strike: int, option_type: str
    ) -> tuple[bool, str]:
        """Check ALL re-entry rules (strategy doc Sections 13 and 14).

        Returns:
            (allowed, reason). When ``allowed`` is False, ``reason``
            explains which guardrail tripped.
        """
        self._ensure_loaded()
        assert self._state is not None

        if self._state.circuit_breaker_triggered:
            return (
                False,
                f"Circuit breaker triggered: "
                f"{self._state.circuit_breaker_reason or 'no reason recorded'}",
            )

        if config.circuit_breakers.daily_sl_count_breaker:
            max_sl = config.circuit_breakers.max_sl_per_day
            if self._state.sl_count >= max_sl:
                return (
                    False,
                    f"Daily SL count {self._state.sl_count} >= cap {max_sl}",
                )

        if config.circuit_breakers.daily_loss_breaker:
            max_loss = config.circuit_breakers.max_loss_per_day_rupees
            if self._state.total_loss_rupees >= max_loss:
                return (
                    False,
                    f"Daily loss ₹{self._state.total_loss_rupees:.2f} "
                    f">= cap ₹{max_loss:.2f}",
                )

        cooldown_minutes = config.re_entry.cooldown_minutes_after_sl
        remaining = self.get_cooldown_remaining_seconds(cooldown_minutes)
        if remaining > 0:
            return (
                False,
                f"In cooldown — {remaining}s remaining "
                f"({cooldown_minutes}-min window after last SL)",
            )

        if (
            config.re_entry.same_strike_kill_after_2_sl
            and self.is_strike_killed(symbol, strike, option_type)
        ):
            return (
                False,
                f"Strike {_strike_key(symbol, strike, option_type)} "
                f"already stopped out {MAX_SL_PER_STRIKE} times today",
            )

        return (True, "Re-entry permitted")

    # ----- internals -----

    def _ensure_loaded(self) -> None:
        if self._state is None:
            self.load_state()
