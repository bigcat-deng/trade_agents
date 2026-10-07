"""Tests for industry return-volatility exceedance marks."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.themes.industry_return_flags import (
    collect_started_codes,
    compute_return_exceedance_cells,
    exceedance_to_line_xy,
    is_long_upper_shadow,
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


class StartedCodesTests(unittest.TestCase):
    def test_yang_marks_started(self) -> None:
        cal = _calendar(101)
        px = 100.0
        bars = []
        for i, day in enumerate(cal):
            if i == 0:
                bars.append({"trade_date": day, "close": px, "volume": 1000})
                continue
            if day == cal[-1]:
                px *= 1.08
            else:
                px *= 1.001
            bars.append({"trade_date": day, "close": px, "volume": 1000})
        started = collect_started_codes(
            codes=["A"],
            as_of=cal[-1],
            bars_by_code={"A": bars},
            vol_calendar=cal,
            check_days=3,
        )
        self.assertIn("A", started)

    def test_volume_surge_marks_started(self) -> None:
        cal = _calendar(40)
        bars = []
        px = 100.0
        for i, day in enumerate(cal):
            if i > 0:
                px *= 1.001  # quiet returns — no yang
            vol = 10_000 if i < len(cal) - 1 else 30_000  # 3× prior
            bars.append({"trade_date": day, "close": px, "volume": vol})
        started = collect_started_codes(
            codes=["B"],
            as_of=cal[-1],
            bars_by_code={"B": bars},
            vol_calendar=cal,
            check_days=1,
            vol_lookback=20,
            vol_mult=2.0,
        )
        self.assertIn("B", started)

    def test_quiet_name_not_started(self) -> None:
        cal = _calendar(101)
        px = 100.0
        bars = []
        for i, day in enumerate(cal):
            if i > 0:
                px *= 1.001
            bars.append(
                {
                    "trade_date": day,
                    "open": px,
                    "high": px * 1.002,
                    "low": px * 0.998,
                    "close": px,
                    "volume": 1000,
                }
            )
        started = collect_started_codes(
            codes=["C"],
            as_of=cal[-1],
            bars_by_code={"C": bars},
            vol_calendar=cal,
        )
        self.assertNotIn("C", started)

    def test_long_upper_shadow_helper(self) -> None:
        # open 10, close 10.2, high 11.5, low 10 → upper dominates, body small
        self.assertTrue(
            is_long_upper_shadow(open_=10.0, high=11.5, low=10.0, close=10.2)
        )
        # solid big body up day — not exhaustion
        self.assertFalse(
            is_long_upper_shadow(open_=10.0, high=11.2, low=10.0, close=11.1)
        )

    def test_long_upper_shadow_marks_unfit(self) -> None:
        cal = _calendar(40)
        bars = []
        px = 100.0
        for i, day in enumerate(cal):
            if i > 0:
                px *= 1.001
            if i == len(cal) - 1:
                # Quiet return but long upper: open≈close, spike high
                o = px
                c = px * 1.002
                h = px * 1.04
                l = px * 0.998
            else:
                o = c = px
                h = px * 1.002
                l = px * 0.998
            bars.append(
                {
                    "trade_date": day,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": 1000,
                }
            )
        started = collect_started_codes(
            codes=["D"],
            as_of=cal[-1],
            bars_by_code={"D": bars},
            vol_calendar=cal,
            check_days=1,
        )
        self.assertIn("D", started)

    def test_big_yin_marks_unfit(self) -> None:
        cal = _calendar(101)
        px = 100.0
        bars = []
        for i, day in enumerate(cal):
            if i == 0:
                bars.append(
                    {
                        "trade_date": day,
                        "open": px,
                        "high": px,
                        "low": px,
                        "close": px,
                        "volume": 1000,
                    }
                )
                continue
            if day == cal[-1]:
                px *= 0.92  # -8% big yin vs quiet σ
            else:
                px *= 1.001
            bars.append(
                {
                    "trade_date": day,
                    "open": px / 0.92 if day == cal[-1] else px,
                    "high": px * 1.002,
                    "low": px * 0.998,
                    "close": px,
                    "volume": 1000,
                }
            )
        started = collect_started_codes(
            codes=["E"],
            as_of=cal[-1],
            bars_by_code={"E": bars},
            vol_calendar=cal,
            check_days=1,
        )
        self.assertIn("E", started)


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
