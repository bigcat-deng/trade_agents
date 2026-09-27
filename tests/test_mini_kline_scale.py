"""Tests for mini-kline CSI 500 scaling."""

from __future__ import annotations

import unittest
from datetime import date

from app.charts.mini_kline import scale_benchmark_to_price


class ScaleBenchmarkTests(unittest.TestCase):
    def test_aligns_min_max_to_price_range(self) -> None:
        bars = [
            {"trade_date": date(2026, 9, 1), "high": 12.0, "low": 10.0},
            {"trade_date": date(2026, 9, 2), "high": 14.0, "low": 11.0},
            {"trade_date": date(2026, 9, 3), "high": 13.0, "low": 10.5},
        ]
        benchmark = {
            date(2026, 9, 1): 100.0,
            date(2026, 9, 2): 200.0,
            date(2026, 9, 3): 150.0,
        }
        scaled = scale_benchmark_to_price(bars, benchmark)
        assert scaled is not None
        values = [value for _, value in scaled]
        self.assertAlmostEqual(min(values), 10.0)
        self.assertAlmostEqual(max(values), 14.0)
        self.assertAlmostEqual(values[2], 12.0)

    def test_skips_missing_benchmark_days(self) -> None:
        bars = [
            {"trade_date": date(2026, 9, 1), "high": 12.0, "low": 10.0},
            {"trade_date": date(2026, 9, 2), "high": 14.0, "low": 11.0},
        ]
        benchmark = {date(2026, 9, 1): 100.0}
        self.assertIsNone(scale_benchmark_to_price(bars, benchmark))


if __name__ == "__main__":
    unittest.main()
