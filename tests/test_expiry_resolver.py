"""Phase 3 unit tests for ``src.data.expiry_resolver``.

The resolver is broker-agnostic: it consumes whatever
``feed.list_expiries(symbol)`` returns and never assumes a particular
weekday. Tests use a tiny in-memory fake feed instead of mocking
specific broker SDKs.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.data import expiry_resolver
from src.data.base_feed import BaseFeed


class FakeFeed(BaseFeed):
    """Minimal BaseFeed stand-in: only ``list_expiries`` and
    ``get_broker_name`` actually do anything. Other abstract methods
    return placeholder values."""

    def __init__(
        self,
        expiries: dict[str, list[date]] | None = None,
        broker: str = "fake",
    ) -> None:
        self._expiries = expiries or {}
        self._broker = broker
        self.list_expiries_calls = 0

    # Concrete BaseFeed methods we don't exercise — return placeholders.
    def connect(self) -> bool:
        return True

    def is_token_valid(self) -> bool:
        return True

    def get_lot_size(self, symbol: str) -> int:
        return 0

    def get_spot_price(self, symbol: str) -> float:
        return 0.0

    def get_5min_candles(self, instrument_key: str, n_candles: int = 0):
        import pandas as pd

        return pd.DataFrame()

    def get_option_chain(self, symbol: str, expiry: str):
        import pandas as pd

        return pd.DataFrame()

    def get_india_vix(self) -> float:
        return 0.0

    def get_india_vix_with_timestamp(self) -> tuple[float, str | None]:
        return 0.0, None

    def get_atm_strike(self, symbol: str) -> int:
        return 0

    def get_broker_name(self) -> str:
        return self._broker

    def get_spot_instrument_key(self, symbol: str) -> str:
        return f"spot:{symbol}"

    def list_expiries(self, symbol: str) -> list[date]:
        self.list_expiries_calls += 1
        return list(self._expiries.get(symbol, []))


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    expiry_resolver.clear_cache()


# ---------------------------------------------------------------------------
# get_all_expiries / cache behaviour
# ---------------------------------------------------------------------------


def test_get_all_expiries_returns_sorted_future_only() -> None:
    today = expiry_resolver._today_ist()
    past = date(today.year - 1, 1, 7)
    fut1 = date(today.year + 1, 1, 7)
    fut2 = date(today.year + 1, 1, 14)
    feed = FakeFeed(expiries={"NIFTY": [fut2, past, fut1]})
    out = expiry_resolver.get_all_expiries(feed, "NIFTY")
    assert out == [fut1, fut2]


def test_get_all_expiries_cached_per_day() -> None:
    today = expiry_resolver._today_ist()
    fut = date(today.year + 1, 6, 2)
    feed = FakeFeed(expiries={"NIFTY": [fut]})
    expiry_resolver.get_all_expiries(feed, "NIFTY")
    expiry_resolver.get_all_expiries(feed, "NIFTY")
    assert feed.list_expiries_calls == 1


def test_clear_cache_forces_refetch() -> None:
    today = expiry_resolver._today_ist()
    fut = date(today.year + 1, 6, 2)
    feed = FakeFeed(expiries={"NIFTY": [fut]})
    expiry_resolver.get_all_expiries(feed, "NIFTY")
    expiry_resolver.clear_cache()
    expiry_resolver.get_all_expiries(feed, "NIFTY")
    assert feed.list_expiries_calls == 2


def test_unknown_symbol_raises() -> None:
    feed = FakeFeed()
    with pytest.raises(ValueError, match="Unknown symbol"):
        expiry_resolver.get_all_expiries(feed, "GOLD")


# ---------------------------------------------------------------------------
# get_next_expiry
# ---------------------------------------------------------------------------


def test_get_next_expiry_picks_earliest_future() -> None:
    today = expiry_resolver._today_ist()
    e1 = date(today.year + 1, 6, 2)
    e2 = date(today.year + 1, 6, 9)
    e3 = date(today.year + 1, 6, 16)
    feed = FakeFeed(expiries={"NIFTY": [e3, e1, e2]})
    assert expiry_resolver.get_next_expiry(feed, "NIFTY") == e1


def test_get_next_expiry_after_cutoff() -> None:
    today = expiry_resolver._today_ist()
    e1 = date(today.year + 1, 6, 2)
    e2 = date(today.year + 1, 6, 9)
    feed = FakeFeed(expiries={"NIFTY": [e1, e2]})
    assert (
        expiry_resolver.get_next_expiry(feed, "NIFTY", after=date(today.year + 1, 6, 3))
        == e2
    )


def test_get_next_expiry_no_match_raises() -> None:
    today = expiry_resolver._today_ist()
    e1 = date(today.year + 1, 6, 2)
    feed = FakeFeed(expiries={"NIFTY": [e1]})
    with pytest.raises(ValueError, match="No upcoming expiry"):
        expiry_resolver.get_next_expiry(
            feed, "NIFTY", after=date(today.year + 5, 1, 1)
        )


# ---------------------------------------------------------------------------
# get_nth_expiry
# ---------------------------------------------------------------------------


def test_get_nth_expiry_indexing() -> None:
    today = expiry_resolver._today_ist()
    e1 = date(today.year + 1, 6, 2)
    e2 = date(today.year + 1, 6, 9)
    e3 = date(today.year + 1, 6, 16)
    feed = FakeFeed(expiries={"BANKNIFTY": [e1, e2, e3]})
    assert expiry_resolver.get_nth_expiry(feed, "BANKNIFTY", 0) == e1
    assert expiry_resolver.get_nth_expiry(feed, "BANKNIFTY", 2) == e3


def test_get_nth_expiry_out_of_range() -> None:
    today = expiry_resolver._today_ist()
    feed = FakeFeed(expiries={"NIFTY": [date(today.year + 1, 6, 2)]})
    with pytest.raises(ValueError, match="Only "):
        expiry_resolver.get_nth_expiry(feed, "NIFTY", 3)


def test_get_nth_expiry_negative() -> None:
    feed = FakeFeed(expiries={"NIFTY": []})
    with pytest.raises(ValueError, match=">= 0"):
        expiry_resolver.get_nth_expiry(feed, "NIFTY", -1)


# ---------------------------------------------------------------------------
# is_expiry_day
# ---------------------------------------------------------------------------


def test_is_expiry_day_today_true() -> None:
    today = expiry_resolver._today_ist()
    feed = FakeFeed(expiries={"NIFTY": [today, date(today.year + 1, 1, 1)]})
    assert expiry_resolver.is_expiry_day(feed, "NIFTY") is True


def test_is_expiry_day_today_false() -> None:
    today = expiry_resolver._today_ist()
    fut = date(today.year + 1, 6, 2)
    feed = FakeFeed(expiries={"NIFTY": [fut]})
    assert expiry_resolver.is_expiry_day(feed, "NIFTY") is False


def test_is_expiry_day_explicit_date() -> None:
    today = expiry_resolver._today_ist()
    e1 = date(today.year + 1, 6, 2)
    feed = FakeFeed(expiries={"NIFTY": [e1]})
    assert expiry_resolver.is_expiry_day(feed, "NIFTY", today=e1) is True
    assert (
        expiry_resolver.is_expiry_day(feed, "NIFTY", today=date(today.year + 1, 6, 3))
        is False
    )


# ---------------------------------------------------------------------------
# get_expiry_summary — pattern detection
# ---------------------------------------------------------------------------


def test_summary_detects_weekly_tuesday_for_nifty() -> None:
    # 7 consecutive Tuesdays starting near "today"
    today = expiry_resolver._today_ist()
    nifty_expiries = []
    # Use a fixed reference series of Tuesdays in 2027 to avoid leap-year edge cases
    base = date(today.year + 1, 1, 5)  # 2027-01-05 is a Tuesday (assuming today < 2027)
    # Generate Tuesdays from base
    from datetime import timedelta

    # Ensure base is a Tuesday: nudge forward.
    while base.weekday() != 1:
        base = base + timedelta(days=1)
    for i in range(7):
        nifty_expiries.append(base + timedelta(days=7 * i))

    banknifty_expiries = []
    # Pick the LAST Tuesday of each of 4 successive months from base
    cur = base
    for _ in range(4):
        next_month_year = cur.year + (cur.month // 12)
        next_month = (cur.month % 12) + 1
        # Walk to end of cur.month and find last Tuesday
        from calendar import monthrange

        days = monthrange(cur.year, cur.month)[1]
        last_tue = None
        for d in range(days, 0, -1):
            cand = date(cur.year, cur.month, d)
            if cand.weekday() == 1:
                last_tue = cand
                break
        if last_tue:
            banknifty_expiries.append(last_tue)
        cur = date(next_month_year, next_month, 1)
    banknifty_expiries = sorted(set(banknifty_expiries))

    feed = FakeFeed(
        expiries={"NIFTY": nifty_expiries, "BANKNIFTY": banknifty_expiries}
    )
    summary = expiry_resolver.get_expiry_summary(feed)
    assert summary["NIFTY"]["weekday_pattern"].startswith("weekly")
    assert "Tuesday" in summary["NIFTY"]["weekday_pattern"]
    assert summary["BANKNIFTY"]["weekday_pattern"].startswith("monthly")
    assert "Tuesday" in summary["BANKNIFTY"]["weekday_pattern"]


def test_summary_empty_when_no_expiries() -> None:
    feed = FakeFeed(expiries={})
    summary = expiry_resolver.get_expiry_summary(feed)
    assert summary["NIFTY"]["next_4_expiries"] == []
    assert summary["NIFTY"]["weekday_pattern"] == "no upcoming expiries"


def test_summary_caps_at_4_expiries() -> None:
    today = expiry_resolver._today_ist()
    from datetime import timedelta

    expiries = [today + timedelta(days=7 * i) for i in range(1, 9)]
    feed = FakeFeed(expiries={"NIFTY": expiries, "BANKNIFTY": []})
    summary = expiry_resolver.get_expiry_summary(feed)
    assert len(summary["NIFTY"]["next_4_expiries"]) == 4
