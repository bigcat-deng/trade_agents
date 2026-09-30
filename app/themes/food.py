"""Pilot: liquor & food (narrow staples) concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

FOOD_THEME = ThemeConfig(
    theme_id="food",
    title="白酒食品主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("301496", "白酒概念"),
        ThemeBoard("301497", "啤酒概念"),
    ),
    group_b=(
        ThemeBoard("308814", "预制菜"),
        ThemeBoard("300023", "食品安全"),
    ),
    satellites=(
        ThemeBoard("300983", "乳业"),
        ThemeBoard("308657", "免税店"),
    ),
    group_a_label="群A · 酒类",
    group_b_label="群B · 食品",
    satellite_label="卫星",
    group_a_reason=(
        "白酒与啤酒是酒类概念中相对最近的一对，作酒类主核。"
        "用来观察酒侧内部热度是否抱团；整体成分重叠弱于科技主题。"
    ),
    group_b_reason=(
        "预制菜与食品安全偏食品加工/安全对照；彼此重叠偏弱。"
        "用来对照酒↔食是共振还是分叉；不要强写群B同热。"
    ),
    satellite_reason=(
        "乳业篮子很窄；免税店偏可选消费/出行，与酒食主核几乎不交；"
        "爆发时对照群A是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "本域概念间重叠整体偏弱，对照叙事优先于同热结论。"
        "只做白酒食品窄页，不是大消费；消费电子、无人零售不进。"
        "乳业、免税店只作卫星，不并入群内。"
    ),
    interpret_template="food-theme-reading",
)
