"""Pilot: lithium / next-gen battery concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

BATTERY_THEME = ThemeConfig(
    theme_id="battery",
    title="电池主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("300733", "锂电池概念"),
        ThemeBoard("308294", "固态电池"),
    ),
    group_b=(
        ThemeBoard("307822", "动力电池回收"),
        ThemeBoard("301096", "钠离子电池"),
    ),
    satellites=(
        ThemeBoard("300316", "燃料电池"),
        ThemeBoard("301174", "钒电池"),
        ThemeBoard("307904", "盐湖提锂"),
    ),
    group_a_label="群A · 锂电核",
    group_b_label="群B · 补链/替代",
    satellite_label="卫星",
    group_a_reason=(
        "锂电池概念与固态电池成分重叠最高，是锂电主核。"
        "用来观察锂电链内部热度是否抱团。"
    ),
    group_b_reason=(
        "动力电池回收与钠离子电池偏补链/替代化学；群内重叠弱于群A。"
        "用来对照锂电核是共振、轮动还是分叉；不要强写群B同热。"
    ),
    satellite_reason=(
        "燃料电池、钒电池、盐湖提锂与主核重叠偏低，不并入群内；"
        "爆发时对照群A是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "本页看锂电主链结构，不是风光储、不是新能源车大伞。"
        "BC/TOPCON/钙钛矿电池属光伏技术，不进本域；储能在风光储页。"
        "金属钴/镍在有色页；盐湖提锂只作资源卫星。"
        "群B内部重叠弱于群A，对照叙事优先于同热结论。"
    ),
    interpret_template="battery-theme-reading",
)
