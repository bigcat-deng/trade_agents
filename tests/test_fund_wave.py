"""Fund-wave self-anomaly helpers."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.themes.fund_wave import (
    build_fund_wave_panel_payload,
    build_industry_fund_plane,
)
from app.themes.heat_seriation import (
    rolling_self_anomaly_series,
    select_top_codes_by_late_strength,
)


class FundWaveTests(unittest.TestCase):
    def test_self_anomaly_spike_outranks_flat_large(self) -> None:
        """Flat large board ~0.5; late spike board ends hotter."""
        start = date(2026, 7, 1)
        hist = [start + timedelta(days=i) for i in range(60)]
        window = hist[-12:]
        values: dict[date, dict[str, float]] = {}
        for i, day in enumerate(hist):
            big = 1000.0
            small = 10.0
            if i >= len(hist) - 3:
                small = 80.0  # spike vs own history
            values[day] = {"big": big, "spike": small}
        series = rolling_self_anomaly_series(
            window_dates=window,
            history_dates=hist,
            codes=["big", "spike"],
            value_by_day=values,
            lookback=40,
            min_periods=20,
        )
        tip_big = series["big"][-1]
        tip_spike = series["spike"][-1]
        self.assertIsNotNone(tip_big)
        self.assertIsNotNone(tip_spike)
        self.assertGreater(tip_spike, tip_big)
        self.assertAlmostEqual(tip_big or 0.0, 0.5, delta=0.08)

    def test_select_top_by_late_strength(self) -> None:
        start = date(2026, 9, 1)
        days = [start + timedelta(days=i) for i in range(8)]
        values = {
            day: {"hot": 100.0 + i, "mid": 50.0, "cold": 1.0}
            for i, day in enumerate(days)
        }
        top = select_top_codes_by_late_strength(
            window_dates=days,
            value_by_day=values,
            candidate_codes=["hot", "mid", "cold"],
            top_n=2,
        )
        self.assertEqual(top, ["hot", "mid"])

    def test_industry_plane_with_history(self) -> None:
        start = date(2026, 7, 1)
        hist = [start + timedelta(days=i) for i in range(55)]
        window = hist[-12:]
        rows = []
        for i, day in enumerate(hist):
            rows.append((day, "a", "甲", 10.0))
            rows.append((day, "b", "乙", 80.0))
            # 丙 spikes at tip
            amt_c = 40.0 if i < len(hist) - 2 else 200.0
            rows.append((day, "c", "丙", amt_c))
        plane = build_industry_fund_plane(
            window_dates=window,
            amount_rows=rows,
            history_dates=hist,
            lookback=40,
        )
        self.assertIsNone(plane.get("empty_message"))
        self.assertEqual(len(plane["board_codes"]), 3)
        tip_z = plane["z_boards"][-1]
        # 丙 should be the hottest tip column among the three
        self.assertEqual(plane["tip_labels"]["text"][0], "丙")
        self.assertGreater(tip_z[plane["board_codes"].index("c")], 0.6)

    def test_panel_payload_rejects_unknown(self) -> None:
        out = build_fund_wave_panel_payload(
            panel="nope", as_of=date(2026, 10, 9), days=40
        )
        self.assertEqual(out.get("error"), "unknown panel")

    def test_industry_plane_respects_frozen_order(self) -> None:
        start = date(2026, 7, 1)
        hist = [start + timedelta(days=i) for i in range(55)]
        window = hist[-12:]
        rows = []
        for day in hist:
            rows.append((day, "a", "甲", 10.0))
            rows.append((day, "b", "乙", 80.0))
            rows.append((day, "c", "丙", 40.0))
        frozen = ["c", "a", "b"]
        plane = build_industry_fund_plane(
            window_dates=window,
            amount_rows=rows,
            history_dates=hist,
            ordered_codes=frozen,
            lookback=40,
        )
        self.assertEqual(plane["board_codes"], frozen)
        self.assertIn("同一叶序", plane["axis_note"])


if __name__ == "__main__":
    unittest.main()
