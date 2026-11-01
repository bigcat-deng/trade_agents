"""News ingest board assembly."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.news_board import analyze_href, assemble_board, format_flashes, select_day


class AnalyzeHrefTests(unittest.TestCase):
    def test_baostock_code_becomes_six_digits(self) -> None:
        self.assertEqual(analyze_href("sh.600519"), "/analyze?code=600519")
        self.assertEqual(analyze_href("sz.000037"), "/analyze?code=000037")
        self.assertEqual(analyze_href("bj.920001"), "/analyze?code=920001")

    def test_missing_or_unusable_code_has_no_link(self) -> None:
        self.assertIsNone(analyze_href(None))
        self.assertIsNone(analyze_href(""))
        self.assertIsNone(analyze_href("not-a-code"))


class SelectDayTests(unittest.TestCase):
    def test_requested_day_wins(self) -> None:
        asked = date(2026, 10, 29)
        self.assertEqual(
            select_day(asked, [(date(2026, 10, 30), "stock_comment", 10)]),
            asked,
        )

    def test_default_is_latest_comment_day(self) -> None:
        counts = [
            (date(2026, 10, 29), "stock_comment", 5),
            (date(2026, 10, 30), "cctv", 16),
            (date(2026, 10, 30), "stock_comment", 100),
        ]
        self.assertEqual(select_day(None, counts), date(2026, 10, 30))

    def test_empty_has_no_day(self) -> None:
        self.assertIsNone(select_day(None, []))


class AssembleTests(unittest.TestCase):
    def test_card_shows_table_rows_when_status_says_zero(self) -> None:
        day = date(2026, 10, 30)
        board = assemble_board(
            requested=None,
            selected=day,
            counts=[(day, "em_rank", 100), (day, "stock_comment", 20)],
            state={
                "em_rank": {
                    "snapshot_date": day,
                    "status": "error",
                    "reported_rows": 0,
                    "error": "connection failed",
                    "updated_at": datetime(2026, 10, 31, 7, 50, tzinfo=ZoneInfo("UTC")),
                }
            },
            flashes={},
            detail=_empty(),
        )
        rank = next(card for card in board["cards"] if card["feed"] == "em_rank")
        self.assertEqual(rank["snapshot_rows"], 100)
        self.assertEqual(rank["mismatch"], "状态记录 0，表内 100")
        self.assertEqual(rank["status_label"], "失败")
        self.assertIn("人气榜最近一次同步未成功", board["notes"][0])
        flash = next(card for card in board["cards"] if card["feed"] == "cls")
        self.assertEqual(flash["status_label"], "尚未同步")
        self.assertEqual(board["days"][0]["counts"][1], 100)

    def test_flash_error_is_visible_before_any_rows(self) -> None:
        board = assemble_board(
            requested=None,
            selected=None,
            counts=[],
            state={
                "cls": {
                    "status": "error",
                    "error": "empty",
                    "updated_at": None,
                }
            },
            flashes={},
            detail=_empty(),
        )
        flash = next(card for card in board["cards"] if card["feed"] == "cls")
        self.assertEqual(flash["status_label"], "失败")
        self.assertEqual(flash["error"], "empty")

    def test_selected_day_outside_coverage_still_appears(self) -> None:
        board = assemble_board(
            requested=date(2026, 1, 1),
            selected=date(2026, 1, 1),
            counts=[(date(2026, 10, 30), "cctv", 2)],
            state={},
            flashes={},
            detail=_empty(),
        )
        self.assertEqual(board["days"][0]["day"], "2026-10-30")
        self.assertEqual(board["days"][1]["day"], "2026-01-01")
        self.assertTrue(board["days"][1]["selected"])
        self.assertEqual(board["days"][1]["counts"], [None, None, None, None, None, None])
        self.assertEqual(board["latest_flashes"], [])


class FormatFlashTests(unittest.TestCase):
    def test_keeps_body_when_it_differs_from_the_title(self) -> None:
        published = datetime(2026, 10, 31, 13, 40, 28, tzinfo=ZoneInfo("UTC"))
        items = format_flashes(
            [
                ("ths", published, "标题", "正文比标题长", "https://news.example/1"),
                ("cls", published, "只有标题", "只有标题", "javascript:alert(1)"),
            ]
        )
        self.assertEqual(items[0]["source_label"], "同花顺")
        self.assertEqual(items[0]["published_at"], "2026-10-31 21:40")
        self.assertEqual(items[0]["content"], "正文比标题长")
        self.assertEqual(items[0]["url"], "https://news.example/1")
        self.assertIsNone(items[1]["content"])
        self.assertIsNone(items[1]["url"])


def _empty() -> dict:
    return {
        "comment": {"count": 0, "focus_top": [], "rise_top": []},
        "rank": [],
        "surge": [],
        "weibo": [],
        "notices": [],
        "cctv": [],
    }
