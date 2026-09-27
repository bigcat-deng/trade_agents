"""Pilot: semiconductor & chip concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

SEMICONDUCTOR_THEME = ThemeConfig(
    theme_id="semiconductor",
    title="半导体&芯片主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("301085", "芯片概念"),
        ThemeBoard("307940", "存储芯片"),
        ThemeBoard("309004", "先进封装"),
    ),
    group_b=(
        ThemeBoard("308725", "汽车芯片"),
        ThemeBoard("308300", "MCU芯片"),
    ),
    satellites=(
        ThemeBoard("308700", "第三代半导体"),
        ThemeBoard("309085", "光刻机"),
        ThemeBoard("308582", "光刻胶"),
        ThemeBoard("309049", "共封装光学(CPO)"),
    ),
    group_a_label="群A · 通用芯片核",
    group_b_label="群B · 汽车/MCU",
    satellite_label="卫星",
    group_a_reason=(
        "芯片、存储与先进封装成分重叠较高，是通用芯片核。"
        "用来观察主线内部热度是否抱团。"
    ),
    group_b_reason=(
        "汽车芯片与 MCU 彼此重叠较高，是应用支线。"
        "用来对照是否与通用核同向，或走出独立景气。"
    ),
    satellite_reason=(
        "功率（第三代）、设备材料（光刻机/光刻胶）与光互联（CPO）"
        "不并入群内；爆发时对照群A是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "通用核看抱团；再看与汽车/MCU 是否一起动；设备与功率只作卫星脉冲。"
        "光刻机与光刻胶彼此重叠很低，不捆成一群。"
        "「华为昇腾」「海思」「消费电子」等大伞不进群。"
        "与人工智能主题域共用芯片/存储/封装三只概念，但问题不同："
        "AI 看算力↔芯片传导，本页看芯片域内部结构。"
    ),
    interpret_template="semiconductor-theme-reading",
)
