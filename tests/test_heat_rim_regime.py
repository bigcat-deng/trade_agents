"""Regime labels from persistent hot cores."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from app.themes.heat_rim_regime import (
    LICENSE_PRESSURE,
    LICENSE_WATCH,
    REGIME_DOMINATE,
    REGIME_FADE,
    REGIME_NONE,
    CoreSnap,
    build_regime_panel_payload,
    candidate_license,
    is_dominate,
    label_series,
    list_persistent_hot_cores,
    list_warming_candidates,
    pick_main,
)


def _d(n: int) -> date:
    return date(2026, 5, 1) + timedelta(days=n)


def _c(
    codes: str,
    *,
    heat: float,
    width: int | None = None,
    asof: float | None = None,
    peak: float | None = None,
    label: str | None = None,
) -> CoreSnap:
    code_set = frozenset(codes.split(","))
    w = width if width is not None else len(code_set)
    a = asof if asof is not None else heat
    p = peak if peak is not None else heat
    return CoreSnap(
        codes=code_set,
        label=label or codes,
        width=w,
        mean_heat=heat,
        asof_heat=a,
        peak_persist=p,
        peak_asof=a if peak is None else max(a, p),
        heat_mass=a * w,
        persist_days=6,
        members=codes,
        lo=0,
        hi=w,
    )


class HeatRimRegimeTests(unittest.TestCase):
    def test_pick_main_asof_peak_first(self) -> None:
        # Higher persist-mean but lower as-of loses to today's hottest persistent cell.
        energy = _c("e1,e2", heat=0.99, width=2, peak=0.99, asof=0.99)
        semi = _c("semi,x,y", heat=0.83, width=3, peak=0.97, asof=1.0)
        self.assertEqual(pick_main([energy, semi]), semi)

    def test_dominate_by_share_or_heat_gap(self) -> None:
        self.assertTrue(is_dominate(h=0.90, s=0.40, h2=0.80))
        self.assertTrue(is_dominate(h=0.90, s=0.20, h2=0.80))
        self.assertFalse(is_dominate(h=0.70, s=0.50, h2=0.60))
        self.assertFalse(is_dominate(h=0.90, s=0.20, h2=0.88))

    def test_persistent_core_finds_hot_plateau(self) -> None:
        dates = [_d(i) for i in range(10)]
        codes = ["a", "b", "semi", "c"]
        names = ["A", "B", "半导体", "C"]
        z = np.full((10, 4), 0.20)
        # semi stays top-hot; neighbors cool — condensed core width 1
        for t in range(4, 10):
            z[t, 2] = 0.90 + 0.01 * (t - 4)
        # a spreading coolish band elsewhere
        for t in range(6, 10):
            z[t, 0] = 0.55
            z[t, 1] = 0.55
        listed = list_persistent_hot_cores(
            dates=dates, codes=codes, names=names, z=z.tolist()
        )
        cores = listed["cores"]
        self.assertTrue(cores)
        tops = {m["board_name"] for c in cores for m in c["members"]}
        self.assertIn("半导体", tops)
        main_codes = max(cores, key=lambda c: c["mean_heat"])["members"]
        self.assertEqual([m["board_name"] for m in main_codes], ["半导体"])

    def test_series_dominate_then_fade(self) -> None:
        days = [
            (_d(0), [_c("semi", heat=0.92), _c("x,y", heat=0.78, width=2)]),
            (_d(1), [_c("semi", heat=0.94), _c("x,y", heat=0.76, width=2)]),
            (_d(2), [_c("semi", heat=0.80), _c("x,y", heat=0.78, width=2)]),
            (_d(3), [_c("x,y", heat=0.70, width=2)]),
        ]
        rows = label_series(days, lookback=8)
        self.assertEqual(rows[0].regime, REGIME_DOMINATE)
        self.assertEqual(rows[1].regime, REGIME_DOMINATE)
        self.assertEqual(rows[2].regime, REGIME_FADE)
        self.assertIn("h_drop", rows[2].fade_flags)
        # old lineage gone, leftover core too weak to dominate → fade
        self.assertEqual(rows[3].regime, REGIME_FADE)
        self.assertIn("lost_persist", rows[3].fade_flags)

    def test_candidate_license_by_regime(self) -> None:
        self.assertEqual(candidate_license(REGIME_DOMINATE), LICENSE_PRESSURE)
        self.assertEqual(candidate_license(REGIME_FADE), LICENSE_WATCH)
        self.assertEqual(candidate_license(REGIME_NONE), LICENSE_WATCH)

    def test_warming_candidates_exclude_main(self) -> None:
        dates = [_d(i) for i in range(12)]
        codes = ["m1", "m2", "c1", "c2", "x"]
        names = ["主1", "主2", "候1", "候2", "冷"]
        z = np.full((12, 5), 0.15)
        # persistent main m1-m2
        for t in range(0, 12):
            z[t, 0] = 0.92
            z[t, 1] = 0.90
        # warming candidate c1-c2 near end (expanding bright)
        for t, val in enumerate([0.42, 0.50, 0.58, 0.66, 0.74, 0.82], start=6):
            z[t, 2] = val
            z[t, 3] = val - 0.02
        main = CoreSnap(
            codes=frozenset({"m1", "m2"}),
            label="主1 → 主2",
            width=2,
            mean_heat=0.91,
            asof_heat=0.91,
            peak_persist=0.92,
            peak_asof=0.92,
            heat_mass=1.82,
            persist_days=6,
            members="主1,主2",
            lo=0,
            hi=2,
        )
        cands = list_warming_candidates(
            dates=dates, codes=codes, names=names, z=z.tolist(), main=main
        )
        self.assertTrue(cands)
        joined = " ".join(c.members for c in cands)
        self.assertIn("候1", joined)
        self.assertNotIn("主1", joined)

    def test_warming_candidates_drop_started(self) -> None:
        dates = [_d(i) for i in range(12)]
        codes = ["m1", "m2", "c1", "c2", "x"]
        names = ["主1", "主2", "候1", "候2", "冷"]
        z = np.full((12, 5), 0.15)
        for t in range(0, 12):
            z[t, 0] = 0.92
            z[t, 1] = 0.90
        for t, val in enumerate([0.42, 0.50, 0.58, 0.66, 0.74, 0.82], start=6):
            z[t, 2] = val
            z[t, 3] = val - 0.02
        main = CoreSnap(
            codes=frozenset({"m1", "m2"}),
            label="主1 → 主2",
            width=2,
            mean_heat=0.91,
            asof_heat=0.91,
            peak_persist=0.92,
            peak_asof=0.92,
            heat_mass=1.82,
            persist_days=6,
            members="主1,主2",
            lo=0,
            hi=2,
        )
        kept = list_warming_candidates(
            dates=dates,
            codes=codes,
            names=names,
            z=z.tolist(),
            main=main,
            started_codes=frozenset(),
        )
        self.assertTrue(kept)
        dropped = list_warming_candidates(
            dates=dates,
            codes=codes,
            names=names,
            z=z.tolist(),
            main=main,
            started_codes=frozenset({"c1", "c2"}),
        )
        self.assertFalse(
            any("候" in c.members for c in dropped),
            msg=f"started patch should be dropped, got {dropped}",
        )

    def test_regime_panel_payload_shows_last_display_days(self) -> None:
        n = 50
        calendar = [_d(i) for i in range(n)]
        codes = ["a", "b", "c"]
        names = {"a": "甲", "b": "乙", "c": "丙"}
        heat_by_day: dict[date, dict[str, float]] = {}
        for i, day in enumerate(calendar):
            heat_by_day[day] = {
                "a": 0.95 if i >= n - 20 else 0.40,
                "b": 0.90 if i >= n - 20 else 0.35,
                "c": 0.30 + 0.01 * (i % 5),
            }
        out = build_regime_panel_payload(
            as_of=calendar[-1],
            calendar=calendar,
            heat_by_day=heat_by_day,
            names=names,
            display_days=10,
            warmup_days=8,
            window_days=12,
        )
        self.assertEqual(len(out["rows"]), 10)
        self.assertEqual(out["rows"][-1]["signal_date"], calendar[-1].isoformat())
        self.assertEqual(out["rows"][0]["signal_date"], calendar[-10].isoformat())
        self.assertIn("现算", out["note"])
        for row in out["rows"]:
            self.assertIn(row["regime"], (REGIME_DOMINATE, REGIME_FADE, REGIME_NONE))
            self.assertIn("cand_license", row)


if __name__ == "__main__":
    unittest.main()
