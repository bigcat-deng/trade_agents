"""All-stock heat plane helpers."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from app.market_data.board_heat import BoardHeatRow
from app.themes.all_stock_wave import (
    ALL_STOCK_HOVERTEMPLATE,
    ZOOM_NAME_THRESHOLD,
    build_all_stock_heat_payload,
    build_all_stock_hover_customdata,
)


def _heat(day: date, code: str, short: float) -> BoardHeatRow:
    return BoardHeatRow(
        trade_date=day,
        board_type="stock",
        board_code=code,
        pct_chg=None,
        rank_no=1,
        universe_n=3,
        heat_short=short,
        heat_long=short,
    )


class AllStockHeatPayloadTests(unittest.TestCase):
    def test_seriates_and_omits_default_ticks(self) -> None:
        days = [date(2026, 10, i) for i in range(1, 21)]
        rows = []
        for i, day in enumerate(days):
            rows.append(_heat(day, "sz.000001", 10 + i * 0.1))
            rows.append(_heat(day, "sz.000002", 50 - i * 0.2))
            rows.append(_heat(day, "sz.000003", 30 + (i % 5)))
        with (
            patch(
                "app.themes.all_stock_wave.fetch_stock_heat_dates_ending",
                return_value=days,
            ),
            patch("app.themes.all_stock_wave.fetch_stock_heat", return_value=rows),
            patch(
                "app.themes.all_stock_wave.fetch_stock_code_names",
                return_value={
                    "sz.000001": "甲",
                    "sz.000002": "乙",
                    "sz.000003": "丙",
                },
            ),
            patch(
                "app.themes.all_stock_wave.fetch_stock_industry_names",
                return_value={
                    "sz.000001": "银行",
                    "sz.000002": "地产",
                    "sz.000003": "传媒",
                },
            ),
        ):
            payload = build_all_stock_heat_payload(as_of=days[-1], window_days=20)

        self.assertIsNone(payload["empty_message"])
        self.assertEqual(payload["board_count"], 3)
        self.assertEqual(len(payload["dates"]), 20)
        self.assertEqual(payload["x_tickvals"], [])
        self.assertEqual(payload["x_ticktext"], [])
        self.assertEqual(payload["zoom_name_threshold"], ZOOM_NAME_THRESHOLD)
        self.assertEqual(len(payload["stock_x"]), 3)
        self.assertEqual(len(payload["stock_names"]), 3)
        self.assertEqual(len(payload["stock_display_codes"]), 3)
        self.assertEqual(len(payload["stock_industries"]), 3)
        self.assertEqual(len(payload["z_short"]), 20)
        self.assertEqual(len(payload["z_short"][0]), 3)

        hover = build_all_stock_hover_customdata(
            dates=payload["dates"],
            x=payload["x"],
            z=payload["z_short"],
            stock_x=payload["stock_x"],
            display_codes=payload["stock_display_codes"],
            names=payload["stock_names"],
            industries=payload["stock_industries"],
        )
        self.assertEqual(len(hover), 20)
        self.assertEqual(len(hover[0][0]), 5)
        self.assertIn("代码 %{customdata[0]}", ALL_STOCK_HOVERTEMPLATE)
        self.assertIn("行业板块 %{customdata[4]}", ALL_STOCK_HOVERTEMPLATE)


if __name__ == "__main__":
    unittest.main()
