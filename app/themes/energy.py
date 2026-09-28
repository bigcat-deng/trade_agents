"""Pilot: coal & oil-gas (fossil energy) concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

ENERGY_THEME = ThemeConfig(
    theme_id="energy",
    title="煤炭&油气主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("308716", "煤炭概念"),
        ThemeBoard("300084", "煤化工概念"),
    ),
    group_b=(
        ThemeBoard("300358", "天然气"),
        ThemeBoard("300402", "页岩气"),
    ),
    satellites=(
        ThemeBoard("300973", "航运概念"),
    ),
    group_a_label="群A · 煤炭链",
    group_b_label="群B · 油气",
    satellite_label="卫星",
    group_a_reason=(
        "煤炭与煤化工成分重叠较高，是煤炭链。"
        "用来观察煤链内部热度是否抱团。"
    ),
    group_b_reason=(
        "天然气与页岩气彼此重叠较高；库中无独立原油概念，气侧作油气代表。"
        "用来对照煤↔气是共振还是轮动。"
    ),
    satellite_reason=(
        "航运与煤/气篮子几乎不交，只作运价/交运脉冲；爆发时对照煤气是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "本页是周期资源族的能源页：先看煤炭链抱团，再看与油气是否一起动。"
        "绿色电力、核电、氢能、锂电等不进本域。"
        "有色金属另页；跨商品全周期共振不在本页展开。"
    ),
    interpret_template="energy-theme-reading",
)
