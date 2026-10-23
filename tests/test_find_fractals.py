"""The newest fractal window may close with two bars on the right."""

from __future__ import annotations

import unittest

import numpy as np

from scripts.chan_fractal_probe import MA, find_fractals, _trailing_ma


def _flat_then(tail: list[float], *, head: int = 8) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    prices = np.array([20.0] * head + tail, dtype=float)
    return prices, prices.copy(), _trailing_ma(prices, MA)


class EdgeFractalWindowTests(unittest.TestCase):
    def test_latest_center_with_two_bars_on_the_right_is_a_bottom(self) -> None:
        highs, lows, smooth = _flat_then([5.0, 20.0, 20.0])
        found = find_fractals(smooth, highs, lows)
        bottoms = [item for item in found if item.kind == "bottom"]
        self.assertEqual([(item.index, item.smooth_index) for item in bottoms], [(8, 8)])

    def test_third_bar_below_the_center_drops_the_provisional_bottom(self) -> None:
        highs, lows, smooth = _flat_then([5.0, 20.0, 20.0, 4.0])
        found = find_fractals(smooth, highs, lows)
        self.assertFalse(any(item.kind == "bottom" for item in found))

    def test_a_closed_window_is_unchanged_by_the_edge_rule(self) -> None:
        highs, lows, smooth = _flat_then([5.0, 20.0, 20.0, 20.0])
        found = find_fractals(smooth, highs, lows)
        bottoms = [item for item in found if item.kind == "bottom"]
        self.assertEqual([(item.index, item.smooth_index) for item in bottoms], [(8, 8)])


if __name__ == "__main__":
    unittest.main()
