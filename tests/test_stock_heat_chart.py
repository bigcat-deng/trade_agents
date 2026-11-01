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
