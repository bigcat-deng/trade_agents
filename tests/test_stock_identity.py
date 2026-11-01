"""Stock name and board membership for the analyze page."""

from __future__ import annotations

import unittest
from datetime import date

from app.stock_identity import build_stock_identity, load_stock_identity


class StockIdentityTests(unittest.TestCase):
    def test_name_sits_with_code_and_boards_split(self) -> None:
        view = build_stock_identity(
            ths_code="000037",
            name="深南电A",
            rows=[
                ("concept", "885001", "深南电A", date(2026, 9, 25), "光伏"),
                ("industry", "881145", "深南电A", date(2026, 9, 25), "电力"),
                ("concept", "885002", "深南电A", date(2026, 9, 25), "风电"),
            ],
        )
        self.assertEqual(view["title"], "000037 深南电A")
        self.assertEqual([item["name"] for item in view["industries"]], ["电力"])
        self.assertEqual(view["industries"][0]["href"], "/boards/industry/881145/kline")
        self.assertEqual([item["name"] for item in view["concepts"]], ["光伏", "风电"])
        self.assertEqual(view["as_of"], "2026-09-25")

    def test_missing_name_keeps_the_code(self) -> None:
        view = build_stock_identity(ths_code="000037", name=None, rows=[])
        self.assertEqual(view["title"], "000037")
        self.assertEqual(view["industries"], [])
        self.assertEqual(view["concepts"], [])
        self.assertIsNone(view["as_of"])

    def test_index_has_a_name_and_no_boards(self) -> None:
        view = load_stock_identity("1B0852")
        self.assertEqual(view["title"], "中证1000 1B0852")
        self.assertFalse(view["show_boards"])
