"""Industry heat forecast prompt template fill (no live LLM call)."""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from app.prompts.template import load_prompt
from app.themes.llm_heat_forecast import (
    TEMPLATE_NAME,
    build_industry_heat_forecast_prompt,
    build_llm_forecast_plane,
)


class LlmHeatForecastTests(unittest.TestCase):
    def test_template_loads(self) -> None:
        tmpl = load_prompt(TEMPLATE_NAME)
        self.assertEqual(tmpl.name, TEMPLATE_NAME)
        self.assertIn("{{as_of}}", tmpl.body)
        self.assertIn("{{hottest_list}}", tmpl.body)

    def test_prompt_embeds_live_fields(self) -> None:
        tip = date(2026, 5, 13)
        hist = [tip - timedelta(days=i) for i in range(9, -1, -1)]
        # Make weekdays-ish unique dates already
        hist = [date(2026, 5, 1) + timedelta(days=i) for i in range(10)]
        tip = hist[-1]
        heat = {
            day: {"a": 2.0 + i * 0.1, "b": 20.0, "c": 50.0}
            for i, day in enumerate(hist)
        }
        names = {"a": "半导体", "b": "银行", "c": "白酒"}

        with (
            patch(
                "app.themes.llm_heat_forecast.fetch_heat_dates_ending",
                side_effect=[
                    [tip],
                    hist,
                ],
            ),
            patch(
                "app.themes.llm_heat_forecast.fetch_industry_heat_window",
                return_value=[
                    (day, code, names[code], heat[day][code], None)
                    for day in hist
                    for code in ("a", "b", "c")
                ],
            ),
            patch(
                "app.themes.llm_heat_forecast.fetch_trading_dates_after",
                return_value=[
                    tip + timedelta(days=1),
                    tip + timedelta(days=2),
                    tip + timedelta(days=3),
                    tip + timedelta(days=4),
                    tip + timedelta(days=5),
                ],
            ),
            patch(
                "app.themes.llm_heat_forecast._regime_summary_line",
                return_value="无主线；主线=半导体；许可=可关注；候选=银行",
            ),
        ):
            template, body, resolved, ctx = build_industry_heat_forecast_prompt(tip)

        self.assertEqual(resolved, tip)
        self.assertIn(tip.isoformat(), body)
        self.assertIn("半导体", body)
        self.assertIn("无主线", body)
        self.assertEqual(len(ctx["forecast_dates"]), 5)
        self.assertEqual(template.name, TEMPLATE_NAME)

    def test_llm_plane_applies_warm_cool(self) -> None:
        hist = [date(2026, 5, 1) + timedelta(days=i) for i in range(40)]
        tip = hist[-1]
        heat = {
            day: {"a": 3.0, "b": 10.0, "c": 40.0}
            for day in hist
        }
        names = {"a": "半导体", "b": "贵金属", "c": "白酒"}
        fwd = [tip + timedelta(days=i) for i in range(1, 6)]
        scenario = {
            "thesis": "测试",
            "days": [
                {
                    "date": d.isoformat(),
                    "regime_guess": "无主线",
                    "warm": ["贵金属"],
                    "cool": ["半导体"],
                    "note": "测",
                }
                for d in fwd
            ],
        }
        out = build_llm_forecast_plane(
            tip=tip,
            hist=hist,
            heat=heat,
            names=names,
            forecast_dates=fwd,
            scenario=scenario,
            ordered_codes=["a", "b", "c"],
        )
        self.assertIsNone(out.get("empty_message"))
        self.assertEqual(len(out["forecast_dates"]), 5)
        self.assertIn("测试", out["scenario_note"])

if __name__ == "__main__":
    unittest.main()
