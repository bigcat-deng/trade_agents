"""Pilot: artificial-intelligence concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

AI_THEME = ThemeConfig(
    theme_id="ai",
    title="人工智能主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("308828", "东数西算(算力)"),
        ThemeBoard("308642", "数据中心(AIDC)"),
        ThemeBoard("309068", "算力租赁"),
    ),
    group_b=(
        ThemeBoard("301085", "芯片概念"),
        ThemeBoard("307940", "存储芯片"),
        ThemeBoard("309004", "先进封装"),
    ),
    satellites=(
        ThemeBoard("309104", "多模态AI"),
        ThemeBoard("309126", "AI语料"),
    ),
    group_a_label="层1 · 算力基建",
    group_b_label="层2 · 半导体",
    satellite_label="卫星",
    group_a_reason=(
        "算力与数据中心相关概念，成分中等重叠。"
        "用来观察基建层内部热度是否抱团。"
    ),
    group_b_reason=(
        "芯片与封装上游，与算力层相关但篮子不完全相同。"
        "用来对照半导体是否领先、落后或与基建同向。"
    ),
    satellite_reason=(
        "偏应用/内容脉冲，不并入层内；爆发时对照层1是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "人工智能是产业链长链：先看同层抱团，再看层1与层2是否传导。"
        "「人工智能」「华为概念」等大伞概念不进层，避免污染。"
        "机器人/具身另见机器人主题域，不进本页。"
    ),
    interpret_template="ai-theme-reading",
)
