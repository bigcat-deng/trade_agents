"""MACD cross markers on heat planes."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from app.themes.board_cross_marks import (
    CROSS_STYLE,
    build_cross_mark_overlay,
    empty_cross_mark_overlay,
)


def _days(n: int, start: date = date(2026, 1, 2)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


class BoardCrossMarkTests(unittest.TestCase):
    def test_empty_overlay_has_macd_series_only(self) -> None:
        empty = empty_cross_mark_overlay()
        self.assertEqual(set(CROSS_STYLE), {"macd_up", "macd_down"})
        for key in CROSS_STYLE:
            self.assertEqual(empty[f"{key}_x"], [])
            self.assertEqual(empty[f"{key}_count"], 0)
        self.assertNotIn("heat_up_x", empty)
        self.assertNotIn("heat_down_x", empty)

    def test_maps_macd_events_to_cell_centers(self) -> None:
        days = _days(5)
        window = days[1:4]
        rows = [(day, 100.0, 10.0, 20.0) for day in days]
        events = {
            "macd_up": [days[2]],
            "macd_down": [],
            "heat_up": [],
            "heat_down": [days[2]],
        }
        with patch(
            "app.interpret.cross_stats.list_cross_event_dates",
            return_value=events,
        ):
            overlay = build_cross_mark_overlay(
                ordered_codes=["left", "mid", "right"],
                window_dates=window,
                close_heat_by_code={"mid": rows},
                names={"mid": "中板"},
            )
        self.assertEqual(overlay["macd_up_count"], 1)
        self.assertNotIn("heat_down_count", overlay)
        # mid column index = 1; no offset now that heat ◆ is gone
        self.assertAlmostEqual(overlay["macd_up_x"][0], 1.0)
        self.assertAlmostEqual(overlay["macd_up_y"][0], 1.0)
        self.assertIn("中板", overlay["macd_up_text"][0])
        self.assertEqual(CROSS_STYLE["macd_up"]["symbol"], "x")
        self.assertEqual(CROSS_STYLE["macd_up"]["color"], "#ea580c")
        self.assertEqual(CROSS_STYLE["macd_down"]["color"], "#2563eb")

    def test_skips_events_outside_window(self) -> None:
        days = _days(5)
        window = days[2:4]
        with patch(
            "app.interpret.cross_stats.list_cross_event_dates",
            return_value={
                "macd_up": [days[0]],
                "macd_down": [],
                "heat_up": [],
                "heat_down": [],
            },
        ):
            overlay = build_cross_mark_overlay(
                ordered_codes=["A"],
                window_dates=window,
                close_heat_by_code={"A": [(d, 1, 1, 1) for d in days]},
            )
        self.assertEqual(overlay["macd_up_count"], 0)

    def test_contour_includes_macd_trace_names_only(self) -> None:
        from app.charts.theme_wave import render_theme_wave_contour

        html = render_theme_wave_contour(
            dates=["2026-09-01", "2026-09-02"],
            x=[0.0, 1.0],
            z=[[0.1, 0.9], [0.2, 0.8]],
            x_tickvals=[0.0, 1.0],
            x_ticktext=["A", "B"],
            include_plotlyjs=False,
            return_exceedance={
                "pos_x": [],
                "pos_y": [],
                "neg_x": [],
                "neg_y": [],
            },
            cross_marks={
                "macd_up_x": [0.0],
                "macd_up_y": [1.0],
                "macd_up_text": ["A<br>2026-09-02"],
                "macd_down_x": [1.0],
                "macd_down_y": [0.0],
                "macd_down_text": ["B<br>2026-09-01"],
            },
        )
        self.assertIn("MACD", html)
        self.assertIn("ea580c", html)
        self.assertIn("2563eb", html)
        self.assertNotIn("diamond", html)
        self.assertNotIn("heat_up", html)
        self.assertNotIn("heat_down", html)


if __name__ == "__main__":
    unittest.main()
