"""Current sideways / bearish / bullish state against the latest pivot."""

from __future__ import annotations

import unittest

from app.levels.industry_rank import (
    BEARISH,
    BULLISH,
    SIDEWAYS,
    pivot_position,
    pivot_state,
    pivot_step,
    state_label,
)


class PivotStateTests(unittest.TestCase):
    def test_bar_inside_the_pivot_is_sideways(self) -> None:
        self.assertEqual(
            pivot_state(100, 120, high=115, low=105, threshold=10),
            SIDEWAYS,
        )

    def test_a_poke_within_half_th_stays_sideways(self) -> None:
        # 多元金融: ZD 1037.34, bar high 1028.86, th 42.
        self.assertEqual(
            pivot_state(1037.34, 1078.24, high=1028.86, low=1012.76, threshold=42),
            SIDEWAYS,
        )

    def test_clearing_below_the_pivot_is_bearish(self) -> None:
        # 工业金属: ZD 4219.48, bar high 3878.52, th 268.
        self.assertEqual(
            pivot_state(4219.48, 4522.87, high=3878.52, low=3813.03, threshold=268),
            BEARISH,
        )

    def test_a_small_dip_under_a_narrow_pivot_stays_sideways(self) -> None:
        # 煤炭开采加工: ZD 2985.37, bar high 2969.75, th 146.
        self.assertEqual(
            pivot_state(2985.37, 2998.12, high=2969.75, low=2889.16, threshold=146),
            SIDEWAYS,
        )

    def test_clearing_above_the_pivot_is_bullish(self) -> None:
        self.assertEqual(
            pivot_state(100, 120, high=160, low=141, threshold=20),
            BULLISH,
        )

    def test_gap_equal_to_half_th_stays_sideways(self) -> None:
        self.assertEqual(
            pivot_state(100, 120, high=95, low=90, threshold=10),
            SIDEWAYS,
        )

    def test_gap_beyond_half_th_is_bearish(self) -> None:
        self.assertEqual(
            pivot_state(100, 120, high=94, low=90, threshold=10),
            BEARISH,
        )


class PivotPositionTests(unittest.TestCase):
    """Band 100–130 splits at 110 and 120. A boundary close belongs above."""

    def test_close_above_the_band_is_outside_upper(self) -> None:
        self.assertEqual(pivot_position(100, 130, close=130.01), "外上")

    def test_close_below_the_band_is_outside_lower(self) -> None:
        self.assertEqual(pivot_position(100, 130, close=99.99), "外下")

    def test_touching_zd_is_inner_lower(self) -> None:
        self.assertEqual(pivot_position(100, 130, close=100), "内下")

    def test_just_under_the_lower_third_stays_inner_lower(self) -> None:
        self.assertEqual(pivot_position(100, 130, close=109.999), "内下")

    def test_lower_third_boundary_is_inner_middle(self) -> None:
        self.assertEqual(pivot_position(100, 130, close=110), "内中")

    def test_just_under_the_upper_third_stays_inner_middle(self) -> None:
        self.assertEqual(pivot_position(100, 130, close=119.999), "内中")

    def test_upper_third_boundary_is_inner_upper(self) -> None:
        self.assertEqual(pivot_position(100, 130, close=120), "内上")

    def test_touching_zg_is_inner_upper(self) -> None:
        self.assertEqual(pivot_position(100, 130, close=130), "内上")


class PivotStepTests(unittest.TestCase):
    def test_later_pivot_wholly_above_steps_up(self) -> None:
        self.assertEqual(pivot_step(100, 120, 121, 140), "上移")

    def test_later_pivot_wholly_below_steps_down(self) -> None:
        self.assertEqual(pivot_step(100, 120, 70, 99), "下移")

    def test_touching_from_above_is_not_a_step(self) -> None:
        self.assertIsNone(pivot_step(100, 120, 120, 140))

    def test_touching_from_below_is_not_a_step(self) -> None:
        self.assertIsNone(pivot_step(100, 120, 80, 100))

    def test_label_joins_state_and_step(self) -> None:
        self.assertEqual(state_label(SIDEWAYS, "下移"), "sideways/下移")
        self.assertEqual(state_label(BEARISH, None), "bearish/—")
        self.assertEqual(state_label(None, None), "—")
