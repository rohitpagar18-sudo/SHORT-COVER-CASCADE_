"""Persistent state manager — Phase 0 stubs.

Tracks daily SL count, cumulative loss, cooldown windows, and killed strikes.
Real implementation arrives in Phase 4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def load_state() -> dict[str, Any]:
    # TODO: Phase 4 — load logs/state.json
    raise NotImplementedError("TODO: Phase 4")


def save_state(state: dict[str, Any]) -> None:
    # TODO: Phase 4 — atomically write logs/state.json
    raise NotImplementedError("TODO: Phase 4")


def increment_sl_count() -> int:
    # TODO: Phase 4
    raise NotImplementedError("TODO: Phase 4")


def reset_daily_state() -> None:
    # TODO: Phase 4 — called at start of new trading session
    raise NotImplementedError("TODO: Phase 4")


def is_strike_killed(strike: int) -> bool:
    # TODO: Phase 4
    raise NotImplementedError("TODO: Phase 4")


def kill_strike(strike: int) -> None:
    # TODO: Phase 4 — mark strike dead for the day (2 SLs on same strike)
    raise NotImplementedError("TODO: Phase 4")


def add_loss(amount: float) -> float:
    # TODO: Phase 4 — accumulate daily loss in rupees
    raise NotImplementedError("TODO: Phase 4")


def get_daily_sl_count() -> int:
    # TODO: Phase 4
    raise NotImplementedError("TODO: Phase 4")


def get_daily_loss() -> float:
    # TODO: Phase 4
    raise NotImplementedError("TODO: Phase 4")


def get_cooldown_until() -> datetime | None:
    # TODO: Phase 4 — earliest time a new entry is allowed after last SL
    raise NotImplementedError("TODO: Phase 4")
