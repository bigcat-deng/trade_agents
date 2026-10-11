"""Kalman + rolling min-max smooth-range helpers."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.themes.board_smooth_range import (
    build_industry_smooth_range_plane,
    kalman_filter_1d,
    kalman_typical_overlay,
    rolling_minmax_norm,
    simple_returns,
    typical_price,
)


class BoardSmoothRangeTests(unittest.TestCase):
    def test_typical_price(self) -> None:
        self.assertAlmostEqual(typical_price(12, 9, 9) or 0.0, 10.0)

    def test_kalman_tracks_level(self) -> None:
        vals = [10.0] * 20 + [20.0] * 20
        sm = kalman_filter_1d(vals)
        self.assertIsNotNone(sm[-1])
        self.assertGreater(sm[-1] or 0.0, 15.0)

    def test_rolling_minmax_spike(self) -> None:
        base = [10.0] * 80
        series = base + [10.0, 10.0, 20.0]
        norm = rolling_minmax_norm(series, window=100, min_periods=20)
        self.assertIsNotNone(norm[-1])
        self.assertGreater(norm[-1] or 0.0, 0.9)

    def test_plane_respects_order(self) -> None:
        start = date(2026, 4, 1)
        hist = [start + timedelta(days=i) for i in range(140)]
        window = hist[-40:]
        bars: dict[str, list[dict[str, object]]] = {"a": [], "b": []}
        for i, day in enumerate(hist):
            # a flat, b ramps up into tip
            for code, px in (("a", 10.0), ("b", 10.0 + i * 0.05)):
                bars[code].append(
                    {
                        "trade_date": day,
                        "high": px + 1,
                        "low": px - 1,
                        "close": px,
                    }
                )
        plane = build_industry_smooth_range_plane(
            window_dates=window,
            history_dates=hist,
            ordered_codes=["b", "a"],
            names={"a": "甲", "b": "乙"},
            bars_by_code=bars,
        )
        self.assertIsNone(plane.get("empty_message"))
        self.assertEqual(plane["board_codes"], ["b", "a"])
        tip = plane["z_boards"][-1]
        self.assertGreater(tip[0] or 0.0, tip[1] or 0.0)

    def test_simple_returns(self) -> None:
        series = [None, 10.0, 11.0, None, 12.0, 12.0]
        rets = simple_returns(series)
        self.assertIsNone(rets[0])
        self.assertIsNone(rets[1])
        self.assertAlmostEqual(rets[2] or 0.0, 0.1)
        self.assertIsNone(rets[3])
        self.assertIsNone(rets[4])  # prev cleared by gap
        self.assertAlmostEqual(rets[5] or 0.0, 0.0)

    def test_return_plane_metric(self) -> None:
        start = date(2026, 4, 1)
        hist = [start + timedelta(days=i) for i in range(140)]
        window = hist[-40:]
        bars: dict[str, list[dict[str, object]]] = {"a": []}
        for i, day in enumerate(hist):
            px = 10.0 + (0.2 if i == len(hist) - 1 else 0.0)
            bars["a"].append(
                {
                    "trade_date": day,
                    "high": px + 1,
                    "low": px - 1,
                    "close": px,
                }
            )
        plane = build_industry_smooth_range_plane(
            window_dates=window,
            history_dates=hist,
            ordered_codes=["a"],
            names={"a": "甲"},
            bars_by_code=bars,
            metric="return",
        )
        self.assertIsNone(plane.get("empty_message"))
        self.assertEqual(plane.get("metric"), "return")
        self.assertIn("简单日收益", plane["axis_note"])

    def test_kalman_overlay_respects_display_window(self) -> None:
        start = date(2026, 8, 1)
        bars = []
        for i in range(50):
            day = start + timedelta(days=i)
            px = 10.0 + i * 0.1
            bars.append(
                {
                    "trade_date": day,
                    "high": px + 1,
                    "low": px - 1,
                    "close": px,
                }
            )
        mid = start + timedelta(days=20)
        end = start + timedelta(days=40)
        overlay = kalman_typical_overlay(
            bars, display_start=mid, display_end=end
        )
        self.assertIsNotNone(overlay)
        assert overlay is not None
        self.assertEqual(overlay["name"], "卡尔曼典型价")
        self.assertGreaterEqual(date.fromisoformat(overlay["x"][0]), mid)
        self.assertLessEqual(date.fromisoformat(overlay["x"][-1]), end)


if __name__ == "__main__":
    unittest.main()
