"""Pilot: robotics / humanoid concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

ROBOTS_THEME = ThemeConfig(
    theme_id="robots",
    title="机器人主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("309119", "人形机器人"),
        ThemeBoard("300816", "机器人概念"),
    ),
    group_b=(
        ThemeBoard("309000", "减速器"),
        ThemeBoard("300941", "工业母机"),
    ),
    satellites=(
        ThemeBoard("301258", "机器视觉"),
        ThemeBoard("301121", "特斯拉概念"),
        ThemeBoard("301286", "无人驾驶"),
    ),
    group_a_label="群A · 机器人核",
    group_b_label="群B · 关键/母机",
    satellite_label="卫星",
    group_a_reason=(
        "人形机器人与机器人概念成分重叠最高，是机器人主核。"
        "用来观察主线内部热度是否抱团。"
    ),
    group_b_reason=(
        "减速器与工业母机偏零部件/机床对照；减速器与人形重叠较高，母机与主核偏弱。"
        "用来对照主核是共振、轮动还是分叉；不要强写群B同热。"
    ),
    satellite_reason=(
        "机器视觉偏感知脉冲；特斯拉概念、无人驾驶偏汽车叙事，不并入群内；"
        "爆发时对照群A是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "本页看机器人/具身结构，不是算力AI，也不是军工航天。"
        "无人驾驶只作汽车智能化卫星，不把智能驾驶写成机器人主线。"
        "群B内部重叠弱于群A，对照叙事优先于同热结论。"
    ),
    interpret_template="robots-theme-reading",
)
