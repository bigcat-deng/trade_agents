"""Tonghuashun concept membership has no row cap."""

from __future__ import annotations

import unittest
from datetime import date

from app.market_data.providers.akshare_ths_board import (
    constituents_from_conceptlist,
    constituents_from_field_page,
)


class ConceptListTests(unittest.TestCase):
    def test_keeps_every_stock_on_the_latest_day(self) -> None:
        payload = {
            "errorcode": 0,
            "result": {
                "listdata": {
                    "2026-06-30": [["600000", "旧名单", "x"]],
                    "2026-09-30": [
                        ["301599", "理奇智能", "x"],
                        ["920201", "另一只", "x"],
                        ["301599", "理奇智能", "dup"],
                    ],
                }
            },
        }
        rows = constituents_from_conceptlist(
            payload,
            trade_date=date(2026, 11, 1),
            board_code="308740",
        )
        self.assertEqual(
            [(row.stock_code, row.stock_name) for row in rows],
            [("sz.301599", "理奇智能"), ("bj.920201", "另一只")],
        )
        self.assertTrue(all(row.board_code == "308740" for row in rows))
        self.assertTrue(all(row.board_type == "concept" for row in rows))


_FIELD_HTML = """
<a href="http://index.10jqka.com.cn/list/field/0881272/">更多</a>
<div>二级行业分类： 计算机 -- 软件开发 （共 2 家）</div>
<div>三级行业分类： 计算机 -- 软件开发 -- 垂直应用软件 （共 1 家）</div>
<table id="hy2_table_1">
  <tr><td>600570</td><td>恒生电子</td></tr>
  <tr><td>920932</td><td>科达自控</td></tr>
</table>
<table id="hy3_table_1">
  <tr><td>000503</td><td>国新健康</td></tr>
</table>
"""


class FieldPageTests(unittest.TestCase):
    def test_second_level_name_uses_the_wider_table(self) -> None:
        rows = constituents_from_field_page(
            _FIELD_HTML,
            trade_date=date(2026, 11, 1),
            board_code="881272",
            board_name="软件开发",
        )
        self.assertEqual(
            [row.stock_code for row in rows],
            ["sh.600570", "bj.920932"],
        )

    def test_third_level_name_uses_the_narrower_table(self) -> None:
        rows = constituents_from_field_page(
            _FIELD_HTML,
            trade_date=date(2026, 11, 1),
            board_code="881272",
            board_name="垂直应用软件",
        )
        self.assertEqual([row.stock_code for row in rows], ["sz.000503"])

    def test_level_mark_is_ignored_when_matching_the_name(self) -> None:
        html = _FIELD_HTML.replace("垂直应用软件", "软件开发Ⅲ")
        rows = constituents_from_field_page(
            html,
            trade_date=date(2026, 11, 1),
            board_code="881272",
            board_name="软件开发",
        )
        self.assertEqual([row.stock_code for row in rows], ["sz.000503"])

    def test_wrong_industry_code_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            constituents_from_field_page(
                _FIELD_HTML,
                trade_date=date(2026, 11, 1),
                board_code="881121",
                board_name="半导体",
            )


if __name__ == "__main__":
    unittest.main()
