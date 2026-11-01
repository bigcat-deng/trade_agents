"""Constituent rows sort by short heat inside the board."""

from __future__ import annotations

import unittest

from app.levels.board_members import MemberPlanRow, _sort_key, ratio_highlight_codes


class BoardMemberSortTests(unittest.TestCase):
    def test_hotter_heat_comes_first(self) -> None:
        cool = MemberPlanRow("sz.2", "B", None, 1.0, 0.1, 12.0, 2.0, None)
        hot = MemberPlanRow("sz.1", "A", None, 1.0, 0.1, 3.0, 1.0, None)
        missing = MemberPlanRow("sz.3", "C", None, 1.0, None, None, None, "无K线")
        ordered = sorted([cool, missing, hot], key=_sort_key)
        self.assertEqual([row.code for row in ordered], ["sz.1", "sz.2", "sz.3"])

    def test_equal_heat_breaks_ties_by_code(self) -> None:
        left = MemberPlanRow("sz.2", "B", None, 1.0, 0.1, 5.0, 1.0, None)
        right = MemberPlanRow("sz.1", "A", None, 1.0, 0.1, 5.0, 1.0, None)
        ordered = sorted([left, right], key=_sort_key)
        self.assertEqual([row.code for row in ordered], ["sz.1", "sz.2"])


class RatioHighlightTests(unittest.TestCase):
    def test_top_and_bottom_three_do_not_overlap(self) -> None:
        rows = [
            MemberPlanRow(f"sz.{i}", str(i), None, 1.0, 0.1, float(i), float(i), None)
            for i in range(1, 8)
        ]
        top, bottom = ratio_highlight_codes(rows)
        self.assertEqual(top, {"sz.7", "sz.6", "sz.5"})
        self.assertEqual(bottom, {"sz.1", "sz.2", "sz.3"})
        self.assertFalse(top & bottom)

    def test_short_list_keeps_top_and_avoids_double_paint(self) -> None:
        rows = [
            MemberPlanRow("sz.3", "C", None, 1.0, 0.1, 1.0, 3.0, None),
            MemberPlanRow("sz.2", "B", None, 1.0, 0.1, 1.0, 2.0, None),
            MemberPlanRow("sz.1", "A", None, 1.0, 0.1, 1.0, 1.0, None),
            MemberPlanRow("sz.0", "Z", None, 1.0, None, None, None, "无K线"),
        ]
        top, bottom = ratio_highlight_codes(rows)
        self.assertEqual(top, {"sz.3", "sz.2", "sz.1"})
        self.assertEqual(bottom, set())


if __name__ == "__main__":
    unittest.main()
