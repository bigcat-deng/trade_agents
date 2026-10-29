"""Name/alias matching and related-ETF enrichment."""

from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from app.market_data.etf_scale import format_aum_yi
from app.market_data.related_etfs import (
    RelatedEtfRow,
    _daily_yield_rate,
    _ratio_text,
    build_related_etf_rows,
    find_related_etfs,
    keywords_for_board,
    related_etf_view,
)


UNIVERSE = [
    ("sh.512480", "国联安半导体ETF"),
    ("sh.512760", "国泰CES芯片ETF"),
    ("sh.515120", "广发中证创新药产业ETF"),
    ("sh.510300", "华泰柏瑞沪深300ETF"),
    ("sh.516670", "招商中证畜牧养殖ETF"),
    ("sz.159865", "国泰中证畜牧养殖ETF"),
    ("sz.159165", "永赢中证畜牧养殖产业ETF"),
    ("sh.512010", "易方达沪深300医药ETF"),
]


def _bar(day: date, close: float, *, open_: float | None = None) -> dict:
    open_px = close if open_ is None else open_
    return {
        "trade_date": day,
        "open": open_px,
        "high": max(open_px, close) + 0.01,
        "low": min(open_px, close) - 0.01,
        "close": close,
        "volume": 1.0,
    }


class RelatedEtfKeywordTests(unittest.TestCase):
    def test_pork_gets_livestock_alias(self) -> None:
        keys = keywords_for_board("猪肉")
        self.assertIn("猪肉", keys)
        self.assertIn("畜牧养殖", keys)

    def test_stem_strips_concept_suffix(self) -> None:
        keys = keywords_for_board("煤化工概念")
        self.assertIn("煤化工", keys)


class RelatedEtfMatchTests(unittest.TestCase):
    def test_exact_name_beats_alias(self) -> None:
        rows = find_related_etfs("创新药", UNIVERSE, limit=5)
        self.assertTrue(rows)
        self.assertEqual(rows[0].code, "sh.515120")
        self.assertEqual(rows[0].matched, "创新药")

    def test_pork_uses_alias(self) -> None:
        rows = find_related_etfs("猪肉", UNIVERSE, limit=5)
        codes = [row.code for row in rows]
        self.assertEqual(
            codes,
            ["sh.516670", "sz.159165", "sz.159865"],
        )
        self.assertTrue(all(row.matched == "畜牧养殖" for row in rows))

    def test_semiconductor_alias_chip(self) -> None:
        rows = find_related_etfs("半导体", UNIVERSE, limit=5)
        codes = {row.code for row in rows}
        self.assertIn("sh.512480", codes)
        self.assertIn("sh.512760", codes)

    def test_limit_and_empty(self) -> None:
        self.assertEqual(find_related_etfs("创新药", UNIVERSE, limit=1)[0].code, "sh.515120")
        self.assertEqual(find_related_etfs("没有这个主题", UNIVERSE), [])


class RelatedEtfEnrichTests(unittest.TestCase):
    def test_drops_codes_without_ths_bars(self) -> None:
        as_of = date(2026, 10, 27)

        def fake_fetch(code: str, start: date, end: date, **_kwargs):
            if code == "516670":
                raise RuntimeError("同花顺没有这个代码的日K")
            if code == "159865":
                return [_bar(date(2026, 10, 24), 0.53), _bar(as_of, 0.52)]
            raise RuntimeError("同花顺没有这个代码的日K")

        with (
            patch(
                "app.market_data.related_etfs.fetch_ths_daily_bars",
                side_effect=fake_fetch,
            ),
            patch(
                "app.market_data.related_etfs._chan_reward_risk_ratio",
                return_value=-0.08,
            ),
        ):
            rows = build_related_etf_rows(
                "猪肉",
                UNIVERSE,
                as_of=as_of,
                limit=12,
                share_map={"159865": 1.2e9},
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ths_code, "159865")
        self.assertEqual(rows[0].close, 0.52)
        self.assertEqual(rows[0].shares, 1.2e9)
        self.assertAlmostEqual(rows[0].yield_rate or 0.0, (0.52 - 0.53) / 0.53)
        self.assertAlmostEqual(rows[0].chan_ratio or 0.0, -0.08)

    def test_daily_yield_vs_prev_close(self) -> None:
        bars = [
            _bar(date(2026, 10, 24), 1.0),
            _bar(date(2026, 10, 27), 0.993, open_=1.001),
        ]
        rate = _daily_yield_rate(bars)
        self.assertIsNotNone(rate)
        assert rate is not None
        self.assertLess(rate, 0)
        self.assertAlmostEqual(rate, (0.993 - 1.0) / 1.0)

    def test_sorts_by_yield_descending(self) -> None:
        from app.market_data.related_etfs import _yield_sort_key

        as_of = date(2026, 10, 27)
        samples = [
            RelatedEtfRow(
                code="sh.516670",
                name="A",
                matched="畜牧养殖",
                score=1,
                ths_code="516670",
                trade_date=as_of,
                open=1,
                high=1,
                low=1,
                close=1,
                yield_rate=0.01,
                chan_ratio=1.2,
                shares=None,
            ),
            RelatedEtfRow(
                code="sz.159165",
                name="C",
                matched="畜牧养殖",
                score=1,
                ths_code="159165",
                trade_date=as_of,
                open=1,
                high=1,
                low=1,
                close=1,
                yield_rate=None,
                chan_ratio=None,
                shares=None,
            ),
            RelatedEtfRow(
                code="sz.159865",
                name="B",
                matched="畜牧养殖",
                score=1,
                ths_code="159865",
                trade_date=as_of,
                open=1,
                high=1,
                low=1,
                close=1,
                yield_rate=0.05,
                chan_ratio=0.5,
                shares=None,
            ),
        ]
        ordered = sorted(samples, key=_yield_sort_key)
        self.assertEqual(
            [row.ths_code for row in ordered],
            ["159865", "516670", "159165"],
        )

    def test_view_formats_fields(self) -> None:
        row = RelatedEtfRow(
            code="sz.159865",
            name="国泰中证畜牧养殖ETF",
            matched="畜牧养殖",
            score=900,
            ths_code="159865",
            trade_date=date(2026, 10, 27),
            open=0.522,
            high=0.531,
            low=0.519,
            close=0.52,
            yield_rate=-0.003,
            chan_ratio=-0.083,
            shares=2.2e7,
        )
        view = related_etf_view(row, "/analyze?code=159865")
        self.assertEqual(view["scale_text"], format_aum_yi(2.2e7, 0.52))
        self.assertEqual(view["close_text"], "0.520")
        self.assertEqual(view["yield_text"], "-0.30%")
        self.assertEqual(view["chan_ratio_text"], "-0.08 : 1")
        self.assertEqual(view["analyze_href"], "/analyze?code=159865")

    def test_ratio_text_aligns_to_one(self) -> None:
        self.assertEqual(_ratio_text(1.061), "1.06 : 1")
        self.assertEqual(_ratio_text(None), "—")

    def test_aum_is_shares_times_price(self) -> None:
        # 0.22亿份 * 0.993 ≈ 0.218 亿
        self.assertEqual(format_aum_yi(2.2e7, 0.993), "0.218亿")


if __name__ == "__main__":
    unittest.main()
