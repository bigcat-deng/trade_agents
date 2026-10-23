"""Spectrum scenario chain covers every finite hotness."""

from __future__ import annotations

import unittest

import numpy as np

from app.themes.heat_scenarios import (
    SCENARIO_ORDER,
    classify_hotness_scenario,
    scenario_hint,
)


def _series(level: float, slope: float, *, n: int = 20, pad: float | None = None) -> np.ndarray:
    last = np.array([level + slope * (i - 4) for i in range(5)], dtype=float)
    head = np.full(n - 5, last[0] if pad is None else pad, dtype=float)
    return np.concatenate([head, last])


class HeatScenarioChainTests(unittest.TestCase):
    def test_empty_or_invalid_hotness_has_no_tag(self) -> None:
        self.assertEqual(classify_hotness_scenario(np.array([]))[0], None)
        self.assertEqual(classify_hotness_scenario(np.full(20, np.nan))[0], None)

    def test_chain_boundaries(self) -> None:
        cases = {
            (0.20, 0.0): "冷寂",
            (0.5499, -0.02): "冷寂",
            (0.5499, 0.0): "冷寂",
            (0.40, 0.02): "萌芽",
            (0.5499, 0.01): "萌芽",
            (0.55, 0.01): "升温",
            (0.70, 0.02): "升温",
            (0.85, 0.01): "升温",
            (0.55, 0.0): "中位",
            (0.70, 0.009): "中位",
            (0.70, -0.009): "中位",
            (0.85, 0.0): "中位",
            (0.86, 0.0): "高位",
            (0.92, 0.02): "久热",
            (0.92, 0.0): "久热",
            (0.55, -0.01): "退潮",
            (0.70, -0.02): "退潮",
            (0.85, -0.01): "退潮",
            (0.96, -0.02): "退潮",
        }
        for (level, slope), expected in cases.items():
            with self.subTest(level=level, slope=slope):
                got, _, _ = classify_hotness_scenario(_series(level, slope))
                self.assertEqual(got, expected)

    def test_plateau_without_long_crowding_is_still_hot(self) -> None:
        # Ending at 0.96 with a cold body fails the 8-day count and uses the plateau rule.
        got, _, _ = classify_hotness_scenario(_series(0.96, 0.0, pad=0.2))
        self.assertEqual(got, "久热")

    def test_crowded_theme_that_turns_down_is_fade(self) -> None:
        got, _, _ = classify_hotness_scenario(_series(0.92, -0.02))
        self.assertEqual(got, "退潮")

    def test_rebound_hint_does_not_change_the_tag(self) -> None:
        series = np.concatenate(
            [
                np.full(10, 0.80),
                np.full(5, 0.30),
                np.array([0.32, 0.34, 0.36, 0.38, 0.40]),
            ]
        )
        scenario, _, _ = classify_hotness_scenario(series)
        self.assertEqual(scenario, "萌芽")
        self.assertEqual(scenario_hint(scenario, series), "回抽再起；近端续热再加重")

    def test_fresh_bud_keeps_the_plain_hint(self) -> None:
        series = _series(0.40, 0.02)
        scenario, _, _ = classify_hotness_scenario(series)
        self.assertEqual(scenario_hint(scenario, series), "观察；近端续热再加重")

    def test_grid_always_lands_on_the_chain(self) -> None:
        for level in (0.0, 0.2, 0.55, 0.7, 0.85, 0.86, 0.92, 1.0):
            for slope in (-0.05, -0.01, 0.0, 0.009, 0.01, 0.05):
                with self.subTest(level=level, slope=slope):
                    scenario, _, _ = classify_hotness_scenario(_series(level, slope))
                    self.assertIn(scenario, SCENARIO_ORDER)


if __name__ == "__main__":
    unittest.main()
