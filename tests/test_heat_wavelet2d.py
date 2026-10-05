"""2D heat wavelet uses native board columns, not densified plot columns."""

from __future__ import annotations

import unittest

from app.themes.heat_seriation import densify_hotness_plane
from app.themes.heat_wavelet2d import analyze_heat_wavelet2d


class HeatWaveletDensifyTests(unittest.TestCase):
    def test_accepts_densified_plane_by_taking_board_columns(self) -> None:
        names = ["A", "B", "C", "D"]
        codes = ["a", "b", "c", "d"]
        # 12 days × 4 boards of mild variation (wavelet needs some structure).
        z_raw = [
            [0.1 + 0.02 * c + 0.01 * t for c in range(4)] for t in range(12)
        ]
        theme_x = [float(i) for i in range(4)]
        _dense_x, dense_z = densify_hotness_plane(
            theme_x=theme_x, z_short=z_raw, densify=4
        )
        self.assertGreater(len(dense_z[0]), len(codes))

        result = analyze_heat_wavelet2d(
            z_short=dense_z,
            dates=[f"2026-09-{i+1:02d}" for i in range(12)],
            board_names=names,
            board_codes=codes,
            as_of="2026-09-12",
            axis_note="test",
            feature_top_n=2,
        )
        self.assertIsNone(result.get("empty_message"))
        occ = result["features"]["occupancy"]
        self.assertEqual(len(occ), 2)
        self.assertIn(occ[0]["board_code"], codes)

    def test_native_board_plane_unchanged(self) -> None:
        names = ["A", "B", "C"]
        codes = ["a", "b", "c"]
        z_raw = [[0.2 * c + 0.01 * t for c in range(3)] for t in range(16)]
        result = analyze_heat_wavelet2d(
            z_short=z_raw,
            dates=[f"d{i}" for i in range(16)],
            board_names=names,
            board_codes=codes,
            as_of="d15",
            axis_note="test",
            feature_top_n=3,
        )
        self.assertIsNone(result.get("empty_message"))
        self.assertEqual(len(result["features"]["occupancy"]), 3)


if __name__ == "__main__":
    unittest.main()
