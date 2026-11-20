"""Build industry fund-wave (amount self-anomaly) reading prompt."""

from __future__ import annotations

from datetime import date

from jinja2 import StrictUndefined, Template

from app.db import (
    fetch_board_amount_named_window,
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
from app.themes.fund_wave import (
    FUND_ANOMALY_LOOKBACK,
    _history_dates_for_window,
    build_industry_fund_plane,
)
from app.themes.industry_wave import build_industry_board_heat_payload

TEMPLATE_NAME = "industry-fund-wave-reading"
DEFAULT_WINDOW_DAYS = 40


def build_industry_fund_wave_reading_prompt(
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
        raise RuntimeError("no industry heat rows to interpret fund wave")
    selected = tip_days[-1]
    window_dates = fetch_heat_dates_ending("industry", selected, window)
    if not window_dates:
        raise RuntimeError("no industry heat window to interpret fund wave")

    # Freeze X to short-heat leaf order (same as theme-wave embed).
    heat = build_industry_board_heat_payload(
        window_dates=window_dates,
        heat_rows=fetch_industry_heat_window(window_dates[0], window_dates[-1]),
        csi500_closes={},
        csi500_volumes={},
    )
    if heat.get("empty_message"):
        raise RuntimeError(str(heat["empty_message"]))
    heat_codes = list(heat.get("board_codes") or [])
    if not heat_codes:
        raise RuntimeError("no industry heat leaf order for fund-wave reading")

    hist = _history_dates_for_window("industry", window_dates)
    amount_rows = fetch_board_amount_named_window(
        "industry", hist[0], window_dates[-1]
    )
    fund = build_industry_fund_plane(
        window_dates=window_dates,
        amount_rows=amount_rows,
        history_dates=hist,
        ordered_codes=heat_codes,
        densify=1,
    )
    if fund.get("empty_message"):
        raise RuntimeError(str(fund["empty_message"]))

    lookback = int(fund.get("lookback") or FUND_ANOMALY_LOOKBACK)
    data_block = _fund_data_block(
        window_dates=window_dates,
        fund=fund,
        heat=heat,
        lookback=lookback,
    )
    body = Template(template.body, undefined=StrictUndefined).render(
        window_trading_days=len(window_dates),
        lookback=lookback,
        data_block=data_block,
    )
    return template, body, window_dates[-1]


def _fund_data_block(
    *,
    window_dates: list[date],
    fund: dict,
    heat: dict,
    lookback: int,
) -> str:
    z = fund.get("z_boards") or fund.get("z_short") or []
    names = list(fund.get("board_names") or [])
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

    tip_red = list((fund.get("tip_labels") or {}).get("text") or [])
    tip_blue = list((fund.get("tip_cold_labels") or {}).get("text") or [])

    hz = heat.get("z_boards") or heat.get("z_short") or []
    heat_end = _row_hotness(hz, len(hz) - 1) if hz else []
    heat_pairs: list[tuple[str, float, float]] = []
    for i, name in enumerate(names):
        hv = heat_end[i] if i < len(heat_end) else None
        av = end_v[i] if i < len(end_v) else None
        if hv is None or av is None:
            continue
        heat_pairs.append((name, float(hv), float(av)))
    heat_hi_amt_lo = sorted(
        heat_pairs, key=lambda item: item[1] - item[2], reverse=True
    )[:8]
    amt_hi_heat_lo = sorted(
        heat_pairs, key=lambda item: item[2] - item[1], reverse=True
    )[:8]

    tip = window_dates[-1]
    lines = [
        f"截止日：{tip.isoformat()}",
        (
            f"窗口：{window_dates[0].isoformat()} → {tip.isoformat()}"
            f"（{len(window_dates)} 个交易日）"
        ),
        f"行业数：{n}",
        (
            f"自身异常回看：{lookback} 日（严格过去，不含当日）；"
            "min_periods=20；z_scale=1.5"
        ),
        f"图注：{fund.get('axis_note') or ''}",
        "横轴说明：与主题热度水面页行业短热同一叶序冻结"
        "（共动近=短热共动，不是成交额共动）",
        "",
        "## 叶序表（下标从左到右；截止自身异常分；中间→截止 Δ）",
        "下标\t行业\t截止异常分\t中间异常分\tΔ\t对照截止短热hotness",
    ]
    for i, name in enumerate(names):
        e = end_v[i] if i < len(end_v) else None
        m = mid_v[i] if i < len(mid_v) else None
        delta = None if e is None or m is None else float(e) - float(m)
        hv = heat_end[i] if i < len(heat_end) else None
        lines.append(
            f"{i}\t{name}\t{_fmt(e)}\t{_fmt(m)}\t{_fmt(delta)}\t{_fmt(hv)}"
        )

    lines += ["", "## 截止日自身异常最高（红字候选）"]
    lines += [f"  {name}\t{_fmt(value)}" for name, value in hot]
    lines += [
        "",
        f"## 图上截止日红字（Top5）：{'、'.join(tip_red) if tip_red else '无'}",
    ]
    lines += ["", "## 截止日自身异常最低（蓝字候选）"]
    lines += [f"  {name}\t{_fmt(value)}" for name, value in cold]
    lines += [
        "",
        f"## 图上截止日蓝字（Bottom5）：{'、'.join(tip_blue) if tip_blue else '无'}",
    ]
    lines += ["", "## 中间→截止异常分抬升最多"]
    lines += [
        f"  {name}\tΔ={_fmt(delta)}\t中={_fmt(m)}\t截={_fmt(e)}"
        for name, delta, m, e in warming[:10]
    ]
    lines += ["", "## 中间→截止异常分回落最多"]
    lines += [
        f"  {name}\tΔ={_fmt(delta)}\t中={_fmt(m)}\t截={_fmt(e)}"
        for name, delta, m, e in list(reversed(warming[-10:]))
    ]

    lines += ["", "## 时间形态：持续放量异常（长红）", "行业\t高异常天数\t窗内均值\t截止"]
    for name, hot_days, mean_hot, e in shapes["persistence"]:
        lines.append(f"  {name}\t{hot_days}\t{_fmt(mean_hot)}\t{_fmt(e)}")
    lines += ["", "## 时间形态：中段收缩后再抬", "行业\t前\t中\t近\t截止"]
    for name, early_m, mid_m, late_m, e in shapes["rewarm"]:
        lines.append(
            f"  {name}\t{_fmt(early_m)}\t{_fmt(mid_m)}\t{_fmt(late_m)}\t{_fmt(e)}"
        )
    lines += ["", "## 时间形态：近端抬升候补（非截止第1）", "行业\t截止\t近段升幅\t名次"]
    for name, e, lift, rank in shapes["challengers"]:
        lines.append(f"  {name}\t{_fmt(e)}\t{_fmt(lift)}\t{int(rank)}")

    lines += ["", "## 对照短热：热度高但自身异常偏弱（热高量弱）"]
    lines += [
        f"  {name}\thotness={_fmt(h)}\tanom={_fmt(a)}\t差={_fmt(h - a)}"
        for name, h, a in heat_hi_amt_lo
    ]
    lines += ["", "## 对照短热：自身异常高但短热偏弱（量高热弱）"]
    lines += [
        f"  {name}\thotness={_fmt(h)}\tanom={_fmt(a)}\t差={_fmt(a - h)}"
        for name, h, a in amt_hi_heat_lo
    ]
    return "\n".join(lines)
