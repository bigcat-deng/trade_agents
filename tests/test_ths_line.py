"""Tonghuashun code check and daily-line parsing."""

from __future__ import annotations

import unittest
from datetime import date

from app.market_data.providers.ths_line import (
    _bars_from_body,
    line_symbol,
    normalize_ths_code,
)


class ThsLineTests(unittest.TestCase):
    def test_six_digit_stock_code_is_prefixed(self) -> None:
        self.assertEqual(normalize_ths_code(" 600519 "), "600519")
        self.assertEqual(line_symbol("600519"), "hs_600519")

    def test_tonghuashun_index_code_keeps_its_letters(self) -> None:
        self.assertEqual(normalize_ths_code("1a0001"), "1A0001")
        self.assertEqual(line_symbol("1A0001"), "hs_1A0001")

    def test_names_and_dotted_codes_are_rejected(self) -> None:
        for raw in ("茅台", "sh.600519", "600519.SH", "hs_600519", "1A000"):
            with self.assertRaises(ValueError):
                normalize_ths_code(raw)

    def test_line_body_becomes_dated_bars(self) -> None:
        body = (
            'quotebridge_v4_line_hs_600519_01_2026('
            '{"data":"20260105,10.5,11.0,10.2,10.8,1000,2000,0,,,0;'
            '20260106,10.8,11.2,10.7,11.1,1100,2100,0,,,0"})'
        )
        rows = _bars_from_body(body)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["trade_date"], date(2026, 1, 5))
        self.assertEqual(rows[0]["close"], 10.8)
        self.assertEqual(rows[1]["volume"], 1100.0)
