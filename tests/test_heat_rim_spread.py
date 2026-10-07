"""Near-end expanding bright-run ranking."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from app.themes.heat_rim_spread import (
    list_heat_rim_patches,
    macd_up_by_code_from_overlay,
    rank_heat_rim_spread,
)


def _days(n: int, start: date = date(2026, 1, 2)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


class HeatRimSpreadTests(unittest.TestCase):
    def test_expanding_bright_run_lists_members(self) -> None:
        dates = _days(12)
        codes = ["a", "b", "c", "d", "e", "f"]
        names = ["A", "B", "C", "D", "E", "F"]
        z = np.full((12, 6), 0.20)
        for t, val in enumerate([0.42, 0.50, 0.58, 0.66, 0.74, 0.82], start=6):
            z[t, 2] = val
            z[t, 3] = val - 0.03
        z[9, 4] = 0.48
        z[10, 4] = 0.60
        z[11, 4] = 0.72
        z[6:12, 5] = 0.88
        out = rank_heat_rim_spread(
            dates=dates, codes=codes, names=names, z=z.tolist()
        )
        got = {row["board_code"] for row in out["rows"]}
        self.assertTrue({"c", "d", "e"} <= got or {"c", "d"} <= got)
        self.assertNotIn("f", got)
        self.assertLessEqual(len(out["rows"]), 5)

    def test_macd_up_boosts_rank(self) -> None:
        dates = _days(12)
        codes = ["a", "b", "c"]
        names = ["A", "B", "C"]
        z = np.full((12, 3), 0.20)
        for t, val in enumerate([0.45, 0.52, 0.58, 0.64, 0.70, 0.78], start=6):
            z[t, :] = val
        out = rank_heat_rim_spread(
            dates=dates,
            codes=codes,
            names=names,
            z=z.tolist(),
            macd_up_by_code={"b": [dates[-1]]},
        )
        self.assertGreaterEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["board_code"], "b")
        self.assertTrue(out["rows"][0]["macd_up"])

    def test_later_macd_up_scores_higher(self) -> None:
        dates = _days(12)
        codes = ["a", "b"]
        names = ["A", "B"]
        z = np.full((12, 2), 0.20)
        for t, val in enumerate([0.45, 0.52, 0.58, 0.64, 0.70, 0.78], start=6):
            z[t, :] = val
        out = rank_heat_rim_spread(
            dates=dates,
            codes=codes,
            names=names,
            z=z.tolist(),
            macd_up_by_code={"a": [dates[6]], "b": [dates[-1]]},
        )
        by_code = {row["board_code"]: row["score"] for row in out["rows"]}
        self.assertGreater(by_code["b"], by_code["a"])

    def test_skips_trailing_all_nan_row(self) -> None:
        dates = _days(8)
        z = np.full((8, 2), 0.20)
        for t, val in enumerate([0.45, 0.52, 0.60, 0.68, 0.76], start=2):
            z[t, 0] = val
            z[t, 1] = val - 0.04
        z[-1, :] = np.nan
        out = rank_heat_rim_spread(
            dates=dates, codes=["a", "b"], names=["A", "B"], z=z.tolist()
        )
        self.assertTrue(out["rows"])
        self.assertEqual(out["as_of"], dates[-2].isoformat())

    def test_list_patches_keeps_full_run(self) -> None:
        dates = _days(12)
        codes = ["a", "b", "c", "d", "e", "f"]
        names = ["A", "B", "C", "D", "E", "F"]
        z = np.full((12, 6), 0.20)
        for t, val in enumerate([0.42, 0.50, 0.58, 0.66, 0.74, 0.82], start=6):
            z[t, 2] = val
            z[t, 3] = val - 0.03
        z[9, 4] = 0.48
        z[10, 4] = 0.60
        z[11, 4] = 0.72
        z[6:12, 5] = 0.88
        listed = list_heat_rim_patches(
            dates=dates, codes=codes, names=names, z=z.tolist()
        )
        self.assertEqual(listed["as_of"], dates[-1].isoformat())
        self.assertTrue(listed["patches"])
        members = {
            m["board_code"]
            for patch in listed["patches"]
            for m in patch["members"]
        }
        self.assertTrue({"c", "d"} <= members)
        self.assertNotIn("f", members)
        self.assertTrue(
            any(p["expanding"] or p["brightening"] for p in listed["patches"])
        )

    def test_overlay_maps_cell_centers(self) -> None:
        dates = _days(3)
        codes = ["x", "y"]
        mapped = macd_up_by_code_from_overlay(
            codes=codes,
            dates=dates,
            overlay={"macd_up_x": [1.0], "macd_up_y": [2.0]},
        )
        self.assertEqual(mapped["y"], [dates[2]])


if __name__ == "__main__":
    unittest.main()
