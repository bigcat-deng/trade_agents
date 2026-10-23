"""Target, buy, and stop from drawn important lines."""

from __future__ import annotations

import unittest

from app.charts.chan_board import _plan_caption
from app.levels.target_stop import CROSS, INTERVAL, OUTSIDE, target_stop_plan


class TargetStopPlanTests(unittest.TestCase):
    def test_bar_inside_an_interval(self) -> None:
        plan = target_stop_plan((160, 100, 130), high=125, low=110, close=120)
        self.assertEqual(plan.mode, INTERVAL)
        self.assertEqual(plan.levels, (100.0, 130.0, 160.0))
        self.assertEqual(plan.delta_avg, 30.0)
        self.assertEqual(plan.extended, (70.0, 100.0, 130.0, 160.0, 190.0))
        self.assertEqual(plan.stop, 100.0)
        self.assertEqual(plan.target, 130.0)
        self.assertAlmostEqual(plan.buy, 110.0)
        self.assertEqual(plan.value, "低")
        self.assertAlmostEqual(plan.reward, 10.0)
        self.assertAlmostEqual(plan.risk, 20.0)
        self.assertAlmostEqual(plan.ratio, 0.5)

    def test_buy_point_is_the_two_to_one_split(self) -> None:
        plan = target_stop_plan((100, 130, 160), high=175, low=165, close=170)
        self.assertEqual(plan.mode, INTERVAL)
        self.assertEqual(plan.stop, 160.0)
        self.assertEqual(plan.target, 190.0)
        self.assertAlmostEqual(plan.buy, 170.0)
        self.assertAlmostEqual(plan.target - plan.buy, 2 * (plan.buy - plan.stop))
        self.assertEqual(plan.value, "平")
        self.assertAlmostEqual(plan.ratio, 2.0)

    def test_bar_crossing_one_line_uses_neighbor_midpoints(self) -> None:
        plan = target_stop_plan((100, 130, 160), high=140, low=120, close=125)
        self.assertEqual(plan.mode, CROSS)
        self.assertEqual(plan.crossed, (130.0,))
        self.assertEqual(plan.target, 145.0)
        self.assertEqual(plan.stop, 115.0)
        self.assertAlmostEqual(plan.buy, 125.0)
        self.assertEqual(plan.value, "平")
        self.assertAlmostEqual(plan.ratio, 2.0)

    def test_bar_crossing_several_lines(self) -> None:
        plan = target_stop_plan((100, 130, 160), high=140, low=90, close=100)
        self.assertEqual(plan.mode, CROSS)
        self.assertEqual(plan.crossed, (100.0, 130.0))
        self.assertEqual(plan.target, 145.0)
        self.assertEqual(plan.stop, 85.0)
        self.assertEqual(plan.value, "高")
        self.assertAlmostEqual(plan.buy, (145.0 + 2 * 85.0) / 3.0)

    def test_bar_outside_the_extended_grid(self) -> None:
        plan = target_stop_plan((100, 130, 160), high=210, low=200, close=205)
        self.assertEqual(plan.mode, OUTSIDE)
        self.assertIsNone(plan.target)
        self.assertIsNone(plan.buy)
        self.assertIsNone(plan.value)
        self.assertIsNone(plan.ratio)

    def test_close_below_buy_is_the_better_price(self) -> None:
        plan = target_stop_plan((100, 130, 160), high=125, low=105, close=108)
        self.assertEqual(plan.value, "高")
        self.assertGreater(plan.ratio, 2.0)

    def test_rejects_a_single_line(self) -> None:
        with self.assertRaises(ValueError):
            target_stop_plan((100,), high=101, low=99, close=100)

    def test_caption_lists_target_buy_and_stop(self) -> None:
        plan = target_stop_plan((160, 100, 130), high=125, low=110, close=120)
        self.assertEqual(plan.target, 130.0)
        self.assertEqual(plan.stop, 100.0)
        self.assertEqual(
            _plan_caption(plan),
            {
                "target": "130.00",
                "buy": "110.00",
                "stop": "100.00",
                "yield_rate": "8.33%",
                "loss_rate": "16.67%",
            },
        )
        outside = target_stop_plan((100, 130, 160), high=210, low=200, close=205)
        self.assertIsNone(_plan_caption(outside))


if __name__ == "__main__":
    unittest.main()
