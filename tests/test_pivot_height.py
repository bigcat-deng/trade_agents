"""A pivot overlap shorter than th/2 is skipped one stroke at a time."""

from __future__ import annotations

import unittest

from scripts.chan_fractal_probe import Fractal, Stroke, find_pivots


def _stroke(direction: str, start: float, end: float, index: int) -> Stroke:
    start_kind = "bottom" if direction == "up" else "top"
    end_kind = "top" if direction == "up" else "bottom"
    return Stroke(
        direction,
        Fractal(start_kind, index, index, start),
        Fractal(end_kind, index + 1, index + 1, end),
    )


class PivotHeightTests(unittest.TestCase):
    def test_thin_overlap_slides_to_the_next_stroke(self) -> None:
        strokes = [
            _stroke("up", 1509.49, 1614.17, 0),
            _stroke("down", 1614.17, 1411.87, 1),
            _stroke("up", 1411.87, 1513.34, 2),
            _stroke("down", 1513.34, 1393.09, 3),
        ]
        pivots = find_pivots(strokes, min_height=32.52)
        self.assertEqual(len(pivots), 1)
        self.assertAlmostEqual(pivots[0].zd, 1411.87)
        self.assertAlmostEqual(pivots[0].zg, 1513.34)
        self.assertEqual(pivots[0].count, 3)
        self.assertEqual(pivots[0].first.start.index, 1)

    def test_height_equal_to_the_minimum_is_kept(self) -> None:
        strokes = [
            _stroke("up", 100, 130, 0),
            _stroke("down", 130, 110, 1),
            _stroke("up", 110, 140, 2),
        ]
        pivots = find_pivots(strokes, min_height=20)
        self.assertEqual(len(pivots), 1)
        self.assertAlmostEqual(pivots[0].zg - pivots[0].zd, 20)

    def test_no_qualifying_triple_makes_no_pivot(self) -> None:
        strokes = [
            _stroke("up", 100, 110, 0),
            _stroke("down", 110, 101, 1),
            _stroke("up", 101, 111, 2),
            _stroke("down", 111, 102, 3),
        ]
        self.assertEqual(find_pivots(strokes, min_height=20), [])
