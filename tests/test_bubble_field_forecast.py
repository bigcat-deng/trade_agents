"""Bubble structure-field rasterize + prompt template."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.prompts.template import load_prompt
from app.themes.bubble_field_forecast import (
    TEMPLATE_NAME,
    build_bubble_forecast_plane,
    build_bubble_forecast_prompt,
    rasterize_bubble_field,
)


class BubbleFieldForecastTests(unittest.TestCase):
    def test_template_loads(self) -> None:
        tmpl = load_prompt(TEMPLATE_NAME)
        self.assertEqual(tmpl.name, TEMPLATE_NAME)
        self.assertIn("看图续气泡", tmpl.body)
        self.assertIn("{{as_of}}", tmpl.body)

    def test_prompt_render(self) -> None:
        tip = date(2026, 5, 13)
        fwd = [tip + timedelta(days=i) for i in range(1, 6)]
        _tmpl, body = build_bubble_forecast_prompt(tip=tip, forecast_dates=fwd)
        self.assertIn("2026-05-13", body)
        self.assertIn("2026-05-14", body)

    def test_rasterize_peaks_near_blob_center(self) -> None:
        scenario = {
            "days": [
                {
                    "date": "2026-05-14",
                    "blobs": [
                        {
                            "id": "A",
                            "cx": 0.2,
                            "ct": 0.0,
                            "rx": 0.05,
                            "rt": 0.2,
                            "peak": 1.0,
                        }
                    ],
                }
            ]
        }
        field = rasterize_bubble_field(n_boards=21, n_days=5, scenario=scenario)
        self.assertEqual(len(field), 5)
        self.assertEqual(len(field[0]), 21)
        # board index ~0.2*20 = 4
        self.assertGreater(field[0][4], 0.7)
        self.assertGreater(field[0][4], field[0][15])

    def test_plane_appends_forecast_rows(self) -> None:
        hist = [date(2026, 4, 1) + timedelta(days=i) for i in range(40)]
        tip = hist[-1]
        ordered = ["a", "b", "c", "d"]
        names = {c: c for c in ordered}
        heat = {
            day: {c: float(10 + j) for j, c in enumerate(ordered)} for day in hist
        }
        fwd = [tip + timedelta(days=i) for i in range(1, 6)]
        scenario = {
            "thesis": "气泡右移",
            "read_image": "顶端偏左竖脊",
            "days": [
                {
                    "date": d.isoformat(),
                    "note": "测",
                    "blobs": [
                        {
                            "id": "A",
                            "cx": 0.7,
                            "ct": i / 4,
                            "rx": 0.08,
                            "rt": 0.3,
                            "peak": 0.95,
                        }
                    ],
                }
                for i, d in enumerate(fwd)
            ],
        }
        out = build_bubble_forecast_plane(
            tip=tip,
            hist=hist,
            heat_by_day=heat,
            names=names,
            ordered=ordered,
            forecast_dates=fwd,
            scenario=scenario,
        )
        self.assertIsNone(out.get("empty_message"))
        self.assertEqual(len(out["forecast_dates"]), 5)
        self.assertIn("读图", out["scenario_note"])
        self.assertTrue(out["z_short"])


if __name__ == "__main__":
    unittest.main()
