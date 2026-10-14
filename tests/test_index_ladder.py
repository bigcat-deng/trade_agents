"""Size-ladder window math: rebase, cross-section range, own-window position."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.market_data.index_ladder import INDICES, align_breadth, build_payload


def _series(closes: list[float]) -> dict[date, tuple[float, float, float]]:
    start = date(2026, 5, 18)
    out = {}
    for offset, close in enumerate(closes):
        day = start + timedelta(days=offset)
        out[day] = (close + 1.0, close - 1.0, close)
    return out


class BuildPayloadTests(unittest.TestCase):
    def test_return_spread_and_position(self) -> None:
        # Five sessions. 上证50 ends −10%, 国证2000 ends −50%.
        closes = {
            "上证50": [100.0, 100.0, 100.0, 100.0, 90.0],
            "沪深300": [100.0, 100.0, 100.0, 100.0, 80.0],
            "中证500": [100.0, 100.0, 100.0, 100.0, 70.0],
            "中证1000": [100.0, 100.0, 100.0, 100.0, 60.0],
            "国证2000": [100.0, 90.0, 80.0, 70.0, 50.0],
        }
        bars = {name: _series(values) for name, values in closes.items()}
        end = date(2026, 5, 22)
        payload = build_payload(bars, n=5, as_of=end)

        self.assertEqual(payload["n"], 5)
        self.assertEqual(payload["returns_pct"]["上证50"][0], 0.0)
        self.assertEqual(payload["returns_pct"]["上证50"][-1], -10.0)
        self.assertEqual(payload["returns_pct"]["国证2000"][-1], -50.0)
        self.assertEqual(payload["range_pp"][-1], 40.0)
        self.assertEqual(payload["spread_50_2000_pp"][-1], 40.0)
        self.assertEqual(payload["snapshot"]["上证50"]["position"], 0.0)
        self.assertEqual(payload["snapshot"]["国证2000"]["position"], 0.0)
        self.assertEqual(len(INDICES), 5)

    def test_flat_avg_sits_at_mid_range(self) -> None:
        bars = {
            name: _series([10.0, 10.0, 10.0, 10.0, 10.0])
            for name, _code, _color in INDICES
        }
        # high = close+1, low = close-1, so avg is the close and is flat.
        payload = build_payload(bars, n=5, as_of=date(2026, 5, 22))
        self.assertEqual(payload["snapshot"]["沪深300"]["position"], 0.5)
        self.assertEqual(payload["range_pp"][-1], 0.0)


class AlignBreadthTests(unittest.TestCase):
    def test_thin_day_is_left_blank_and_down_is_negative(self) -> None:
        days = [date(2026, 9, d) for d in (21, 22, 23, 24)]
        counts = {
            days[0]: (2000, 3000, 100, 5100),
            days[1]: (2100, 2900, 100, 5100),
            days[2]: (1600, 3400, 100, 5100),
            days[3]: (1400, 900, 20, 2320),
        }
        aligned = align_breadth(days, counts)
        self.assertEqual(aligned["up"][:3], [2000, 2100, 1600])
        self.assertEqual(aligned["down"][0], -3000)
        self.assertIsNone(aligned["up"][3])
        self.assertIsNone(aligned["down"][3])
        self.assertEqual(aligned["incomplete"][3], 0)
        self.assertIsNone(aligned["incomplete"][0])
        self.assertAlmostEqual(aligned["up_ratio"][2], round(1600 / 5000 * 100, 1))
        self.assertEqual(aligned["last_complete"]["date"], "2026-09-23")
        self.assertEqual(aligned["last_complete"]["down"], 3400)
