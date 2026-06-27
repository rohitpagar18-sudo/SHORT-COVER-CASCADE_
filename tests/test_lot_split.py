"""Unit tests for :func:`src.risk.lot_sizing.compute_lot_split`.

The 50/50 ladder is locked: ``tp1_lots = ceil(lots / 2)``,
``tp2_lots = lots − tp1_lots``. Odd counts route the extra lot to TP1
(conservative). ``lots == 1`` is the single special case — full exit
at TP1, no runner.
"""

from __future__ import annotations

import pytest

from src.risk.lot_sizing import compute_lot_split


@pytest.mark.parametrize(
    "lots, expected",
    [
        (1, (1, 0)),     # single-lot: full exit at TP1
        (2, (1, 1)),     # even: 50/50
        (3, (2, 1)),     # odd: extra to TP1
        (4, (2, 2)),     # even: 50/50
        (5, (3, 2)),     # odd: extra to TP1
        (6, (3, 3)),     # even: 50/50
        (7, (4, 3)),     # odd
        (8, (4, 4)),     # even: 50/50
        (9, (5, 4)),     # odd
        (10, (5, 5)),    # even: 50/50
        (20, (10, 10)),  # even: 50/50
        (30, (15, 15)),  # even: 50/50
    ],
)
def test_compute_lot_split(lots, expected):
    assert compute_lot_split(lots) == expected


def test_sum_equals_lots():
    """tp1 + tp2 == lots for all inputs 1..50."""
    for lots in range(1, 51):
        tp1, tp2 = compute_lot_split(lots)
        assert tp1 + tp2 == lots, f"lots={lots}: {tp1}+{tp2} != {lots}"


def test_tp1_gte_tp2():
    """tp1 >= tp2 always — extra lot goes to TP1 on odd counts."""
    for lots in range(1, 51):
        tp1, tp2 = compute_lot_split(lots)
        assert tp1 >= tp2, f"lots={lots}: tp1={tp1} < tp2={tp2}"


def test_even_lots_exact_half():
    """Even lots produce exactly 50/50."""
    for lots in [2, 4, 6, 8, 10, 20, 30]:
        tp1, tp2 = compute_lot_split(lots)
        assert tp1 == lots // 2
        assert tp2 == lots // 2


def test_single_lot_no_runner():
    """lots=1 must return (1, 0) — full exit at TP1."""
    assert compute_lot_split(1) == (1, 0)


def test_tp2_zero_only_for_lots_1():
    """tp2==0 only for lots==1; all other lots have tp2 >= 1."""
    for lots in range(2, 51):
        _, tp2 = compute_lot_split(lots)
        assert tp2 >= 1, f"lots={lots}: tp2={tp2} < 1"


def test_invalid_inputs():
    with pytest.raises(ValueError):
        compute_lot_split(0)
    with pytest.raises(ValueError):
        compute_lot_split(-5)
