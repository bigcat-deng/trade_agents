"""Build industry smooth-range / smooth-return reading prompts."""

from __future__ import annotations

from datetime import date

from jinja2 import StrictUndefined, Template

from app.db import (
    fetch_board_bar_dates_ending,
    fetch_board_daily_bars_many,
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
)
from app.interpret.theme_wave import (
    _fmt,
    _industry_shape_stats,
    _named_levels,
    _row_hotness,
)
from app.prompts.template import PromptTemplate, load_prompt
from app.themes.board_smooth_range import (
    SMOOTH_RANGE_MIN_PERIODS,
    SMOOTH_RANGE_NORM_DAYS,
    build_industry_smooth_range_plane,
)
from app.themes.industry_wave import build_industry_board_heat_payload

RANGE_TEMPLATE = "industry-smooth-range-reading"
RETURN_TEMPLATE = "industry-smooth-return-reading"
DEFAULT_WINDOW_DAYS = 40


def build_industry_smooth_range_reading_prompt(
    as_of: date | None = None,
    *,
    window_trading_days: int | None = None,
) -> tuple[PromptTemplate, str, date]:
    return _build_smooth_reading_prompt(
        RANGE_TEMPLATE,
        as_of,
        window_trading_days=window_trading_days,
        metric="level",
    )


def build_industry_smooth_return_reading_prompt(
    as_of: date | None = None,
    *,
    window_trading_days: int | None = None,
) -> tuple[PromptTemplate, str, date]:
    return _build_smooth_reading_prompt(
        RETURN_TEMPLATE,
        as_of,
        window_trading_days=window_trading_days,
        metric="return",
    )


def _build_smooth_reading_prompt(
    template_name: str,
    as_of: date | None,
    *,
    window_trading_days: int | None,
    metric: str,
) -> tuple[PromptTemplate, str, date]:
    template = load_prompt(template_name)
    window = int(
        window_trading_days
        if window_trading_days is not None
        else (template.config.get("window_trading_days") or DEFAULT_WINDOW_DAYS)
    )
    window = max(20, min(180, window))
    metric_key = "return" if metric == "return" else "level"

    target = as_of or date.today()
    tip_days = fetch_heat_dates_ending("industry", target, 1)
    if not tip_days:
        tip_days = fetch_board_bar_dates_ending("industry", target, 1)
    if not tip_days:
        raise RuntimeError("no industry tip date for smooth-range reading")
    selected = tip_days[-1]
    window_dates = fetch_heat_dates_ending("industry", selected, window)
    if len(window_dates) < 5:
        window_dates = fetch_board_bar_dates_ending("industry", selected, window)
    if len(window_dates) < 5:
        raise RuntimeError("no industry window for smooth-range reading")

    heat = build_industry_board_heat_payload(
        window_dates=window_dates,
        heat_rows=fetch_industry_heat_window(window_dates[0], window_dates[-1]),
        csi500_closes={},
        csi500_volumes={},
    )
    if heat.get("empty_message"):
        raise RuntimeError(str(heat["empty_message"]))
    heat_codes = list(heat.get("board_codes") or [])
    heat_names = list(heat.get("board_names") or [])
    if not heat_codes:
        raise RuntimeError("no industry heat leaf order for smooth-range reading")
    name_map = {
        code: (heat_names[i] if i < len(heat_names) else code)
        for i, code in enumerate(heat_codes)
    }

    need = len(window_dates) + SMOOTH_RANGE_NORM_DAYS + 20
    history = fetch_heat_dates_ending("industry", selected, need)
    if len(history) < SMOOTH_RANGE_MIN_PERIODS + 5:
        history = fetch_board_bar_dates_ending("industry", selected, need)
    if not history:
        history = list(window_dates)
    history = sorted(set(history) | set(window_dates))

    bars = fetch_board_daily_bars_many(
        "industry", heat_codes, history[0], selected
    )
    plane = build_industry_smooth_range_plane(
        window_dates=window_dates,
        history_dates=history,
        ordered_codes=heat_codes,
        names=name_map,
        bars_by_code=bars,
        metric=metric_key,
        densify=1,
    )
    if plane.get("empty_message"):
        raise RuntimeError(str(plane["empty_message"]))

    norm_days = int(plane.get("norm_days") or SMOOTH_RANGE_NORM_DAYS)
    data_block = _smooth_data_block(
        window_dates=window_dates,
        plane=plane,
        heat=heat,
        metric=metric_key,
        norm_days=norm_days,
    )
    body = Template(template.body, undefined=StrictUndefined).render(
        window_trading_days=len(window_dates),
        norm_days=norm_days,
        data_block=data_block,
    )
    return template, body, window_dates[-1]


