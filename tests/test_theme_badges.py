"""Unit tests for concept theme badge rules (stdlib unittest)."""

from __future__ import annotations

import unittest

from app.themes.badges import (
    SIGN_COLD,
    SIGN_FLAT,
    SIGN_HOT,
    build_members,
    judge_group_a,
    judge_pair,
    judge_satellite,
    percentiles_from_heats,
    sign_delta,
    window_delta,
)
from app.themes.medicine import MEDICINE_THEME


class PercentileTests(unittest.TestCase):
    def test_hottest_is_zero(self) -> None:
        pct = percentiles_from_heats({"a": 1.0, "b": 5.0, "c": 10.0})
        self.assertEqual(pct["a"], 0.0)
        self.assertEqual(pct["c"], 1.0)
        self.assertAlmostEqual(pct["b"], 0.5)


class SignTests(unittest.TestCase):
    def test_window_delta_hotter(self) -> None:
        self.assertEqual(window_delta(20.0, 10.0), 10.0)
        self.assertEqual(sign_delta(10.0, 5.0), SIGN_HOT)
        self.assertEqual(sign_delta(3.0, 5.0), SIGN_FLAT)
        self.assertEqual(sign_delta(-8.0, 5.0), SIGN_COLD)


class GroupABadgeTests(unittest.TestCase):
    def _members(self, deltas: list[float], pcts: list[float] | None = None):
        boards = [
            ("308014", "创新药"),
            ("308572", "仿制药一致性评价"),
            ("301565", "医药电商"),
        ]
        heat_d0 = {code: 50.0 for code, _ in boards}
        heat_as = {
            code: 50.0 - delta for (code, _), delta in zip(boards, deltas)
        }
        if pcts is None:
            pcts = [0.2, 0.3, 0.4]
        pct_d0 = {code: 0.2 for code, _ in boards}
        pct_as = {code: p for (code, _), p in zip(boards, pcts)}
        return build_members(
            boards, heat_d0, heat_as, pct_d0, pct_as, MEDICINE_THEME.epsilon
        )

    def test_same_heat(self) -> None:
        badge = judge_group_a(
            self._members([12.0, 10.0, 9.0], pcts=[0.25, 0.28, 0.30]),
            MEDICINE_THEME,
        )
        self.assertEqual(badge.label, "同热")

    def test_same_cold(self) -> None:
        badge = judge_group_a(
            self._members([-12.0, -10.0, -9.0], pcts=[0.55, 0.58, 0.60]),
            MEDICINE_THEME,
        )
        self.assertEqual(badge.label, "同冷")

    def test_leader_only(self) -> None:
        badge = judge_group_a(self._members([20.0, 2.0, 1.0]), MEDICINE_THEME)
        self.assertEqual(badge.label, "仅龙头热")

    def test_split_by_direction(self) -> None:
        badge = judge_group_a(self._members([12.0, -10.0, 2.0]), MEDICINE_THEME)
        self.assertEqual(badge.label, "拆开")

    def test_split_by_spread(self) -> None:
        # All flat-ish but percentiles diverge a lot.
        members = self._members([2.0, 1.0, 0.0], pcts=[0.1, 0.5, 0.9])
        # Force start spread small via rebuilding with same end spread large:
        boards = [(m.board_code, m.board_name) for m in members]
        heat_d0 = {m.board_code: 40.0 for m in members}
        heat_as = {m.board_code: 38.0 for m in members}
        pct_d0 = {m.board_code: 0.4 for m in members}
        pct_as = {"308014": 0.05, "308572": 0.4, "301565": 0.85}
        members = build_members(
            boards, heat_d0, heat_as, pct_d0, pct_as, MEDICINE_THEME.epsilon
        )
        badge = judge_group_a(members, MEDICINE_THEME)
        self.assertEqual(badge.label, "拆开")


class PairBadgeTests(unittest.TestCase):
    def test_a_hot_b_cold(self) -> None:
        badge = judge_pair(12.0, -10.0, 0.4, 0.2, 0.3, 0.5, MEDICINE_THEME)
        self.assertEqual(badge.label, "A热B冷")

    def test_same_direction_with_gap_sublabel(self) -> None:
        badge = judge_pair(12.0, 10.0, 0.2, 0.1, 0.25, 0.45, MEDICINE_THEME)
        self.assertEqual(badge.label, "同向")
        self.assertEqual(badge.sublabel, "缺口扩大")
        self.assertEqual(badge.detail, "同热")


class SatelliteTests(unittest.TestCase):
    def test_burst_by_percentile(self) -> None:
        badge = judge_satellite(
            "309081",
            "减肥药",
            40.0,
            30.0,
            0.05,
            [5.0, 4.0, 3.0],
            MEDICINE_THEME,
            "同热",
        )
        self.assertEqual(badge.label, "爆发中")
        self.assertIn("同热", badge.detail)

    def test_quiet(self) -> None:
        badge = judge_satellite(
            "309081",
            "减肥药",
            40.0,
            38.0,
            0.5,
            [12.0, 10.0, 9.0],
            MEDICINE_THEME,
            "同热",
        )
        self.assertEqual(badge.label, "安静")


if __name__ == "__main__":
    unittest.main()
