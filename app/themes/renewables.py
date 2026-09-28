"""Pilot: solar, wind, and storage (风光储) concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

RENEWABLES_THEME = ThemeConfig(
    theme_id="renewables",
    title="风光储主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("301079", "光伏概念"),
        ThemeBoard("306380", "储能"),
    ),
    group_b=(
        ThemeBoard("300200", "风电"),
        ThemeBoard("308760", "绿色电力"),
    ),
    satellites=(
        ThemeBoard("300238", "核电"),
        ThemeBoard("308491", "氢能源"),
        ThemeBoard("300353", "特高压"),
        ThemeBoard("308761", "虚拟电厂"),
    ),
    group_a_label="群A · 光伏储能",
    group_b_label="群B · 风电绿电",
    satellite_label="卫星",
    group_a_reason=(
        "光伏与储能成分重叠较高，是光储主线。"
        "用来观察装机/储能侧是否抱团。"
    ),
    group_b_reason=(
        "风电与绿色电力重叠较高，偏发电侧对照。"
        "用来看光储与风电绿电是共振还是轮动。"
    ),
    satellite_reason=(
        "核电、氢能、特高压、虚拟电厂不并入主群；"
        "爆发时对照光储/风电是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "本页是成长侧资本开支：光储 vs 风电绿电，不并锂电、新能源车。"
        "煤炭&油气另页；不要做成「大新能源」杂烩。"
    ),
    interpret_template="renewables-theme-reading",
)
