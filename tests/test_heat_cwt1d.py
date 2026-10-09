"""Unit tests for 1D Morlet CWT mode extract / phase forecast."""

from __future__ import annotations

import unittest

import numpy as np

from datetime import date, timedelta

from app.themes.heat_cwt1d import (
    analyze_board_series,
    build_industry_cwt_forecast_plane,
    map_heat_short_to_h,
    phase_forecast_from_mode,
    soft_asymmetric_sine,
    extract_dominant_near_mode,
)


class HeatCwt1dTests(unittest.TestCase):
    def test_map_inverts_heat_short(self) -> None:
        h = map_heat_short_to_h([10.0, 5.0, 1.0, None])
        self.assertTrue(np.isnan(h[3]))
        self.assertGreater(h[2], h[1])
        self.assertGreater(h[1], h[0])

    def test_soft_asym_finite(self) -> None:
        th = np.linspace(0, 2 * np.pi, 50)
        y = soft_asymmetric_sine(th, 0.35)
        self.assertEqual(y.shape, th.shape)
        self.assertTrue(np.all(np.isfinite(y)))

    def test_dominant_mode_on_sine(self) -> None:
        t = np.arange(160, dtype=float)
        # heat_short smaller=hotter; craft oscillating ranks
        hs = 50 + 20 * np.sin(2 * np.pi * t / 20.0)
        mode, pack = extract_dominant_near_mode(map_heat_short_to_h(list(hs)))
        self.assertIsNotNone(mode)
        assert mode is not None
        self.assertGreater(mode.energy_share, 0.05)
        # period should be near 20
        self.assertLess(abs(mode.period - 20.0), 6.0)
        self.assertIn("spectrum", pack)

    def test_analyze_forecast_len(self) -> None:
        t = np.arange(160, dtype=float)
        hs = list(40 + 15 * np.sin(2 * np.pi * t / 16.0))
        out = analyze_board_series(hs)
        self.assertIsNone(out.get("empty_message"))
        self.assertEqual(len(out["forecast"]), 5)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in out["forecast"]))
        tip = float(out["tip_h"])
        fc = phase_forecast_from_mode(
            out["mode"], amp=float(out["amp"]), tip_h=tip
        )
        self.assertEqual(len(fc), 5)
        # One phase step from tip should be modest vs free re-center jumps.
        self.assertLess(abs(fc[0] - tip), 0.35)

    def test_build_plane_appends_forecast(self) -> None:
        hist = [date(2026, 4, 1) + timedelta(days=i) for i in range(80)]
        tip = hist[-1]
        ordered = ["a", "b", "c"]
        names = {c: c for c in ordered}
        heat = {
            day: {
                c: float(20 + 10 * np.sin(2 * np.pi * (i + j) / 16.0) + j)
                for j, c in enumerate(ordered)
            }
            for i, day in enumerate(hist)
        }
        fwd = [tip + timedelta(days=i) for i in range(1, 6)]
        out = build_industry_cwt_forecast_plane(
            tip=tip,
            hist=hist,
            heat_by_day=heat,
            names=names,
            ordered=ordered,
            forecast_dates=fwd,
            context_days=40,
        )
        self.assertIsNone(out.get("empty_message"))
        self.assertEqual(len(out["forecast_dates"]), 5)
        self.assertTrue(out["z_short"])
        self.assertIn("CWT", out["axis_note"])


if __name__ == "__main__":
    unittest.main()
