"""Pilot: defense & aerospace concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

DEFENSE_THEME = ThemeConfig(
    theme_id="defense",
    title="军工航天主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("309130", "商业航天"),
        ThemeBoard("300722", "卫星导航"),
        ThemeBoard("300889", "无人机"),
    ),
    group_b=(
        ThemeBoard("309128", "军工信息化"),
        ThemeBoard("309051", "毫米波雷达"),
    ),
    satellites=(
        ThemeBoard("301470", "航空发动机"),
        ThemeBoard("300105", "海工装备"),
    ),
    group_a_label="群A · 航天无人",
    group_b_label="群B · 信息化/感知",
    satellite_label="卫星",
    group_a_reason=(
        "商业航天、卫星导航与无人机成分重叠较高，是航天无人核。"
        "用来观察主线内部热度是否抱团。"
    ),
    group_b_reason=(
        "军工信息化与毫米波雷达偏电子/感知对照；内部重叠中等偏弱。"
        "用来对照航天核与信息化叙事是共振还是分叉。"
    ),
    satellite_reason=(
        "航空发动机、海工装备与主核重叠偏低，不并入群内；"
        "爆发时对照群A是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "「军工」是大伞概念，不进群，避免污染。"
        "群B作对照叙事，内部同热预期弱于群A。"
        "不与机器人、智能驾驶混域；机器人另见机器人主题域。"
        "与芯片/人工智能略有沾边但问题不同。"
    ),
    interpret_template="defense-theme-reading",
)
