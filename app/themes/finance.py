"""Pilot: banks vs brokers (narrow finance) concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

FINANCE_THEME = ThemeConfig(
    theme_id="finance",
    title="银行券商主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("301270", "参股银行"),
        ThemeBoard("301209", "互联网金融"),
    ),
    group_b=(
        ThemeBoard("300100", "参股券商"),
        ThemeBoard("301377", "信托概念"),
    ),
    satellites=(
        ThemeBoard("300018", "参股保险"),
        ThemeBoard("301628", "互联网保险"),
    ),
    group_a_label="群A · 银行侧",
    group_b_label="群B · 券商侧",
    satellite_label="卫星",
    group_a_reason=(
        "参股银行作银行贝塔代理；互联网金融有沾边、不是纯银行。"
        "用来观察银行侧内部热度是否抱团；成分重叠偏弱。"
    ),
    group_b_reason=(
        "参股券商与信托偏资本市场/非银对照；与银行侧重叠弱。"
        "用来对照银↔券是共振还是分叉；不要强写群B同热。"
    ),
    satellite_reason=(
        "参股保险、互联网保险是保险第三条腿，不并入群内；"
        "爆发时对照群A是否同热。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "本页用参股/互金等概念代理，不是行业「银行」「证券」本身。"
        "只做银行↔券商对照，不是大金融；多元金融大伞不进。"
        "本域重叠整体偏弱，对照叙事优先于同热结论。"
    ),
    interpret_template="finance-theme-reading",
)
