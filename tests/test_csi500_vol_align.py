"""CSI 500 volume scaled onto return volatility."""

from __future__ import annotations

import unittest
from datetime import date

from app.market_data.csi500 import csi500_overlay_series, scale_to_peer_volatility


class ScaleToPeerVolatilityTests(unittest.TestCase):
    def test_maps_source_onto_peer_mean_and_sigma(self) -> None:
        peer = [0.01, 0.02, 0.03]
        source = [100.0, 200.0, 300.0]
        scaled = scale_to_peer_volatility(source, peer)
        self.assertEqual(len(scaled), 3)
        for got, want in zip(scaled, peer):
            self.assertIsNotNone(got)
            self.assertAlmostEqual(got, want)

    def test_preserves_none_and_needs_two_pairs(self) -> None:
        self.assertEqual(
            scale_to_peer_volatility([1.0, None], [0.1, 0.2]),
            [None, None],
        )
        source = [10.0, None, 30.0]
        peer = [0.0, 0.1, 0.2]
        scaled = scale_to_peer_volatility(source, peer)
        self.assertIsNone(scaled[1])
        self.assertIsNotNone(scaled[0])
        self.assertIsNotNone(scaled[2])

    def test_overlay_series_keeps_raw_volume_and_scaled_x(self) -> None:
        days = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]
        closes = {
            date(2026, 8, 31): 100.0,
            date(2026, 9, 1): 102.0,
            date(2026, 9, 2): 101.0,
            date(2026, 9, 3): 104.0,
        }
        volumes = {
            date(2026, 9, 1): 100.0,
            date(2026, 9, 2): 200.0,
            date(2026, 9, 3): 300.0,
        }
        overlay = csi500_overlay_series(days, closes=closes, volumes=volumes)
        self.assertEqual(overlay["volumes"], [100.0, 200.0, 300.0])
        self.assertEqual(len(overlay["returns"]), 3)
        self.assertEqual(len(overlay["volumes_scaled"]), 3)
        for raw, scaled in zip(overlay["volumes"], overlay["volumes_scaled"]):
            self.assertIsNotNone(scaled)
            self.assertNotAlmostEqual(scaled, raw)


class CsiRowHoverScriptTests(unittest.TestCase):
    def test_contour_html_binds_paper_wide_row_mark(self) -> None:
        from app.charts.theme_wave import render_theme_wave_contour

        html = render_theme_wave_contour(
            dates=["2026-09-01", "2026-09-02", "2026-09-03"],
            x=[0.0, 1.0],
            z=[[0.1, 0.9], [0.2, 0.8], [0.3, 0.7]],
            x_tickvals=[0.0, 1.0],
            x_ticktext=["A", "B"],
            include_plotlyjs=False,
            csi500_returns=[0.01, -0.02, 0.03],
            csi500_volumes=[1e8, 2e8, 1.5e8],
            csi500_volumes_scaled=[0.01, -0.02, 0.03],
        )
        self.assertIn("plotly_hover", html)
        self.assertIn("plotly_doubleclick", html)
        self.assertIn("xaxis2.autorange", html)
        self.assertIn("xref: 'paper'", html)
        self.assertIn("中证500日收益", html)
        self.assertIn("中证500成交量", html)

    def test_contour_without_csi_has_no_row_mark_script(self) -> None:
        from app.charts.theme_wave import render_theme_wave_contour

        html = render_theme_wave_contour(
            dates=["2026-09-01", "2026-09-02"],
            x=[0.0, 1.0],
            z=[[0.1, 0.9], [0.2, 0.8]],
            x_tickvals=[0.0, 1.0],
            x_ticktext=["A", "B"],
            include_plotlyjs=False,
        )
        self.assertNotIn("plotly_hover", html)


if __name__ == "__main__":
    unittest.main()
