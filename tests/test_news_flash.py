"""CLS and Tonghuashun flash normalization."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.jobs.sync_news_flash import run
from app.market_data.news_flash import normalize_cls, normalize_ths
from app.sync_runner import _build_command

SHANGHAI = ZoneInfo("Asia/Shanghai")


class NormalizeTests(unittest.TestCase):
    def test_cls_combines_date_and_time(self) -> None:
        rows, skipped = normalize_cls(
            [
                {
                    "标题": "公司回购",
                    "内容": "正文",
                    "发布日期": date(2026, 10, 31),
                    "发布时间": time(21, 5, 6),
                    "等级": "A",
                },
                {"标题": "", "内容": "无标题", "发布日期": date(2026, 10, 31), "发布时间": time(21, 6)},
            ]
        )
        self.assertEqual(skipped, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "cls")
        self.assertEqual(rows[0].level, "A")
        self.assertEqual(rows[0].published_at, datetime(2026, 10, 31, 21, 5, 6, tzinfo=SHANGHAI))

    def test_ths_parses_local_timestamp(self) -> None:
        rows, skipped = normalize_ths(
            [
                {
                    "标题": "同花顺快讯",
                    "内容": "摘要",
                    "发布时间": "2026-10-31 21:08:00",
                    "链接": "https://news.10jqka.com.cn/1",
                }
            ]
        )
        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0].source, "ths")
        self.assertEqual(rows[0].url, "https://news.10jqka.com.cn/1")
        self.assertEqual(rows[0].published_at, datetime(2026, 10, 31, 21, 8, tzinfo=SHANGHAI))
        self.assertIsNone(rows[0].level)

    def test_duplicate_title_at_the_same_time_keeps_one(self) -> None:
        rows, skipped = normalize_cls(
            [
                {
                    "标题": "重复",
                    "内容": "一",
                    "发布日期": date(2026, 10, 31),
                    "发布时间": time(21, 1),
                },
                {
                    "标题": "重复",
                    "内容": "二",
                    "发布日期": date(2026, 10, 31),
                    "发布时间": time(21, 1),
                },
            ]
        )
        self.assertEqual(skipped, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].content, "二")


class RunTests(unittest.TestCase):
    def test_one_source_error_still_stores_the_other(self) -> None:
        saved: list[str] = []

        def fake_store(database_url, *, feed, rows, status, error):
            saved.append(f"{feed}:{status}:{len(rows)}")
            return len(rows)

        with patch("app.jobs.sync_news_flash.store_flash", fake_store):
            code = run(
                "postgresql:///analytics",
                fetch=False,
                cls_records=[
                    {
                        "标题": "一条",
                        "内容": "正文",
                        "发布日期": date(2026, 10, 31),
                        "发布时间": time(21, 0),
                    }
                ],
                ths_error="down",
            )
        self.assertEqual(code, 1)
        self.assertEqual(saved, ["cls:ok:1", "ths:error:0"])

    def test_dashboard_command(self) -> None:
        command = _build_command(
            "news_flash", trading_days=None, resume=False, day=None
        )
        self.assertEqual(command[-2:], ["-m", "app.jobs.sync_news_flash"])
