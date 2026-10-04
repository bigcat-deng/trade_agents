"""Tests for fused concept seriation priors."""

from __future__ import annotations

import unittest

from app.themes.heat_seriation import (
    constituent_jaccard,
    name_char_similarity,
    order_by_fused_seriation,
    structural_similarity,
)


class StructuralSimilarityTests(unittest.TestCase):
    def test_name_char_similarity(self) -> None:
        self.assertGreater(
            name_char_similarity("芯片概念", "存储芯片"),
            name_char_similarity("芯片概念", "白酒"),
        )
        self.assertEqual(name_char_similarity("", "芯片"), 0.0)

    def test_constituent_jaccard(self) -> None:
        a = {"sh.600000", "sz.000001", "sh.601318"}
        b = {"sh.600000", "sz.000001"}
        c = {"sz.300750"}
        self.assertAlmostEqual(constituent_jaccard(a, b), 2 / 3)
        self.assertEqual(constituent_jaccard(a, c), 0.0)
        self.assertEqual(constituent_jaccard(set(), b), 0.0)

    def test_structural_theme_boost(self) -> None:
        base = structural_similarity(
            left_code="a",
            right_code="b",
            names={"a": "芯片", "b": "白酒"},
            constituents={"a": {"x"}, "b": {"y"}},
            theme_ids_by_code=None,
        )
        boosted = structural_similarity(
            left_code="a",
            right_code="b",
            names={"a": "芯片", "b": "白酒"},
            constituents={"a": {"x"}, "b": {"y"}},
            theme_ids_by_code={"a": {"semiconductor"}, "b": {"semiconductor"}},
        )
        self.assertGreater(boosted, base)

    def test_fused_order_prefers_overlap_when_traj_weak(self) -> None:
        # Three flat-ish parallel series; structure should pull a-b together.
        series = {
            "a": [0.1, 0.2, 0.15, 0.25, 0.2, 0.3, 0.22, 0.28, 0.24, 0.26],
            "b": [0.12, 0.18, 0.16, 0.22, 0.21, 0.27, 0.23, 0.25, 0.22, 0.24],
            "c": [0.9, 0.1, 0.85, 0.15, 0.8, 0.2, 0.75, 0.25, 0.7, 0.3],
        }
        names = {"a": "芯片概念", "b": "存储芯片", "c": "白酒"}
        constituents = {
            "a": {"s1", "s2", "s3"},
            "b": {"s1", "s2", "s4"},
            "c": {"t1", "t2"},
        }
        ordered = order_by_fused_seriation(
            ["a", "b", "c"],
            series,
            names=names,
            constituents=constituents,
            theme_ids_by_code={"a": {"semiconductor"}, "b": {"semiconductor"}},
            traj_weight=0.5,
        )
        self.assertEqual(set(ordered), {"a", "b", "c"})
        # a and b should be neighbors after fusion.
        pos = {code: i for i, code in enumerate(ordered)}
        self.assertEqual(abs(pos["a"] - pos["b"]), 1)


if __name__ == "__main__":
    unittest.main()
