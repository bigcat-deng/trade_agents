"""Build industry short-heat wave reading prompt for the theme-wave page."""

from __future__ import annotations

from datetime import date

from jinja2 import StrictUndefined, Template

from app.db import fetch_heat_dates_ending, fetch_industry_heat_window
from app.interpret.theme_wave import (
    _fmt,
    _industry_shape_stats,
    _named_levels,
    _row_hotness,
)
from app.prompts.template import PromptTemplate, load_prompt
from app.themes.industry_wave import build_industry_board_heat_payload

TEMPLATE_NAME = "industry-short-heat-reading"
DEFAULT_WINDOW_DAYS = 40


def build_industry_short_heat_reading_prompt(
    as_of: date | None = None,
    *,
    window_trading_days: int | None = None,
) -> tuple[PromptTemplate, str, date]:
    template = load_prompt(TEMPLATE_NAME)
    window = int(
        window_trading_days
        if window_trading_days is not None
        else (template.config.get("window_trading_days") or DEFAULT_WINDOW_DAYS)
    )
    window = max(20, min(180, window))

    target = as_of or date.today()
    tip_days = fetch_heat_dates_ending("industry", target, 1)
    if not tip_days:
        raise RuntimeError("no industry heat rows to interpret")
    selected = tip_days[-1]
    window_dates = fetch_heat_dates_ending("industry", selected, window)
    if not window_dates:
        raise RuntimeError("no industry heat window to interpret")

    # Skip CSI overlay fetch (baostock); marks still come from board bars.
    industry = build_industry_board_heat_payload(
        window_dates=window_dates,
        heat_rows=fetch_industry_heat_window(window_dates[0], window_dates[-1]),
        csi500_closes={},
        csi500_volumes={},
    )
    if industry.get("empty_message"):
        raise RuntimeError(str(industry["empty_message"]))

    data_block = _industry_data_block(window_dates=window_dates, industry=industry)
    body = Template(template.body, undefined=StrictUndefined).render(
        window_trading_days=len(window_dates),
        data_block=data_block,
    )
    return template, body, window_dates[-1]