def _smooth_data_block(
    *,
    window_dates: list[date],
    plane: dict,
    heat: dict,
    metric: str,
    norm_days: int,
) -> str:
    z = plane.get("z_boards") or plane.get("z_short") or []
    names = list(plane.get("board_names") or [])
    n = len(names)
    end_i = len(z) - 1
    mid_i = end_i // 2 if end_i >= 0 else 0
    end_v = _row_hotness(z, end_i) if z else []
    mid_v = _row_hotness(z, mid_i) if z else []
    hot = _named_levels(names, end_v, hottest_first=True, limit=12)
    cold = _named_levels(names, end_v, hottest_first=False, limit=8)
    warming: list[tuple[str, float, float, float]] = []
    for name, e, m in zip(names, end_v, mid_v):
        if e is None or m is None:
            continue
        warming.append((name, float(e) - float(m), float(m), float(e)))
    warming.sort(key=lambda item: item[1], reverse=True)
    shapes = _industry_shape_stats(names, z)

    tip_red = list((plane.get("tip_labels") or {}).get("text") or [])
    tip_blue = list((plane.get("tip_cold_labels") or {}).get("text") or [])

    hz = heat.get("z_boards") or heat.get("z_short") or []
    heat_end = _row_hotness(hz, len(hz) - 1) if hz else []
    heat_pairs: list[tuple[str, float, float]] = []
    for i, name in enumerate(names):
        hv = heat_end[i] if i < len(heat_end) else None
        av = end_v[i] if i < len(end_v) else None
        if hv is None or av is None:
            continue
        heat_pairs.append((name, float(hv), float(av)))
    heat_hi_score_lo = sorted(
        heat_pairs, key=lambda item: item[1] - item[2], reverse=True
    )[:8]
    score_hi_heat_lo = sorted(
        heat_pairs, key=lambda item: item[2] - item[1], reverse=True
    )[:8]

    if metric == "return":
        score_label = "收益区间位置"
        contrast_hi = "对照短热：热度高但收益区间偏弱"
        contrast_lo = "对照短热：收益区间高但短热偏弱"
        score_col = "截止收益位"
        mid_col = "中间收益位"
    else:
        score_label = "价位区间位置"
        contrast_hi = "对照短热：热度高但价位区间偏低"
        contrast_lo = "对照短热：价位区间高但短热偏弱"
        score_col = "截止价位"
        mid_col = "中间价位"

    tip = window_dates[-1]
    lines = [
        f"截止日：{tip.isoformat()}",
        (
            f"窗口：{window_dates[0].isoformat()} → {tip.isoformat()}"
            f"（{len(window_dates)} 个交易日）"
        ),
        f"行业数：{n}",
        f"指标：{'平滑收益' if metric == 'return' else '平滑价位'}（{score_label}）",
        f"区间回看：{norm_days} 日；卡尔曼后自身 min-max；min_periods={SMOOTH_RANGE_MIN_PERIODS}",
        f"图注：{plane.get('axis_note') or ''}",
        "横轴说明：与主题热度水面页行业短热同一叶序冻结",
        "",
        f"## 叶序表（下标从左到右；{score_label}；中间→截止 Δ）",
        f"下标\t行业\t{score_col}\t{mid_col}\tΔ\t对照截止短热hotness",
    ]
    for i, name in enumerate(names):
        e = end_v[i] if i < len(end_v) else None
        m = mid_v[i] if i < len(mid_v) else None
        delta = None if e is None or m is None else float(e) - float(m)
        hv = heat_end[i] if i < len(heat_end) else None
        lines.append(
            f"{i}\t{name}\t{_fmt(e)}\t{_fmt(m)}\t{_fmt(delta)}\t{_fmt(hv)}"
        )

    lines += ["", f"## 截止日{score_label}最高（红字候选）"]
    lines += [f"  {name}\t{_fmt(value)}" for name, value in hot]
    lines += [
        "",
        f"## 图上截止日红字（Top5）：{'、'.join(tip_red) if tip_red else '无'}",
    ]
    lines += ["", f"## 截止日{score_label}最低（蓝字候选）"]
    lines += [f"  {name}\t{_fmt(value)}" for name, value in cold]
    lines += [
        "",
        f"## 图上截止日蓝字（Bottom5）：{'、'.join(tip_blue) if tip_blue else '无'}",
    ]
    lines += ["", "## 中间→截止抬升最多"]
    lines += [
        f"  {name}\tΔ={_fmt(delta)}\t中={_fmt(m)}\t截={_fmt(e)}"
        for name, delta, m, e in warming[:10]
    ]
    lines += ["", "## 中间→截止回落最多"]
    lines += [
        f"  {name}\tΔ={_fmt(delta)}\t中={_fmt(m)}\t截={_fmt(e)}"
        for name, delta, m, e in list(reversed(warming[-10:]))
    ]

    lines += ["", "## 时间形态：持续高位（长红）", "行业\t高位天数\t窗内均值\t截止"]
    for name, hot_days, mean_hot, e in shapes["persistence"]:
        lines.append(f"  {name}\t{hot_days}\t{_fmt(mean_hot)}\t{_fmt(e)}")
    lines += ["", "## 时间形态：中段收缩后再抬", "行业\t前\t中\t近\t截止"]
    for name, early_m, mid_m, late_m, e in shapes["rewarm"]:
        lines.append(
            f"  {name}\t{_fmt(early_m)}\t{_fmt(mid_m)}\t{_fmt(late_m)}\t{_fmt(e)}"
        )
    lines += ["", "## 时间形态：近端抬升候补", "行业\t截止\t近段升幅\t名次"]
    for name, e, lift, rank in shapes["challengers"]:
        lines.append(f"  {name}\t{_fmt(e)}\t{_fmt(lift)}\t{int(rank)}")

    lines += ["", f"## {contrast_hi}"]
    lines += [
        f"  {name}\thotness={_fmt(h)}\tscore={_fmt(a)}\t差={_fmt(h - a)}"
        for name, h, a in heat_hi_score_lo
    ]
    lines += ["", f"## {contrast_lo}"]
    lines += [
        f"  {name}\thotness={_fmt(h)}\tscore={_fmt(a)}\t差={_fmt(a - h)}"
        for name, h, a in score_hi_heat_lo
    ]
    return "\n".join(lines)
