"""Raw price fractals placed on the industry short-heat plane."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.themes.board_fractal_marks import (
    build_fractal_mark_overlay,
    surviving_raw_fractals,
)


def _bar(day: date, price: float) -> dict[str, object]:
    return {
        "trade_date": day,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
    }


class BoardFractalMarkTests(unittest.TestCase):
    def test_only_surviving_raw_fractals_are_returned(self) -> None:
        start = date(2026, 1, 1)
        prices = [10.0] * 8 + [30.0] + [10.0] * 8 + [1.0] + [10.0] * 8
        bars = [_bar(start + timedelta(days=i), price) for i, price in enumerate(prices)]
        marks = surviving_raw_fractals(bars)
        kinds = {kind for _day, kind in marks}
        self.assertTrue(kinds)
        self.assertTrue(kinds <= {"top", "bottom"})
        self.assertIn("top", kinds)

    def test_overlay_keeps_fractals_inside_the_window(self) -> None:
        start = date(2026, 1, 1)
        prices = [10.0] * 8 + [40.0] + [12.0] * 8 + [1.0] + [12.0] * 8
        bars = [_bar(start + timedelta(days=i), price) for i, price in enumerate(prices)]
        window = [start + timedelta(days=i) for i in range(len(prices))]
        overlay = build_fractal_mark_overlay(
            ordered_codes=["881112"],
            window_dates=window,
            bars_by_code={"881112": bars},
            names={"881112": "钢铁"},
        )
        self.assertGreater(overlay["top_count"], 0)
        self.assertTrue(all(x == 0.0 for x in overlay["top_x"]))
        self.assertTrue(all(0 <= y < len(window) for y in overlay["top_y"]))
        self.assertTrue(all("顶分型" in text and "钢铁" in text for text in overlay["top_text"]))
        outside = build_fractal_mark_overlay(
            ordered_codes=["881112"],
            window_dates=[start - timedelta(days=30)],
            bars_by_code={"881112": bars},
            names={"881112": "钢铁"},
        )
        self.assertEqual(outside["top_count"], 0)
        self.assertEqual(outside["bottom_count"], 0)
