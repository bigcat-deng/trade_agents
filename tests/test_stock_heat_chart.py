"""Stock heat chart under the Chan window."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal

from app.charts.chan_board import chan_xaxis_range
from app.charts.stock_heat import build_stock_heat_figure, render_stock_heat_html


class StockHeatChartTests(unittest.TestCase):
    def test_chan_xaxis_range_matches_single_and_multi(self) -> None:
        start = date(2024, 1, 2)
        end = date(2024, 6, 28)
        single = chan_xaxis_range(start, start, 1)
        self.assertEqual(len(single), 2)
        self.assertLess(single[0], single[1])
        multi = chan_xaxis_range(start, end, 120)
        self.assertLess(multi[0].date(), start)
        self.assertGreater(multi[1].date(), end)

    def test_build_stock_heat_figure_draws_short_and_long(self) -> None:
        start = date(2024, 1, 2)
        heats = []
        day = start
        for i in range(30):
            while day.weekday() >= 5:
                day += timedelta(days=1)
            heats.append(
                {
                    "trade_date": day,
                    "heat_short": Decimal(100 - i),
                    "heat_long": Decimal(80 - i * 0.5),
                }
            )
            day += timedelta(days=1)
        end = heats[-1]["trade_date"]
        figure = build_stock_heat_figure(
            heats, title="测试", start=start, end=end, n=len(heats)
        )
        self.assertIsNotNone(figure)
        assert figure is not None
        self.assertEqual(len(figure.data), 2)
        html = render_stock_heat_html(
            heats, title="测试", start=start, end=end, n=len(heats)
        )
        self.assertIsNotNone(html)
        assert html is not None
        self.assertTrue("\\u77ed\\u70ed" in html or "短热" in html)

    def test_comment_ranks_are_a_line_on_the_same_axis(self) -> None:
        start = date(2024, 1, 2)
        heats = [
            {
                "trade_date": start,
                "heat_short": Decimal("900"),
                "heat_long": Decimal("1200"),
            },
            {
                "trade_date": date(2024, 1, 8),
                "heat_short": Decimal("700"),
                "heat_long": Decimal("1100"),
            },
        ]
        comments = [
            {"trade_date": start, "rank_no": 12, "rank_change": 3},
            {"trade_date": date(2024, 1, 5), "rank_no": None, "rank_change": 1},
            {"trade_date": date(2024, 1, 8), "rank_no": 40, "rank_change": -2},
        ]
        figure = build_stock_heat_figure(
            heats,
            title="测试",
            start=start,
            end=date(2024, 1, 8),
            n=2,
            comments=comments,
        )
        self.assertIsNotNone(figure)
        assert figure is not None
        self.assertEqual(len(figure.data), 3)
        comment = figure.data[2]
        self.assertEqual(comment.name, "千股千评")
        self.assertEqual(comment.mode, "lines")
        self.assertEqual(comment.line.color, "rgba(21, 128, 61, 0.5)")
        self.assertEqual(comment.line.dash, None)
        self.assertEqual(list(comment.x), [start, date(2024, 1, 8)])
        self.assertEqual(list(comment.y), [12.0, 40.0])
        self.assertEqual(list(comment.customdata), ["+3", "-2"])
        self.assertEqual(figure.layout.yaxis.autorange, "reversed")
        html = render_stock_heat_html(
            heats,
            title="测试",
            start=start,
            end=date(2024, 1, 8),
            n=2,
            comments=comments,
        )
        assert html is not None
        self.assertTrue("\\u5343\\u80a1\\u5343\\u8bc4" in html or "千股千评" in html)

    def test_comment_ranks_do_not_draw_without_heat(self) -> None:
        heats = [
            {"trade_date": date(2024, 1, 2), "heat_short": None, "heat_long": None},
        ]
        comments = [
            {"trade_date": date(2024, 1, 2), "rank_no": 8, "rank_change": 0},
        ]
        self.assertIsNone(
            build_stock_heat_figure(
                heats,
                title="空",
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                n=1,
                comments=comments,
            )
        )

    def test_build_stock_heat_figure_empty_when_all_null(self) -> None:
        heats = [
            {"trade_date": date(2024, 1, 2), "heat_short": None, "heat_long": None},
        ]
        self.assertIsNone(
            build_stock_heat_figure(
                heats, title="空", start=date(2024, 1, 2), end=date(2024, 1, 2), n=1
            )
        )


if __name__ == "__main__":
    unittest.main()
