"""Close-of-day news snapshot normalization and job wiring."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from app.market_data.codes import to_baostock
from app.market_data.news_daily import (
    cctv_ready,
    collect_snapshot,
    hot_list_records,
    normalize_comment,
    normalize_notices,
    resolve_name,
    session_date,
    name_index,
)
from app.jobs.sync_news_daily import run
from app.sync_runner import _build_command


def _comment(code: str, name: str, day: str = "2026-10-30") -> dict:
    return {
        "代码": code,
        "名称": name,
        "最新价": 10.5,
        "涨跌幅": 1.2,
        "换手率": 2.0,
        "市盈率": 8.0,
        "主力成本": 10.0,
        "机构参与度": 30.0,
        "综合得分": 70.0,
        "上升": 3,
        "目前排名": 12,
        "关注指数": 80.0,
        "交易日": day,
    }


class CodeTests(unittest.TestCase):
    def test_beijing_92_is_not_shanghai(self) -> None:
        self.assertEqual(to_baostock("920079"), "bj.920079")
        self.assertEqual(to_baostock("900901"), "sh.900901")


class SessionDateTests(unittest.TestCase):
    def test_after_close_uses_that_weekday(self) -> None:
        self.assertEqual(
            session_date(datetime(2026, 10, 30, 15, 5)).isoformat(),
            "2026-10-30",
        )

    def test_before_close_uses_previous_weekday(self) -> None:
        self.assertEqual(
            session_date(datetime(2026, 10, 30, 15, 4)).isoformat(),
            "2026-10-29",
        )
        self.assertEqual(
            session_date(datetime(2026, 11, 2, 9, 0)).isoformat(),
            "2026-10-30",
        )

    def test_weekend_uses_friday(self) -> None:
        self.assertEqual(
            session_date(datetime(2026, 10, 31, 10, 0)).isoformat(),
            "2026-10-30",
        )
        self.assertEqual(
            session_date(datetime(2026, 11, 1, 12, 0)).isoformat(),
            "2026-10-30",
        )


class CctvReadyTests(unittest.TestCase):
    def test_waits_until_1930_on_broadcast_day(self) -> None:
        broadcast = session_date(datetime(2026, 10, 30, 21, 0))
        self.assertFalse(cctv_ready(datetime(2026, 10, 30, 18, 0), broadcast))
        self.assertTrue(cctv_ready(datetime(2026, 10, 30, 19, 30), broadcast))
        self.assertTrue(cctv_ready(datetime(2026, 10, 31, 10, 0), broadcast))


class NormalizeTests(unittest.TestCase):
    def test_comment_codes_and_majority_date(self) -> None:
        day, rows, skipped = normalize_comment(
            [
                _comment("600000", "浦发银行"),
                _comment("SZ000001", "平安银行"),
                _comment("000001", "重复"),
                _comment("600000", "其他日", day="2026-10-29"),
                _comment("not-a-code", "坏代码"),
            ]
        )
        self.assertEqual(day.isoformat(), "2026-10-30")
        by_code = {row.code: row.name for row in rows}
        self.assertEqual(by_code["sh.600000"], "浦发银行")
        self.assertEqual(by_code["sz.000001"], "重复")
        self.assertEqual(skipped, 2)

    def test_short_comment_does_not_replace(self) -> None:
        outcome = collect_snapshot(
            _Sources(comment=[_comment("600000", "浦发银行")]),
            datetime(2026, 10, 30, 21, 0),
            minimum_comment_rows=2,
        )[0]
        self.assertEqual(outcome.feed, "stock_comment")
        self.assertEqual(outcome.status, "error")
        self.assertFalse(outcome.replace)
        self.assertEqual(outcome.reported_rows, 1)

    def test_notice_id_comes_from_url(self) -> None:
        rows, skipped = normalize_notices(
            [
                {
                    "代码": "920079",
                    "名称": "乔路铭",
                    "公告标题": "进展公告",
                    "公告日期": date(2026, 10, 30),
                    "网址": "https://data.eastmoney.com/notices/detail/920079/AN202610301831248802.html",
                }
            ],
            notice_type="重大事项",
            notice_date=date(2026, 10, 30),
        )
        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0].notice_id, "AN202610301831248802")
        self.assertEqual(rows[0].code, "bj.920079")

    def test_weibo_name_resolution(self) -> None:
        index = name_index(
            [
                ("sz.000002", "万 科Ａ"),
                ("sh.600000", "浦发银行"),
                ("sh.600001", "浦发银行"),
            ]
        )
        self.assertEqual(resolve_name("万科A", index), "sz.000002")
        self.assertIsNone(resolve_name("浦发银行", index))
        self.assertIsNone(resolve_name("不存在", index))

    def test_partial_notice_keeps_successful_types(self) -> None:
        outcome = next(
            item
            for item in collect_snapshot(
                _Sources(notice_error_types={"风险提示"}),
                datetime(2026, 10, 30, 21, 0),
                minimum_comment_rows=1,
            )
            if item.feed == "stock_notice"
        )
        self.assertEqual(outcome.status, "error")
        self.assertTrue(outcome.replace)
        self.assertNotIn("风险提示", outcome.notice_types)
        self.assertIn("重大事项", outcome.notice_types)
        self.assertEqual(len(outcome.rows), 3)

    def test_cctv_before_broadcast_stays_pending(self) -> None:
        outcome = next(
            item
            for item in collect_snapshot(
                _Sources(cctv_should_not_run=True),
                datetime(2026, 10, 30, 16, 0),
                minimum_comment_rows=1,
            )
            if item.feed == "cctv"
        )
        self.assertEqual(outcome.status, "pending")
        self.assertFalse(outcome.replace)
        self.assertEqual(outcome.error, "联播未到播出时间")


class RunTests(unittest.TestCase):
    def test_failed_comment_sets_exit_code_without_failing_cctv_pending(self) -> None:
        from unittest.mock import patch

        with patch("app.jobs.sync_news_daily.persist") as persist:
            code = run(
                "postgresql:///analytics",
                now=datetime(2026, 10, 30, 16, 0),
                sources=_Sources(comment_error=True),
            )
        self.assertEqual(code, 1)
        outcomes = [call.args[1] for call in persist.call_args_list]
        self.assertEqual(
            [item.feed for item in outcomes],
            ["stock_comment", "em_rank", "em_surge", "weibo", "stock_notice", "cctv"],
        )
        self.assertEqual(outcomes[1].rows[0].code, "sz.000001")
        self.assertEqual(outcomes[1].rows[0].list_name, "rank")
        self.assertEqual(outcomes[2].rows[0].rank_change, 20)
        self.assertEqual(outcomes[2].rows[0].code, "sh.600000")
        weibo = {row.name: row.code for row in outcomes[3].rows}
        self.assertEqual(weibo["万科A"], "sz.000002")
        self.assertIsNone(weibo["无名"])
        self.assertEqual(outcomes[-1].status, "pending")

    def test_dashboard_command(self) -> None:
        command = _build_command(
            "news_daily", trading_days=None, resume=False, day=None
        )
        self.assertEqual(command[-2:], ["-m", "app.jobs.sync_news_daily"])


class _Sources:
    def __init__(
        self,
        *,
        comment: list[dict] | None = None,
        comment_error: bool = False,
        notice_error_types: set[str] | None = None,
        cctv_should_not_run: bool = False,
    ) -> None:
        self._comment = comment if comment is not None else [_comment("600000", "浦发银行")]
        self._comment_error = comment_error
        self._notice_error_types = notice_error_types or set()
        self._cctv_should_not_run = cctv_should_not_run

    def comment(self) -> list[dict]:
        if self._comment_error:
            raise RuntimeError("comment down")
        return self._comment

    def hot_rank(self) -> list[dict]:
        return [
            {
                "代码": "SZ000001",
                "股票名称": "平安银行",
                "当前排名": 1,
                "最新价": 10,
                "涨跌额": 0.1,
                "涨跌幅": 1,
            }
        ]

    def hot_surge(self) -> list[dict]:
        return [
            {
                "代码": "SH600000",
                "股票名称": "浦发银行",
                "当前排名": 4,
                "排名较昨日变动": 20,
                "最新价": 11,
                "涨跌额": 0.2,
                "涨跌幅": 2,
            }
        ]

    def weibo(self) -> list[dict]:
        return [{"name": "万科A", "rate": 7.5}, {"name": "无名", "rate": 1}]

    def notices(self, notice_type: str, day) -> list[dict]:
        if notice_type in self._notice_error_types:
            raise RuntimeError("notice down")
        slug = {
            "重大事项": "major",
            "风险提示": "risk",
            "资产重组": "reorg",
            "持股变动": "hold",
        }[notice_type]
        return [
            {
                "代码": "600000",
                "名称": "浦发银行",
                "公告标题": notice_type,
                "公告日期": day.isoformat(),
                "网址": f"https://data.eastmoney.com/notices/detail/600000/AN{slug}.html",
            }
        ]

    def cctv(self, day) -> list[dict]:
        if self._cctv_should_not_run:
            raise AssertionError("cctv fetched before broadcast")
        return [{"title": "国内联播", "content": "正文"}]

    def universe_names(self) -> list[tuple[str, str]]:
        return [("sz.000002", "万 科Ａ")]


class HotListRecordTests(unittest.TestCase):
    def test_local_name_and_bar_fill_a_rank_when_quotes_are_missing(self) -> None:
        records = hot_list_records(
            [{"sc": "SH600519", "rk": 1}],
            names={"sh.600519": "贵州茅台"},
            bars={"sh.600519": {"close": 1400, "preclose": 1380, "pct_chg": 1.45}},
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["股票名称"], "贵州茅台")
        self.assertEqual(records[0]["当前排名"], 1)
        self.assertEqual(records[0]["最新价"], 1400)
        self.assertEqual(records[0]["涨跌额"], 20)
        self.assertEqual(records[0]["涨跌幅"], 1.45)
        self.assertNotIn("排名较昨日变动", records[0])

    def test_quote_wins_and_surge_keeps_the_rank_change(self) -> None:
        records = hot_list_records(
            [{"sc": "SZ000001", "rk": 3, "hrc": 12}],
            names={"sz.000001": "旧名"},
            quotes={
                "SZ000001": {
                    "name": "平安银行",
                    "close": 10,
                    "pct": 1,
                    "change": 0.1,
                }
            },
            bars={"sz.000001": {"close": 9, "preclose": 8, "pct_chg": 12}},
            surge=True,
        )
        self.assertEqual(records[0]["股票名称"], "平安银行")
        self.assertEqual(records[0]["最新价"], 10)
        self.assertEqual(records[0]["涨跌额"], 0.1)
        self.assertEqual(records[0]["排名较昨日变动"], 12)

    def test_drops_rows_without_a_usable_code(self) -> None:
        records = hot_list_records(
            [{"sc": "??"}, {"rk": 1}],
            names={},
        )
        self.assertEqual(records, [])
