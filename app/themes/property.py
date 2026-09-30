"""Pilot: property & infrastructure concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

PROPERTY_THEME = ThemeConfig(
    theme_id="property",
    title="地产基建主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("305794", "装配式建筑"),
        ThemeBoard("300261", "建筑节能"),
    ),
    group_b=(
        ThemeBoard("301365", "一带一路"),
        ThemeBoard("301518", "高铁"),
    ),
    satellites=(
        ThemeBoard("308717", "物业管理"),
        ThemeBoard("307826", "水泥概念"),
    ),
    group_a_label="群A · 建筑链",
    group_b_label="群B · 基建",
    satellite_label="卫星",
    group_a_reason=(
        "装配式建筑与建筑节能成分重叠最高，是建筑链主核。"
        "用来观察建筑侧内部热度是否抱团。"
    ),
    group_b_reason=(
        "一带一路与高铁偏交运/对外基建对照；彼此重叠偏弱。"
        "用来对照建筑↔基建是共振还是分叉；不要强写群B同热。"
    ),
    satellite_reason=(
        "物业管理偏地产运营；水泥概念偏建材脉冲，与主核几乎不交；"
        "爆发时对照群A是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "库中无独立「房地产」概念，本页用建筑链+基建概念代理政策周期。"
        "不是全周期资源杂烩；钢铁等另属其他页。"
        "群B内部重叠弱于群A，对照叙事优先于同热结论。"
    ),
    interpret_template="property-theme-reading",
)
