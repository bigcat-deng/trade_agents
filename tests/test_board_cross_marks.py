"""MACD / heat cross markers on heat planes."""

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
    def test_empty_overlay_has_four_series(self) -> None:
        empty = empty_cross_mark_overlay()
        for key in CROSS_STYLE:
            self.assertEqual(empty[f"{key}_x"], [])
            self.assertEqual(empty[f"{key}_count"], 0)

    def test_maps_events_to_cell_centers_with_offsets(self) -> None:
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
        self.assertEqual(overlay["heat_down_count"], 1)
        # mid column index = 1; MACD left of center, heat right of center
        self.assertAlmostEqual(overlay["macd_up_x"][0], 1.0 - 0.12)
        self.assertAlmostEqual(overlay["heat_down_x"][0], 1.0 + 0.12)
        # window index of days[2] is 1
        self.assertAlmostEqual(overlay["macd_up_y"][0], 1.0)
        self.assertIn("中板", overlay["macd_up_text"][0])
        self.assertEqual(CROSS_STYLE["macd_up"]["symbol"], "x")
        self.assertEqual(CROSS_STYLE["heat_down"]["symbol"], "diamond")
        self.assertEqual(CROSS_STYLE["macd_up"]["color"], "#ea580c")
        self.assertEqual(CROSS_STYLE["heat_down"]["color"], "#2563eb")

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

    def test_contour_includes_cross_trace_names(self) -> None:
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
                "macd_down_x": [],
                "macd_down_y": [],
                "macd_down_text": [],
                "heat_up_x": [],
                "heat_up_y": [],
                "heat_up_text": [],
                "heat_down_x": [1.0],
                "heat_down_y": [0.0],
                "heat_down_text": ["B<br>2026-09-01"],
            },
        )
        # Plotly unicode-escapes Chinese in JSON; check escaped forms.
        self.assertIn("MACD", html)
        self.assertIn("diamond", html)
        self.assertIn("ea580c", html)
        self.assertIn("2563eb", html)


if __name__ == "__main__":
    unittest.main()
