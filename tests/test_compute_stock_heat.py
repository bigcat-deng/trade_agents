"""Unit tests for stock heat tip-window helpers and ranking reuse."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.jobs.compute_stock_heat import WARMUP_EXTRA, tip_write_window
from app.market_data.board_heat import BoardReturn, compute_heat


def _days(n: int, start: date = date(2024, 1, 2)) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def test_tip_write_window_splits_warmup_and_write() -> None:
    days = _days(WARMUP_EXTRA + 5)
    fetch_start, write_start = tip_write_window(days, 5)
    assert fetch_start == days[0]
    assert write_start == days[-5]
    assert days.index(write_start) == len(days) - 5


def test_tip_write_window_rejects_short_calendar() -> None:
    assert tip_write_window(_days(3), 5) is None
    with pytest.raises(ValueError):
        tip_write_window(_days(10), 0)


def test_compute_heat_stock_produces_short_heat() -> None:
    """Enough bars for MA2 + MA5 rank + MA5 short heat on the tip day."""
    codes = [f"sh.60000{i}" for i in range(3)]
    days = _days(30)
    returns: list[BoardReturn] = []
    for i, code in enumerate(codes):
        price = Decimal("10") + Decimal(i)
        for day in days:
            price += Decimal("0.1") * (i + 1)
            returns.append(
                BoardReturn(
                    trade_date=day,
                    board_code=code,
                    pct_chg=Decimal("1"),
                    high=price + Decimal("0.2"),
                    low=price - Decimal("0.2"),
                    close=price,
                )
            )
    rows = compute_heat(returns, board_type="stock")
    tip = days[-1]
    tip_rows = [row for row in rows if row.trade_date == tip]
    assert len(tip_rows) == 3
    assert all(row.board_type == "stock" for row in tip_rows)
    assert all(row.rank_no is not None for row in tip_rows)
    assert all(row.heat_short is not None for row in tip_rows)
    assert all(row.heat_long is not None for row in tip_rows)
