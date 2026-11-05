"""Constituent rows sort by short heat inside the board."""

from __future__ import annotations

import unittest

from app.levels.board_members import (
    MemberPlanRow,
    _day_return_at,
    _sort_key,
    ratio_highlight_codes,
)


def _row(
    code: str,
    name: str,
    *,
    heat: float | None,
    ratio: float | None = 1.0,
    day_return: float | None = 0.01,
    note: str | None = None,
) -> MemberPlanRow:
    return MemberPlanRow(
        code,
        name,
        None,
        1.0,
        day_return,
        heat,
        ratio,
        None if ratio is None else 0.1,
        None if ratio is None else 1.1,
        None if ratio is None else 0.9,
        note,
    )


class BoardMemberSortTests(unittest.TestCase):
    def test_hotter_heat_comes_first(self) -> None:
        cool = _row("sz.2", "B", heat=12.0, ratio=2.0)
        hot = _row("sz.1", "A", heat=3.0, ratio=1.0)
        missing = _row("sz.3", "C", heat=None, ratio=None, day_return=None, note="无K线")
        ordered = sorted([cool, missing, hot], key=_sort_key)
        self.assertEqual([row.code for row in ordered], ["sz.1", "sz.2", "sz.3"])

    def test_equal_heat_breaks_ties_by_code(self) -> None:
        left = _row("sz.2", "B", heat=5.0)
        right = _row("sz.1", "A", heat=5.0)
        ordered = sorted([left, right], key=_sort_key)
        self.assertEqual([row.code for row in ordered], ["sz.1", "sz.2"])


class RatioHighlightTests(unittest.TestCase):
    def test_top_and_bottom_three_do_not_overlap(self) -> None:
        rows = [_row(f"sz.{i}", str(i), heat=float(i), ratio=float(i)) for i in range(1, 8)]
        top, bottom = ratio_highlight_codes(rows)
        self.assertEqual(top, {"sz.7", "sz.6", "sz.5"})
        self.assertEqual(bottom, {"sz.1", "sz.2", "sz.3"})
        self.assertFalse(top & bottom)

    def test_short_list_keeps_top_and_avoids_double_paint(self) -> None:
        rows = [
            _row("sz.3", "C", heat=1.0, ratio=3.0),
            _row("sz.2", "B", heat=1.0, ratio=2.0),
            _row("sz.1", "A", heat=1.0, ratio=1.0),
            _row("sz.0", "Z", heat=None, ratio=None, day_return=None, note="无K线"),
        ]
        top, bottom = ratio_highlight_codes(rows)
        self.assertEqual(top, {"sz.3", "sz.2", "sz.1"})
        self.assertEqual(bottom, set())


class DayReturnTests(unittest.TestCase):
    def test_baostock_percent_becomes_fraction(self) -> None:
        bars = [{"close": 10.0, "pct_chg": "-0.9022"}]
        self.assertAlmostEqual(_day_return_at(bars, 0), -0.009022)

    def test_ths_close_to_close_fraction(self) -> None:
        bars = [{"close": 100.0}, {"close": 96.29}]
        self.assertAlmostEqual(_day_return_at(bars, 1), -0.0371, places=4)
        self.assertIsNone(_day_return_at(bars, 0))


if __name__ == "__main__":
    unittest.main()
