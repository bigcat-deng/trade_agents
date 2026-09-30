"""Near-end vs full-window trend helpers for theme readings."""

from __future__ import annotations

import unittest

from app.interpret.medicine_theme import (
    _ab_near_relation,
    _near_end_block,
    _near_word_from_vals,
    _pct_trend_word,
    _series_trend_slice,
)


class NearEndTrendTests(unittest.TestCase):
    def test_percentile_smaller_is_warming(self) -> None:
        self.assertEqual(_pct_trend_word(0.78, 0.29), "升温")
        self.assertEqual(_pct_trend_word(0.29, 0.78), "降温")
        self.assertEqual(_pct_trend_word(0.30, 0.32), "走平")

    def test_trough_rebound_counts_as_warming(self) -> None:
        # Endpoint flat/cooler, but rebound from intra-window cold peak.
        self.assertEqual(
            _near_word_from_vals([0.64, 0.70, 0.72, 0.68, 0.66]),
            "升温",
        )
        self.assertEqual(
            _near_word_from_vals([0.30, 0.40, 0.50, 0.60, 0.70]),
            "降温",
        )

    def test_ab_near_both_warming_is_tongre(self) -> None:
        self.assertEqual(_ab_near_relation("升温", "升温"), "同热（同向）")
        self.assertEqual(_ab_near_relation("降温", "降温"), "同冷（同向）")

    def test_property_like_rebound_ab_near_tongre(self) -> None:
        series_a = [
            {"trade_date": "2026-09-01", "value": 0.11},
            {"trade_date": "2026-09-08", "value": 0.20},
            {"trade_date": "2026-09-15", "value": 0.45},
            {"trade_date": "2026-09-21", "value": 0.76},
            {"trade_date": "2026-09-22", "value": 0.72},
            {"trade_date": "2026-09-23", "value": 0.66},
            {"trade_date": "2026-09-24", "value": 0.56},
            {"trade_date": "2026-09-28", "value": 0.45},
            {"trade_date": "2026-09-29", "value": 0.29},
        ]
        series_b = [
            {"trade_date": "2026-09-01", "value": 0.44},
            {"trade_date": "2026-09-08", "value": 0.50},
            {"trade_date": "2026-09-15", "value": 0.55},
            {"trade_date": "2026-09-21", "value": 0.61},
            {"trade_date": "2026-09-22", "value": 0.64},
            {"trade_date": "2026-09-23", "value": 0.70},
            {"trade_date": "2026-09-24", "value": 0.72},
            {"trade_date": "2026-09-28", "value": 0.68},
            {"trade_date": "2026-09-29", "value": 0.66},
        ]
        slice_a = _series_trend_slice(series_a)
        slice_b = _series_trend_slice(series_b)
        assert slice_a is not None and slice_b is not None
        self.assertEqual(slice_a["near_word"], "升温")
        self.assertEqual(slice_b["near_word"], "升温")
        self.assertEqual(slice_a["window_word"], "降温")
        self.assertEqual(slice_b["window_word"], "降温")

        block = "\n".join(
            _near_end_block(
                {
                    "series_group_a": series_a,
                    "series_group_b": series_b,
                    "badge_ab": {
                        "label": "同向",
                        "sublabel": None,
                        "detail": "同冷",
                    },
                },
                "建筑链",
                "基建",
            )
        )
        self.assertIn("A↔B近端：同热（同向）", block)
        self.assertIn("整窗徽章：同向—同冷", block)
        self.assertIn("禁止写成「同冷」同向", block)


if __name__ == "__main__":
    unittest.main()
