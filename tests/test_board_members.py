"""Constituent rows sort by short heat inside the board."""

from __future__ import annotations

import unittest

from app.levels.board_members import MemberPlanRow, _sort_key


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


if __name__ == "__main__":
    unittest.main()
