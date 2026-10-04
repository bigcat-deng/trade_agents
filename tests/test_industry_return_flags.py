"""Tests for industry return-volatility exceedance marks."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.themes.industry_return_flags import (
    compute_return_exceedance_cells,
    exceedance_to_line_xy,
    sigma_from_returns,
)


def _calendar(n: int, start: date = date(2026, 1, 2)) -> list[date]:
    # weekdays only-ish: just consecutive dates for unit tests
    return [start + timedelta(days=i) for i in range(n)]


class ReturnExceedanceTests(unittest.TestCase):
    def test_sigma_needs_enough_returns(self) -> None:
        self.assertIsNone(sigma_from_returns([0.01] * 10, lookback=100))
        sig = sigma_from_returns([0.01, -0.01] * 50, lookback=100)
        self.assertIsNotNone(sig)
        self.assertGreater(sig, 0.0)

    def test_flags_only_beyond_two_sigma(self) -> None:
        cal = _calendar(101)
        # Quiet returns then one big up day and one big down day in the window.
        closes = []
        px = 100.0
        for i, day in enumerate(cal):
            if i == 0:
                closes.append({"trade_date": day, "close": px})
                continue
            if day == cal[-2]:
                px *= 1.08  # +8%
            elif day == cal[-1]:
                px *= 0.92  # -8%
            else:
                px *= 1.001
            closes.append({"trade_date": day, "close": px})
        window = cal[-40:]
        pos, neg = compute_return_exceedance_cells(
            ordered_codes=["A"],
            window_dates=window,
            bars_by_code={"A": closes},
            vol_calendar=cal,
            lookback=100,
            mult=2.0,
        )
        self.assertIn(("A", cal[-2]), pos)
        self.assertIn(("A", cal[-1]), neg)

    def test_line_xy_on_cell_bottom(self) -> None:
        days = _calendar(3)
        xs, ys = exceedance_to_line_xy(
            cells=[("b", days[1])],
            ordered_codes=["a", "b", "c"],
            window_dates=days,
        )
        self.assertEqual(xs[:2], [0.5, 1.5])
        self.assertEqual(ys[:2], [0.5, 0.5])
        self.assertIsNone(xs[2])

    def test_last_day_labels(self) -> None:
        from app.themes.industry_return_flags import last_day_label_points

        days = _calendar(3)
        xs, ys, texts = last_day_label_points(
            cells=[("b", days[-1]), ("a", days[0])],
            ordered_codes=["a", "b", "c"],
            names={"b": "白酒"},
            window_dates=days,
        )
        self.assertEqual(xs, [1.0])
        self.assertEqual(ys, [2.5])
        self.assertEqual(texts, ["白酒"])


class Csi500ReturnAlignTests(unittest.TestCase):
    def test_daily_returns_aligned(self) -> None:
        from app.market_data.csi500 import daily_returns_aligned

        d0, d1, d2 = date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)
        closes = {d0: 100.0, d1: 101.0, d2: 99.0}
        rets = daily_returns_aligned([d1, d2], closes)
        self.assertAlmostEqual(rets[0], 0.01)
        self.assertAlmostEqual(rets[1], 99.0 / 101.0 - 1.0)


if __name__ == "__main__":
    unittest.main()
