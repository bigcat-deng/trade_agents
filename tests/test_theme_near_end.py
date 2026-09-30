"""Near-end vs full-window trend helpers for theme readings."""

from __future__ import annotations

import unittest

from app.interpret.medicine_theme import (
    _near_end_block,
    _pct_trend_word,
    _series_trend_slice,
)


class NearEndTrendTests(unittest.TestCase):
    def test_percentile_smaller_is_warming(self) -> None:
        self.assertEqual(_pct_trend_word(0.78, 0.29), "升温")
        self.assertEqual(_pct_trend_word(0.29, 0.78), "降温")
        self.assertEqual(_pct_trend_word(0.30, 0.32), "走平")

    def test_rebound_flags_conflict(self) -> None:
        series_a = [
            {"trade_date": "2026-09-01", "value": 0.25},
            {"trade_date": "2026-09-08", "value": 0.30},
            {"trade_date": "2026-09-13", "value": 0.40},
            {"trade_date": "2026-09-16", "value": 0.55},
            {"trade_date": "2026-09-20", "value": 0.70},
            {"trade_date": "2026-09-22", "value": 0.78},
            {"trade_date": "2026-09-24", "value": 0.65},
            {"trade_date": "2026-09-26", "value": 0.45},
            {"trade_date": "2026-09-29", "value": 0.29},
        ]
        series_b = [
            {"trade_date": "2026-09-01", "value": 0.30},
            {"trade_date": "2026-09-08", "value": 0.35},
            {"trade_date": "2026-09-13", "value": 0.45},
            {"trade_date": "2026-09-16", "value": 0.55},
            {"trade_date": "2026-09-20", "value": 0.65},
            {"trade_date": "2026-09-22", "value": 0.72},
            {"trade_date": "2026-09-24", "value": 0.74},
            {"trade_date": "2026-09-26", "value": 0.70},
            {"trade_date": "2026-09-29", "value": 0.65},
        ]
        slice_a = _series_trend_slice(series_a)
        assert slice_a is not None
        self.assertEqual(slice_a["near_word"], "升温")
        self.assertEqual(slice_a["window_word"], "降温")

        block = "\n".join(
            _near_end_block(
                {"series_group_a": series_a, "series_group_b": series_b},
                "建筑链",
                "基建",
            )
        )
        self.assertIn("近端趋势", block)
        self.assertIn("冲突提示", block)
        self.assertIn("建筑链", block)
        self.assertIn("升温", block)


if __name__ == "__main__":
    unittest.main()
