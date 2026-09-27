"""Pilot: non-ferrous metals concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

METALS_THEME = ThemeConfig(
    theme_id="metals",
    title="有色金属主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("301577", "金属铜"),
        ThemeBoard("301582", "金属锌"),
        ThemeBoard("308864", "金属铅"),
    ),
    group_b=(
        ThemeBoard("301511", "金属镍"),
        ThemeBoard("300809", "小金属概念"),
    ),
    satellites=(
        ThemeBoard("300248", "黄金概念"),
        ThemeBoard("300382", "稀土永磁"),
        ThemeBoard("302174", "金属钴"),
    ),
    group_a_label="群A · 工业有色",
    group_b_label="群B · 镍/小金属",
    satellite_label="卫星",
    group_a_reason=(
        "铜、锌、铅成分重叠高，是工业有色核。"
        "用来观察主线内部热度是否抱团。"
    ),
    group_b_reason=(
        "镍与小金属与工业有色有中等重叠，偏弹性/小品种。"
        "用来对照是扩散到支线，还是主线独自动。"
    ),
    satellite_reason=(
        "黄金偏避险脉冲；稀土、钴篮子更窄，不并入群内；"
        "爆发时对照群A是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "第一页只做有色金属：先看工业有色抱团，再看与镍/小金属是否一起动。"
        "煤炭、油气、航运、锂电等另属周期资源族的其他页，不进本域。"
        "「资源」「周期」等伞标签不进群。"
    ),
    interpret_template="metals-theme-reading",
)
