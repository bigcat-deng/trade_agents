"""Joint industry reading: rim regime as axis + four layer compact evidence."""

from __future__ import annotations

from datetime import date

from jinja2 import StrictUndefined, Template

from app.db import (
    fetch_board_amount_named_window,
    fetch_board_bar_dates_ending,
    fetch_board_daily_bars_many,
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
    fetch_trading_dates_ending,
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
from app.themes.fund_wave import (
    FUND_ANOMALY_LOOKBACK,
    _history_dates_for_window,
    build_industry_fund_plane,
)
from app.themes.heat_rim_regime import (
    REGIME_DISPLAY_DAYS,
    REGIME_PLANE_WINDOW,
    REGIME_WARMUP_DAYS,
    build_regime_panel_payload,
)
from app.themes.heat_seriation import as_float
from app.themes.industry_wave import (
    RETURN_VOL_LOOKBACK,
    build_industry_board_heat_payload,
)

TEMPLATE_NAME = "industry-rim-joint-reading"
DEFAULT_WINDOW_DAYS = 40


def build_industry_rim_joint_reading_prompt(
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
        raise RuntimeError("no industry heat tip for rim-joint reading")
    tip = tip_days[-1]
    window_dates = fetch_heat_dates_ending("industry", tip, window)
    if len(window_dates) < 5:
        raise RuntimeError("no industry heat window for rim-joint reading")

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
        raise RuntimeError("no industry heat leaf order for rim-joint reading")
    name_map = {
        code: (heat_names[i] if i < len(heat_names) else code)
        for i, code in enumerate(heat_codes)
    }

    # Fund plane (heat-aligned).
    hist = _history_dates_for_window("industry", window_dates)
    amount_rows = fetch_board_amount_named_window("industry", hist[0], tip)
    fund = build_industry_fund_plane(
        window_dates=window_dates,
        amount_rows=amount_rows,
        history_dates=hist,
        ordered_codes=heat_codes,
        densify=1,
    )

    # Smooth level + return (shared bars history).
    need = len(window_dates) + SMOOTH_RANGE_NORM_DAYS + 20
    smooth_hist = fetch_heat_dates_ending("industry", tip, need)
    if len(smooth_hist) < SMOOTH_RANGE_MIN_PERIODS + 5:
        smooth_hist = fetch_board_bar_dates_ending("industry", tip, need)
    if not smooth_hist:
        smooth_hist = list(window_dates)
    smooth_hist = sorted(set(smooth_hist) | set(window_dates))
    bars = fetch_board_daily_bars_many(
        "industry", heat_codes, smooth_hist[0], tip
    )
    level = build_industry_smooth_range_plane(
        window_dates=window_dates,
        history_dates=smooth_hist,
        ordered_codes=heat_codes,
        names=name_map,
        bars_by_code=bars,
        metric="level",
        densify=1,
    )
    ret = build_industry_smooth_range_plane(
        window_dates=window_dates,
        history_dates=smooth_hist,
        ordered_codes=heat_codes,
        names=name_map,
        bars_by_code=bars,
        metric="return",
        densify=1,
    )

    rim = _build_rim_panel(tip=tip)
    rim_display = int(rim.get("display_days") or REGIME_DISPLAY_DAYS)

    data_block = _joint_data_block(
        window_dates=window_dates,
        heat=heat,
        fund=fund if not fund.get("empty_message") else None,
        level=level if not level.get("empty_message") else None,
        ret=ret if not ret.get("empty_message") else None,
        rim=rim,
    )
    body = Template(template.body, undefined=StrictUndefined).render(
        window_trading_days=len(window_dates),
        rim_display_days=rim_display,
        norm_days=SMOOTH_RANGE_NORM_DAYS,
        data_block=data_block,
    )
    return template, body, tip


def _build_rim_panel(*, tip: date) -> dict:
    regime_need = REGIME_DISPLAY_DAYS + REGIME_WARMUP_DAYS + REGIME_PLANE_WINDOW
    regime_calendar = fetch_trading_dates_ending("industry", tip, regime_need)
    if not regime_calendar:
        return {
            "rows": [],
            "note": "近端没有可标的主线政权。",
            "as_of": tip.isoformat(),
            "display_days": REGIME_DISPLAY_DAYS,
        }
    regime_rows = fetch_industry_heat_window(regime_calendar[0], tip)
    regime_heat: dict[date, dict[str, float]] = {}
    regime_names: dict[str, str] = {}
    for trade_date, board_code, board_name, heat_short, _long in regime_rows:
        code = str(board_code)
        if board_name:
            regime_names[code] = str(board_name)
        val = as_float(heat_short)
        if val is None:
            continue
        regime_heat.setdefault(trade_date, {})[code] = val
    bar_cal = fetch_trading_dates_ending(
        "industry", tip, regime_need + RETURN_VOL_LOOKBACK + 5
    )
    regime_bars = (
        fetch_board_daily_bars_many(
            "industry",
            list(regime_names.keys()),
            bar_cal[0],
            tip,
        )
        if bar_cal and regime_names
        else {}
    )
    return build_regime_panel_payload(
        as_of=tip,
        calendar=regime_calendar,
        heat_by_day=regime_heat,
        names=regime_names,
        bars_by_code=regime_bars,
        vol_calendar=bar_cal or regime_calendar,
    )


def _compact_layer(
    *,
    title: str,
    plane: dict | None,
    score_name: str,
    heat: dict | None = None,
    extra_lines: list[str] | None = None,
) -> list[str]:
    lines = ["", f"## {title}"]
    if plane is None:
        lines.append("（本层不可用）")
        return lines
    z = plane.get("z_boards") or plane.get("z_short") or []
    names = list(plane.get("board_names") or [])
    if not z or not names:
        lines.append("（本层无网格）")
        return lines
    end_i = len(z) - 1
    mid_i = end_i // 2 if end_i >= 0 else 0
    end_v = _row_hotness(z, end_i)
    mid_v = _row_hotness(z, mid_i)
    hot = _named_levels(names, end_v, hottest_first=True, limit=8)
    cold = _named_levels(names, end_v, hottest_first=False, limit=6)
    warming: list[tuple[str, float, float, float]] = []
    for name, e, m in zip(names, end_v, mid_v):
        if e is None or m is None:
            continue
        warming.append((name, float(e) - float(m), float(m), float(e)))
    warming.sort(key=lambda item: item[1], reverse=True)
    shapes = _industry_shape_stats(names, z)

    tip_red = list((plane.get("tip_labels") or {}).get("text") or [])
    tip_blue = list((plane.get("tip_cold_labels") or {}).get("text") or [])

    lines.append(f"行业数：{len(names)}；图注：{plane.get('axis_note') or ''}")
    lines.append(f"截止最高（{score_name}）：")
    lines += [f"  {name}\t{_fmt(v)}" for name, v in hot]
    if tip_red:
        lines.append("红字Top5：" + "、".join(tip_red))
    lines.append(f"截止最低（{score_name}）：")
    lines += [f"  {name}\t{_fmt(v)}" for name, v in cold]
    if tip_blue:
        lines.append("蓝字Bottom5：" + "、".join(tip_blue))
    lines.append("中间→截止抬升最多：")
    lines += [
        f"  {name}\tΔ={_fmt(d)}\t截={_fmt(e)}"
        for name, d, _m, e in warming[:8]
    ]
    lines.append("中间→截止回落最多：")
    lines += [
        f"  {name}\tΔ={_fmt(d)}\t截={_fmt(e)}"
        for name, d, _m, e in list(reversed(warming[-8:]))
    ]
    lines.append("长红/持续高位：")
    for name, hot_days, mean_hot, e in shapes["persistence"][:6]:
        lines.append(f"  {name}\t天={hot_days}\t均={_fmt(mean_hot)}\t截={_fmt(e)}")
    lines.append("中段收缩后再抬：")
    for name, early_m, mid_m, late_m, e in shapes["rewarm"][:5]:
        lines.append(
            f"  {name}\t前={_fmt(early_m)}\t中={_fmt(mid_m)}\t近={_fmt(late_m)}\t截={_fmt(e)}"
        )
    lines.append("近端候补：")
    for name, e, lift, rank in shapes["challengers"][:5]:
        lines.append(f"  {name}\t截={_fmt(e)}\t升={_fmt(lift)}\t名次={int(rank)}")

    if heat is not None:
        hz = heat.get("z_boards") or heat.get("z_short") or []
        heat_end = _row_hotness(hz, len(hz) - 1) if hz else []
        pairs: list[tuple[str, float, float]] = []
        for i, name in enumerate(names):
            hv = heat_end[i] if i < len(heat_end) else None
            av = end_v[i] if i < len(end_v) else None
            if hv is None or av is None:
                continue
            pairs.append((name, float(hv), float(av)))
        hi_lo = sorted(pairs, key=lambda x: x[1] - x[2], reverse=True)[:5]
        lo_hi = sorted(pairs, key=lambda x: x[2] - x[1], reverse=True)[:5]
        lines.append("对照短热：热高本层低：")
        lines += [
            f"  {name}\thot={_fmt(h)}\tscore={_fmt(a)}" for name, h, a in hi_lo
        ]
        lines.append("对照短热：本层高热低：")
        lines += [
            f"  {name}\thot={_fmt(h)}\tscore={_fmt(a)}" for name, h, a in lo_hi
        ]

    if extra_lines:
        lines.extend(extra_lines)
    return lines


def _heat_extra(heat: dict) -> list[str]:
    lines: list[str] = []
    rex = heat.get("return_exceedance") or {}
    pos = list(rex.get("last_pos_text") or [])
    neg = list(rex.get("last_neg_text") or [])
    lines.append("截止日±2σ正超：" + ("、".join(pos) if pos else "无"))
    lines.append("截止日±2σ负超：" + ("、".join(neg) if neg else "无"))
    return lines


def _joint_data_block(
    *,
    window_dates: list[date],
    heat: dict,
    fund: dict | None,
    level: dict | None,
    ret: dict | None,
    rim: dict,
) -> str:
    tip = window_dates[-1]
    rows = list(rim.get("rows") or [])
    lines = [
        f"截止日：{tip.isoformat()}",
        (
            f"四层展示窗：{window_dates[0].isoformat()} → {tip.isoformat()}"
            f"（{len(window_dates)} 个交易日）"
        ),
        f"主线政权图注：{rim.get('note') or ''}",
        "",
        f"## 主线政权近{len(rows) or REGIME_DISPLAY_DAYS}日",
        "日期\t政权\t主线成员\t许可\t候选\t关系",
    ]
    if not rows:
        lines.append("（近端没有可标的主线政权）")
    else:
        for row in rows:
            lines.append(
                f"{row.get('signal_date')}\t{row.get('regime')}\t"
                f"{row.get('members')}\t{row.get('cand_license')}\t"
                f"{row.get('cand_members')}\t{row.get('cand_relation')}"
            )

    lines += _compact_layer(
        title="行业短热（佐证）",
        plane=heat,
        score_name="hotness",
        extra_lines=_heat_extra(heat),
    )
    lines += _compact_layer(
        title=f"资金水面 · 成交额自身异常（回看{FUND_ANOMALY_LOOKBACK}日）",
        plane=fund,
        score_name="异常分",
        heat=heat,
    )
    lines += _compact_layer(
        title=f"平滑价位（区间{SMOOTH_RANGE_NORM_DAYS}日）",
        plane=level,
        score_name="价位区间",
        heat=heat,
    )
    lines += _compact_layer(
        title=f"平滑收益（区间{SMOOTH_RANGE_NORM_DAYS}日）",
        plane=ret,
        score_name="收益区间",
        heat=heat,
    )
    return "\n".join(lines)
