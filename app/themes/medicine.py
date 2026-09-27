"""Pilot: medicine concept theme domain."""

from __future__ import annotations

from app.themes.config import ThemeBoard, ThemeConfig

MEDICINE_THEME = ThemeConfig(
    theme_id="medicine",
    title="医药主题域",
    board_type="concept",
    group_a=(
        ThemeBoard("308014", "创新药"),
        ThemeBoard("308572", "仿制药一致性评价"),
        ThemeBoard("301565", "医药电商"),
    ),
    group_b=(
        ThemeBoard("308712", "医美概念"),
        ThemeBoard("301346", "民营医院"),
        ThemeBoard("301252", "眼科医疗"),
    ),
    satellites=(ThemeBoard("309081", "减肥药"),),
    group_a_label="群A · 制药主线",
    group_b_label="群B · 消费医疗",
    satellite_label="卫星",
    group_a_reason=(
        "成分股中等重叠：药企研发与仿制链条，加上医药渠道。"
        "用来观察制药主线内部热度是否一致。"
    ),
    group_b_reason=(
        "可选/消费型医疗相关概念，彼此有一定重叠但不与群A捆成同一篮子。"
        "用来对照消费医疗是否与制药主线一起动。"
    ),
    satellite_reason=(
        "与群A成分重叠偏低，不并入群内；只在突然变热时提示是否独立脉冲。"
    ),
    grouping_note=(
        "分群依据成分股重叠，不用热度或名称相似建群。"
        "重叠过高视为近重复只留代表；过低不连边。"
        "医药是主题域，先拆成稍松的群，再看热度与价格是否同向。"
    ),
)
