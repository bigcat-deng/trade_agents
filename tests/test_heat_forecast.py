"""Industry heat 5-day forecast helpers."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.themes.heat_forecast import (
    build_industry_heat_forecast_payload,
    extrapolate_series,
    resolve_forecast_dates,
    synthesize_trading_days,
)


def _d(n: int) -> date:
    return date(2026, 1, 2) + timedelta(days=n)


class HeatForecastTests(unittest.TestCase):
    def test_synthesize_skips_weekends(self) -> None:
        # 2026-01-02 is Friday
        out = synthesize_trading_days(date(2026, 1, 2), 3)
        self.assertEqual(out, [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)])

    def test_resolve_prefers_known_forward(self) -> None:
        known = [date(2026, 9, 25), date(2026, 9, 28)]
        out = resolve_forecast_dates(
            as_of=date(2026, 9, 24), n=5, known_forward=known
        )
        self.assertEqual(out[:2], known)
        self.assertEqual(len(out), 5)
        self.assertTrue(all(d > date(2026, 9, 24) for d in out))

    def test_extrapolate_follows_downtrend_damped(self) -> None:
        # heat_short smaller = hotter; falling series = warming
        series = [10.0 - 0.5 * i for i in range(12)]
        preds = extrapolate_series(series, horizon=5, lookback=12, damp=0.85)
        self.assertEqual(len(preds), 5)
        self.assertLess(preds[0], series[-1])
        # damping: step sizes shrink
        steps = [preds[0] - series[-1]] + [
            preds[i] - preds[i - 1] for i in range(1, 5)
        ]
        self.assertLess(abs(steps[-1]), abs(steps[0]) + 1e-9)

    def test_payload_appends_forecast_days(self) -> None:
        hist = [_d(i) for i in range(60)]
        codes = ["a", "b", "c"]
        names = {"a": "甲", "b": "乙", "c": "丙"}
        heat: dict[date, dict[str, float]] = {}
        for i, day in enumerate(hist):
            heat[day] = {
                "a": 5.0 - 0.02 * i,
                "b": 8.0,
                "c": 12.0 + 0.01 * i,
            }
        fwd = resolve_forecast_dates(as_of=hist[-1], n=5, known_forward=[])
        out = build_industry_heat_forecast_payload(
            as_of=hist[-1],
            history_dates=hist,
            heat_by_day=heat,
            names=names,
            forecast_dates=fwd,
            context_days=20,
        )
        self.assertIsNone(out.get("empty_message"))
        self.assertEqual(len(out["forecast_dates"]), 5)
        self.assertEqual(len(out["context_dates"]), 20)
        self.assertEqual(len(out["dates"]), 25)
        self.assertEqual(out["board_count"], 3)
        self.assertTrue(out["z_short"])
        self.assertIn("推演", out["scenario_note"])


if __name__ == "__main__":
    unittest.main()
