"""Stock-basket heat: name parse, union, and in-universe ranking."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.market_data.board_heat import BoardReturn, compute_heat
from app.themes.stock_basket_wave import (
    match_board_queries,
    parse_name_query,
    union_constituents,
)


@dataclass(frozen=True)
class _Board:
    board_type: str
    board_code: str
    board_name: str


class ParseAndMatchTests(unittest.TestCase):
    def test_parse_splits_and_dedupes(self) -> None:
        self.assertEqual(
            parse_name_query("半导体，新能源车\n算力, 半导体"),
            ["半导体", "新能源车", "算力"],
        )

    def test_exact_name_keeps_industry_and_concept(self) -> None:
        catalog = [
            _Board("industry", "881121", "半导体"),
            _Board("concept", "300001", "半导体"),
            _Board("industry", "881122", "汽车"),
        ]
        matched, unmatched = match_board_queries(["半导体", "没有这个"], catalog)
        self.assertEqual(unmatched, ["没有这个"])
        self.assertEqual(
            {(item.board_type, item.board_code) for item in matched},
            {("industry", "881121"), ("concept", "300001")},
        )

    def test_unique_substring_and_code(self) -> None:
        catalog = [
            _Board("industry", "881121", "半导体"),
            _Board("concept", "300084", "煤化工概念"),
        ]
        matched, unmatched = match_board_queries(["半导", "300084"], catalog)
        self.assertEqual(unmatched, [])
        self.assertEqual(
            {(item.board_type, item.board_code) for item in matched},
            {("industry", "881121"), ("concept", "300084")},
        )


class UnionAndRankTests(unittest.TestCase):
    def test_union_prefers_overlap_then_code(self) -> None:
        codes, names, hits = union_constituents(
            {
                ("industry", "a"): [("sz.000002", "万科"), ("sz.000001", "平安")],
                ("concept", "b"): [("sz.000001", ""), ("sh.600000", "浦发")],
            }
        )
        self.assertEqual(codes, ["sz.000001", "sh.600000", "sz.000002"])
        self.assertEqual(hits["sz.000001"], 2)
        self.assertEqual(names["sz.000001"], "平安")

    def test_heat_ranks_only_inside_selected_universe(self) -> None:
        start = date(2026, 1, 2)
        n = 30
        hot = _price_path("sh.600000", start, n, Decimal("10"), Decimal("0.02"))
        mid = _price_path("sz.000001", start, n, Decimal("10"), Decimal("0.00"))
        cold = _price_path("sz.000002", start, n, Decimal("10"), Decimal("-0.01"))
        rows = compute_heat(hot + mid + cold, board_type="stock")
        last = start + timedelta(days=n - 1)
        by_code = {
            row.board_code: row
            for row in rows
            if row.trade_date == last and row.rank_no is not None
        }
        self.assertEqual(set(by_code), {"sh.600000", "sz.000001", "sz.000002"})
        self.assertEqual({row.universe_n for row in by_code.values()}, {3})
        self.assertEqual(by_code["sh.600000"].rank_no, 1)
        self.assertEqual(by_code["sz.000002"].rank_no, 3)


def _price_path(
    code: str,
    start: date,
    n: int,
    px: Decimal,
    daily: Decimal,
) -> list[BoardReturn]:
    rows: list[BoardReturn] = []
    price = px
    for i in range(n):
        rows.append(
            BoardReturn(
                trade_date=start + timedelta(days=i),
                board_code=code,
                pct_chg=daily * Decimal(100),
                high=price * Decimal("1.01"),
                low=price * Decimal("0.99"),
                close=price,
            )
        )
        price = price * (Decimal(1) + daily)
    return rows


if __name__ == "__main__":
    unittest.main()
