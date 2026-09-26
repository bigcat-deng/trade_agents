"""Pilot: medicine concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

MEDICINE_THEME = ThemeConfig(
    theme_id="medicine",
    title="医药主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("308014", "创新药"),
        ThemeBoard("308572", "仿制药一致性评价"),
        ThemeBoard("301565", "医药电商"),
    ),
    group_b=(
        ThemeBoard("308712", "医美概念"),
        ThemeBoard("301346", "民营医院"),
        ThemeBoard("301252", "眼科医疗"),
    ),
    satellites=(ThemeBoard("309081", "减肥药"),),
)
