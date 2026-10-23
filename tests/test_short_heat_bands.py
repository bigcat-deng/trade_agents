"""Short-heat thirds for the industry target/stop table."""

from __future__ import annotations

import unittest

from app.levels.industry_rank import COLD, HOT, short_heat_bands


class ShortHeatBandTests(unittest.TestCase):
    def test_thirds_of_nine_leave_the_middle_plain(self) -> None:
        rows = [(f"{index:02d}", index) for index in range(1, 10)]
        bands = short_heat_bands(rows)
        self.assertEqual(bands["01"], HOT)
        self.assertEqual(bands["03"], HOT)
        self.assertNotIn("04", bands)
        self.assertNotIn("06", bands)
        self.assertEqual(bands["07"], COLD)
        self.assertEqual(bands["09"], COLD)

    def test_missing_heat_is_left_out_of_the_count(self) -> None:
        rows = [(f"{index:02d}", index) for index in range(1, 9)]
        rows.append(("none", None))
        bands = short_heat_bands(rows)
        self.assertEqual(len([code for code, band in bands.items() if band == HOT]), 2)
        self.assertEqual(len([code for code, band in bands.items() if band == COLD]), 2)
        self.assertNotIn("none", bands)
        self.assertEqual(bands["01"], HOT)
        self.assertEqual(bands["08"], COLD)

    def test_equal_heats_are_cut_by_code(self) -> None:
        rows = [(code, 5) for code in ("c", "a", "b", "f", "d", "e")]
        bands = short_heat_bands(rows)
        self.assertEqual({code for code, band in bands.items() if band == HOT}, {"a", "b"})
        self.assertEqual({code for code, band in bands.items() if band == COLD}, {"e", "f"})

    def test_fewer_than_three_rows_stay_plain(self) -> None:
        self.assertEqual(short_heat_bands([("a", 1), ("b", 2)]), {})