def _industry_data_block(*, window_dates: list[date], industry: dict) -> str:
    z = industry.get("z_boards") or industry.get("z_short") or []
    names = list(industry.get("board_names") or [])
    dates = list(industry.get("dates") or [d.isoformat() for d in window_dates])
    n = len(names)
    end_i = len(z) - 1
    mid_i = end_i // 2 if end_i >= 0 else 0
    ind_end = _row_hotness(z, end_i) if z else []
    ind_mid = _row_hotness(z, mid_i) if z else []
    hot = _named_levels(names, ind_end, hottest_first=True, limit=12)
    cold = _named_levels(names, ind_end, hottest_first=False, limit=8)
    warming: list[tuple[str, float, float, float]] = []
    for name, end_v, mid_v in zip(names, ind_end, ind_mid):
        if end_v is None or mid_v is None:
            continue
        warming.append((name, float(end_v) - float(mid_v), float(mid_v), float(end_v)))
    warming.sort(key=lambda item: item[1], reverse=True)
    shapes = _industry_shape_stats(names, z)

    rex = industry.get("return_exceedance") or {}
    pos_tip = list(zip(rex.get("last_pos_text") or [], rex.get("last_pos_x") or []))
    neg_tip = list(zip(rex.get("last_neg_text") or [], rex.get("last_neg_x") or []))

    cross = industry.get("cross_marks") or {}
    fract = industry.get("fractal_marks") or {}
    y_cut = max(0, end_i - 4)

    def collect_near(marks: dict, xkey: str, ykey: str, tkey: str, label: str):
        rows = []
        for x, y, text in zip(
            marks.get(xkey) or [],
            marks.get(ykey) or [],
            marks.get(tkey) or [],
        ):
            try:
                if float(y) >= y_cut - 0.1:
                    rows.append((str(text), label, float(x), float(y)))
            except (TypeError, ValueError):
                continue
        return rows

    near_events = []
    near_events += collect_near(cross, "up_x", "up_y", "up_text", "MACD上穿")
    near_events += collect_near(cross, "down_x", "down_y", "down_text", "MACD下穿")
    near_events += collect_near(fract, "top_x", "top_y", "top_text", "顶分型")
    near_events += collect_near(fract, "bottom_x", "bottom_y", "bottom_text", "底分型")

    def name_at(x: float) -> str:
        index = int(round(float(x)))
        if 0 <= index < len(names):
            return names[index]
        return f"x={x}"

    near_by_name: dict[str, list[str]] = {}
    for _text, label, x, y in near_events:
        name = name_at(x)
        day_i = int(round(y))
        day = dates[day_i] if 0 <= day_i < len(dates) else y
        near_by_name.setdefault(name, []).append(f"{label}@{day}")

    tip = window_dates[-1]
    lines = [
        f"截止日：{tip.isoformat()}",
        (
            f"窗口：{window_dates[0].isoformat()} → {tip.isoformat()}"
            f"（{len(window_dates)} 个交易日）"
        ),
        f"行业数：{n}",
        f"图注：{industry.get('axis_note') or ''}",
        "",
        "## 叶序表（下标从左到右；截止 hotness；中间→截止 Δ）",
        "下标\t行业\t截止热度\t中间热度\tΔ",
    ]
    for i, name in enumerate(names):
        end_v = ind_end[i] if i < len(ind_end) else None
        mid_v = ind_mid[i] if i < len(ind_mid) else None
        delta = None if end_v is None or mid_v is None else float(end_v) - float(mid_v)
        lines.append(
            f"{i}\t{name}\t{_fmt(end_v)}\t{_fmt(mid_v)}\t{_fmt(delta)}"
        )

    lines += ["", "## 截止日最热"]
    lines += [f"  {name}\t{_fmt(value)}" for name, value in hot]
    lines += ["", "## 截止日最冷"]
    lines += [f"  {name}\t{_fmt(value)}" for name, value in cold]
    lines += ["", "## 中间→截止升温最多"]
    lines += [
        f"  {name}\tΔ={_fmt(delta)}\t中={_fmt(mid_v)}\t截={_fmt(end_v)}"
        for name, delta, mid_v, end_v in warming[:10]
    ]
    lines += ["", "## 中间→截止降温最多"]
    lines += [
        f"  {name}\tΔ={_fmt(delta)}\t中={_fmt(mid_v)}\t截={_fmt(end_v)}"
        for name, delta, mid_v, end_v in list(reversed(warming[-10:]))
    ]

    lines += ["", "## 时间形态：长红柱", "行业\t高热天数\t窗内均值\t截止"]
    for name, hot_days, mean_hot, end_v in shapes["persistence"]:
        lines.append(f"  {name}\t{hot_days}\t{_fmt(mean_hot)}\t{_fmt(end_v)}")
    lines += ["", "## 时间形态：冷却后再抬", "行业\t前\t中\t近\t截止"]
    for name, early_m, mid_m, late_m, end_v in shapes["rewarm"]:
        lines.append(
            f"  {name}\t{_fmt(early_m)}\t{_fmt(mid_m)}\t{_fmt(late_m)}\t{_fmt(end_v)}"
        )
    lines += ["", "## 时间形态：候补龙头", "行业\t截止\t近段升幅\t名次"]
    for name, end_v, lift, rank in shapes["challengers"]:
        lines.append(f"  {name}\t{_fmt(end_v)}\t{_fmt(lift)}\t{int(rank)}")

    lines += ["", "## 截止日收益±2σ冲击（顶上红/绿字来源）"]
    lines.append("正超：" + ("、".join(text for text, _x in pos_tip) or "无"))
    lines.append("负超：" + ("、".join(text for text, _x in neg_tip) or "无"))

    lines += ["", "## 近5日结构事件（按行业汇总）"]
    if not near_by_name:
        lines.append("（近5日无 MACD/分型落点）")
    else:
        for name, events in sorted(
            near_by_name.items(), key=lambda item: (-len(item[1]), item[0])
        )[:25]:
            lines.append(f"  {name}\t" + "；".join(events[:6]))

    csi_r = industry.get("csi500_returns") or []
    csi_tip = next((v for v in reversed(csi_r) if v is not None), None)
    lines += [
        "",
        f"## 中证500截止日收益：{_fmt(csi_tip, 4) if csi_tip is not None else '—'}",
    ]
    return "\n".join(lines)
