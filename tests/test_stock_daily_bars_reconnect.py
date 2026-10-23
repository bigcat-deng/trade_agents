"""Baostock reconnect waits before the stock daily-bar fallback."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.jobs import sync_stock_daily_bars as job
from app.market_data.normalize import DailyBar


def _bar(source: str) -> DailyBar:
    return DailyBar(
        trade_date=date(2026, 10, 14),
        code="sh.600000",
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        preclose=Decimal("1"),
        volume=1,
        amount=Decimal("1"),
        adjustflag=3,
        turn=None,
        tradestatus=1,
        pct_chg=Decimal("0"),
        is_st=0,
        source=source,
    )


class ReconnectTests(unittest.TestCase):
    def test_empty_baostock_does_not_reconnect(self) -> None:
        sleeps: list[int] = []
        logins = {"n": 0}

        def fetch(_code: str, _start: date, _end: date) -> list[DailyBar]:
            return []

        def login() -> object:
            logins["n"] += 1
            raise AssertionError("login should not run")

        job.time.sleep = lambda seconds: sleeps.append(seconds)  # type: ignore[method-assign]
        job.baostock_kline.fetch_daily_bars = fetch  # type: ignore[method-assign]
        job.akshare_em_kline.fetch_daily_bars = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: []
        )
        job.akshare_tx_kline.fetch_daily_bars = (  # type: ignore[method-assign]
            lambda *_args, **_kwargs: []
        )
        job.bs.login = login  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError) as caught:
            job.fetch_with_fallback("sh.600000", date(2026, 10, 8), date(2026, 10, 14))
        self.assertIn("baostock: empty", str(caught.exception))
        self.assertEqual(sleeps, [])
        self.assertEqual(logins["n"], 0)

    def test_failure_reconnects_then_returns_baostock(self) -> None:
        sleeps: list[int] = []
        attempts = {"n": 0}

        def fetch(_code: str, _start: date, _end: date) -> list[DailyBar]:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("网络接收错误。")
            return [_bar("baostock")]

        job.time.sleep = lambda seconds: sleeps.append(seconds)  # type: ignore[method-assign]
        job.baostock_kline.fetch_daily_bars = fetch  # type: ignore[method-assign]
        job.bs.logout = lambda: None  # type: ignore[method-assign]
        job.bs.login = lambda: type("Login", (), {"error_code": "0", "error_msg": ""})()  # type: ignore[method-assign]

        source, bars = job.fetch_with_fallback(
            "sh.600000", date(2026, 10, 8), date(2026, 10, 14)
        )
        self.assertEqual(source, "baostock")
        self.assertEqual(len(bars), 1)
        self.assertEqual(sleeps, [60, 120])
        self.assertEqual(attempts["n"], 3)

    def test_three_reconnects_then_eastmoney(self) -> None:
        sleeps: list[int] = []

        def fetch(_code: str, _start: date, _end: date) -> list[DailyBar]:
            raise RuntimeError("网络接收错误。")

        def eastmoney(_code: str, _start: date, _end: date) -> list[DailyBar]:
            return [_bar("akshare_em")]

        job.time.sleep = lambda seconds: sleeps.append(seconds)  # type: ignore[method-assign]
        job.baostock_kline.fetch_daily_bars = fetch  # type: ignore[method-assign]
        job.akshare_em_kline.fetch_daily_bars = eastmoney  # type: ignore[method-assign]
        job.bs.logout = lambda: None  # type: ignore[method-assign]
        job.bs.login = lambda: type("Login", (), {"error_code": "0", "error_msg": ""})()  # type: ignore[method-assign]

        source, bars = job.fetch_with_fallback(
            "sh.600000", date(2026, 10, 8), date(2026, 10, 14)
        )
        self.assertEqual(source, "akshare_em")
        self.assertEqual(bars[0].source, "akshare_em")
        self.assertEqual(sleeps, [60, 120, 180])


if __name__ == "__main__":
    unittest.main()
