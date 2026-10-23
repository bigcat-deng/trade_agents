"""Industry plan rows group by state, then by reward:risk."""

from __future__ import annotations

import unittest

from app.levels.industry_rank import (
    BEARISH,
    BULLISH,
    SIDEWAYS,
    IndustryPlanRow,
    _sort_key,
)


def _row(code: str, state: str | None, ratio: float | None) -> IndustryPlanRow:
    return IndustryPlanRow(
        code=code,
        name=code,
        trade_date=None,
        close=None,
        target=None,
        buy=None,
        stop=None,
        value=None,
        ratio=ratio,
        note=None,
        state=state,
        position=None,
        step=None,
    )


class IndustryRankSortTests(unittest.TestCase):
    def test_groups_bullish_sideways_bearish_then_ratio(self) -> None:
        rows = [
            _row("bear-high", BEARISH, 9),
            _row("bull-low", BULLISH, 1),
            _row("side-none", SIDEWAYS, None),
            _row("side-mid", SIDEWAYS, 3),
            _row("side-high", SIDEWAYS, 5),
            _row("bull-none", BULLISH, None),
            _row("missing", None, 100),
        ]
        ordered = [row.code for row in sorted(rows, key=_sort_key)]
        self.assertEqual(
            ordered,
            [
                "bull-low",
                "bull-none",
                "side-high",
                "side-mid",
                "side-none",
                "bear-high",
                "missing",
            ],
        )
