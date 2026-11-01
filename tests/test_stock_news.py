"""Per-stock news slice for the analyze page."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.stock_news import assemble_stock_news, focus_sparkline, like_pattern


def _comment(day: date, focus: str = "10.0") -> tuple:
    return (day, "普门科技", focus, "60.0", 2017, -3)


class AssembleStockNewsTests(unittest.TestCase):
    def test_off_list_and_unnamed_broadcast(self) -> None:
        view = assemble_stock_news(
            code="sh.688389",
            name="普门科技",
            as_of=date(2026, 10, 30),
            comments=[_comment(date(2026, 10, 30), "69.6")],
            rank_listed=True,
            rank=None,
            surge_listed=True,
            surge=None,
            weibo=[],
            weibo_listed=True,
            notices=[],
            flashes=[],
            cctv_listed=True,
            cctv=[],
        )
        self.assertEqual(view["kind"], "stock")
        self.assertEqual(view["as_of"], "2026-10-30")
        self.assertEqual(view["news_href"], "/news?day=2026-10-30")
        self.assertEqual(view["comment"]["focus"], "69.6")
        self.assertEqual(view["comment"]["rank_change"], "-3")
        self.assertIsNone(view["sparkline"])
        self.assertEqual(view["rank"]["label"], "未上榜")
        self.assertEqual(view["weibo_note"], "未上榜")
        self.assertEqual(view["surge"]["label"], "未上榜")
        self.assertEqual(view["cctv_note"], "当日联播未提及")
        self.assertEqual(view["flash_note"], "没有提到「普门科技」")

    def test_on_list_and_name_match(self) -> None:
        published = datetime(2026, 10, 30, 13, 0, tzinfo=ZoneInfo("UTC"))
        view = assemble_stock_news(
            code="sh.600519",
            name="贵州茅台",
            as_of=date(2026, 10, 30),
            comments=[
                _comment(date(2026, 10, 29), "40.0"),
                _comment(date(2026, 10, 30), "55.5"),
            ],
            rank_listed=True,
            rank=(3, 2, 1.25),
            surge_listed=False,
            surge=None,
            weibo=[("CNHOUR24", 12.5)],
            notices=[(date(2026, 10, 28), "业绩", "三季报", "https://example.test/a")],
            flashes=[("cls", published, "贵州茅台披露", "贵州茅台披露", "http://news.example/x")],
            cctv_listed=True,
            cctv=[("财经", "提到贵州茅台的一段")],
        )
        self.assertEqual(view["rank"]["state"], "on")
        self.assertEqual(view["rank"]["rank_no"], 3)
        self.assertEqual(view["rank"]["pct_chg"], "+1.25")
        self.assertEqual(view["surge"]["label"], "该日尚未入库")
        self.assertEqual(view["weibo"][0]["period"], "近 24 小时")
        self.assertEqual(view["weibo"][0]["rate"], "12.50")
        self.assertEqual(view["notices"][0]["url"], "https://example.test/a")
        self.assertEqual(view["flashes"][0]["title"], "贵州茅台披露")
        self.assertEqual(view["flashes"][0]["content"], None)
        self.assertIsNone(view["cctv_note"])
        self.assertEqual(view["cctv"][0]["title"], "财经")
        self.assertIsNotNone(view["sparkline"])
        self.assertEqual(view["sparkline"]["low"], "40.0")
        self.assertEqual(view["sparkline"]["high"], "55.5")

    def test_missing_snapshot_day(self) -> None:
        view = assemble_stock_news(
            code="sh.688389",
            name=None,
            as_of=None,
            comments=[],
            rank_listed=False,
            rank=None,
            surge_listed=False,
            surge=None,
            weibo=[],
            notices=[],
            flashes=[],
            cctv_listed=False,
            cctv=[],
        )
        self.assertTrue(view["comment_missing"] is False)
        self.assertEqual(view["rank"]["label"], "还没有榜单日期")
        self.assertEqual(view["flash_note"], "没有证券简称，未按名称检索")
        self.assertEqual(view["cctv_note"], "没有证券简称，未检索联播")
        self.assertEqual(view["news_href"], "/news")

    def test_like_pattern_escapes_wildcards(self) -> None:
        self.assertEqual(like_pattern("A_B%"), "%A\\_B\\%%")

    def test_sparkline_needs_two_points(self) -> None:
        self.assertIsNone(focus_sparkline([(date(2026, 10, 30), 1.0)]))
        line = focus_sparkline(
            [(date(2026, 10, 29), 1.0), (date(2026, 10, 30), 3.0)]
        )
        self.assertIsNotNone(line)
        self.assertIn(",", line["points"])
