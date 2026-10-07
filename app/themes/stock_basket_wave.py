"""Stock heat plane from a named industry/concept constituent union."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from typing import Protocol

from app.market_data.board_heat import BoardHeatRow, BoardReturn, compute_heat
from app.market_data.csi500 import csi500_maps_ending, csi500_overlay_series
from app.themes.board_cross_marks import (
    CROSS_HISTORY_DAYS,
    build_cross_mark_overlay,
    empty_cross_mark_overlay,
)
from app.themes.heat_rim_regime import (
    REGIME_DISPLAY_DAYS,
    REGIME_PLANE_WINDOW,
    REGIME_WARMUP_DAYS,
    build_regime_panel_payload,
)
from app.themes.heat_seriation import (
    DEFAULT_PLANE_DENSIFY,
    as_float,
    densify_hotness_plane,
    hotness_grid,
    hotness_series_by_code,
    order_by_trajectory_seriation,
)
from app.themes.heat_surface_flags import attach_surface_flags
from app.themes.industry_return_flags import (
    RETURN_VOL_LOOKBACK,
    RETURN_VOL_MULT,
    build_return_exceedance_overlay,
)
from app.themes.industry_wave import (
    INDUSTRY_DENSIFY,
    build_industry_scrub_frames,
)
from app.themes.wave_surface import MAP_SLIDER_AFTER, MAP_SLIDER_BEFORE

STOCK_BASKET_MAX = 300
STOCK_BASKET_WINDOW_DAYS = 40
_NAME_SPLIT = re.compile(r"[\s,，、;；]+")


class NamedBoard(Protocol):
    board_type: str
    board_code: str
    board_name: str

STOCK_AXIS_NOTE = (
    "横轴：所选板块/概念成分股并集，热度只在该并集内截面排名"
    "（公式与板块热度相同：均价MA2收益 → MA5 → 竞争名次）；"
    "排列按窗口内短热轨迹相似度层次聚类最优叶序（共动近的挨在一起，整窗不逐日重排）；"
    "相邻个股之间已插值成连续色场；颜色为当日短热截面分位翻转（越高越热）；进深为时间；"
    f"方格下沿细线=该日收盘收益超过自身近{RETURN_VOL_LOOKBACK}日收益波动率"
    f"{RETURN_VOL_MULT:.0f}倍（黑=正超，白=负超）；"
    "最后交易日顶上红/绿字=当日正超/负超的个股名；"
    "小交叉×=MACD（上穿橙、下穿蓝）；"
    "右侧细折线=中证500（sh.000905）同日收盘收益，虚线=成交量（已按双方波动对齐到收益尺度）。"
)


def parse_name_query(text: str) -> list[str]:
    """Split pasted board/concept names; keep first occurrence of each token."""
    parts = [part.strip() for part in _NAME_SPLIT.split(text or "") if part.strip()]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        out.append(part)
    return out


def match_board_queries(
    queries: list[str],
    catalog: list[NamedBoard],
) -> tuple[list[NamedBoard], list[str]]:
    """Exact name or code, else a unique name substring. Same name on two types keeps both."""
    matched: list[NamedBoard] = []
    seen: set[tuple[str, str]] = set()
    unmatched: list[str] = []

    def _add(items: list[NamedBoard]) -> None:
        for item in items:
            key = (item.board_type, item.board_code)
            if key in seen:
                continue
            seen.add(key)
            matched.append(item)

    for query in queries:
        exact_name = [item for item in catalog if item.board_name == query]
        if exact_name:
            _add(exact_name)
            continue
        exact_code = [item for item in catalog if item.board_code == query]
        if exact_code:
            _add(exact_code)
            continue
        contains = [item for item in catalog if query in (item.board_name or "")]
        unique_names = {item.board_name for item in contains}
        if len(unique_names) == 1:
            _add(contains)
            continue
        unmatched.append(query)
    return matched, unmatched


def union_constituents(
    members_by_board: dict[tuple[str, str], list[tuple[str, str]]],
) -> tuple[list[str], dict[str, str], dict[str, int]]:
    """Union stock codes; names prefer first non-empty; counts are board hits."""
    names: dict[str, str] = {}
    hits: dict[str, int] = defaultdict(int)
    for stocks in members_by_board.values():
        seen_here: set[str] = set()
        for code, name in stocks:
            if not code or code in seen_here:
                continue
            seen_here.add(code)
            hits[code] += 1
            if code not in names or (name and not names[code]):
                names[code] = name or code
    ranked = sorted(hits, key=lambda code: (-hits[code], code))
    return ranked, names, dict(hits)


def _to_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def bars_to_returns(bars: list[dict[str, object]]) -> list[BoardReturn]:
    out: list[BoardReturn] = []
    for bar in bars:
        high = _to_decimal(bar.get("high"))
        low = _to_decimal(bar.get("low"))
        close = _to_decimal(bar.get("close"))
        code = str(bar.get("code") or "")
        day = bar.get("trade_date")
        if not code or high is None or low is None or close is None:
            continue
        if not isinstance(day, date):
            try:
                day = date.fromisoformat(str(day))
            except ValueError:
                continue
        pct = _to_decimal(bar.get("pct_chg"))
        out.append(
            BoardReturn(
                trade_date=day,
                board_code=code,
                pct_chg=pct,
                high=high,
                low=low,
                close=close,
            )
        )
    return out


def group_bars_by_code(
    bars: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for bar in bars:
        code = str(bar.get("code") or "")
        if not code:
            continue
        grouped[code].append(bar)
    return dict(grouped)


def heat_rows_to_tuples(
    rows: list[BoardHeatRow],
    names: dict[str, str],
) -> list[tuple[date, str, str, object | None, object | None]]:
    return [
        (
            row.trade_date,
            row.board_code,
            names.get(row.board_code, row.board_code),
            row.heat_short,
            row.heat_long,
        )
        for row in rows
    ]


def close_heat_from_bars_and_heat(
    bars_by_code: dict[str, list[dict[str, object]]],
    heat_rows: list[BoardHeatRow],
) -> dict[str, list[tuple[date, object, object, object]]]:
    heat_map: dict[tuple[str, date], BoardHeatRow] = {
        (row.board_code, row.trade_date): row for row in heat_rows
    }
    out: dict[str, list[tuple[date, object, object, object]]] = {}
    for code, bars in bars_by_code.items():
        series: list[tuple[date, object, object, object]] = []
        for bar in sorted(bars, key=lambda item: str(item.get("trade_date"))):
            day = bar.get("trade_date")
            if not isinstance(day, date):
                continue
            heat = heat_map.get((code, day))
            series.append(
                (
                    day,
                    bar.get("close"),
                    None if heat is None else heat.heat_short,
                    None if heat is None else heat.heat_long,
                )
            )
        if series:
            out[code] = series
    return out


def build_stock_heat_plane(
    *,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, str, object | None, object | None]],
    bars_by_code: dict[str, list[dict[str, object]]],
    vol_calendar: list[date],
    close_heat_by_code: dict[str, list[tuple[date, object, object, object]]],
    csi500_closes: dict[date, float] | None = None,
    csi500_volumes: dict[date, float] | None = None,
    densify: int = INDUSTRY_DENSIFY,
) -> dict:
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": STOCK_AXIS_NOTE,
        "as_of": None,
        "board_count": 0,
        "densify": densify,
        "return_exceedance": {
            "pos_x": [],
            "pos_y": [],
            "neg_x": [],
            "neg_y": [],
            "last_pos_x": [],
            "last_pos_y": [],
            "last_pos_text": [],
            "last_neg_x": [],
            "last_neg_y": [],
            "last_neg_text": [],
            "pos_count": 0,
            "neg_count": 0,
            "lookback": RETURN_VOL_LOOKBACK,
            "mult": RETURN_VOL_MULT,
        },
        "cross_marks": empty_cross_mark_overlay(),
        "csi500_returns": [],
        "csi500_volumes": [],
        "csi500_volumes_scaled": [],
        "empty_message": "没有可绘制的个股热度窗口",
    }
    if not window_dates:
        return attach_surface_flags(empty)

    short_by_day: dict[date, dict[str, float]] = {}
    names: dict[str, str] = {}
    for trade_date, board_code, board_name, heat_short, _heat_long in heat_rows:
        if board_code not in names and board_name:
            names[board_code] = str(board_name)
        short_val = as_float(heat_short)
        if short_val is not None:
            short_by_day.setdefault(trade_date, {})[board_code] = short_val

    all_codes = sorted(names.keys()) or sorted(
        {code for day_map in short_by_day.values() for code in day_map}
    )
    if not all_codes:
        return attach_surface_flags(empty)
    for code in all_codes:
        names.setdefault(code, code)

    as_of = window_dates[-1]
    series_by_code = hotness_series_by_code(
        window_dates=window_dates,
        codes=all_codes,
        heat_by_day=short_by_day,
    )
    ordered_codes = order_by_trajectory_seriation(all_codes, series_by_code)
    board_names = [names[code] for code in ordered_codes]
    theme_x = [float(i) for i in range(len(ordered_codes))]
    z_raw = hotness_grid(
        window_dates=window_dates,
        ordered_codes=ordered_codes,
        heat_by_day=short_by_day,
    )
    return_exceedance = build_return_exceedance_overlay(
        ordered_codes=ordered_codes,
        window_dates=window_dates,
        bars_by_code=bars_by_code,
        vol_calendar=vol_calendar or window_dates,
        names=names,
    )
    cross_marks = build_cross_mark_overlay(
        ordered_codes=ordered_codes,
        window_dates=window_dates,
        close_heat_by_code=close_heat_by_code,
        names=names,
    )
    if csi500_closes is not None:
        _csi = csi500_overlay_series(
            window_dates,
            closes=csi500_closes,
            volumes=csi500_volumes or {},
        )
    else:
        _csi = {
            "returns": [None] * len(window_dates),
            "volumes": [None] * len(window_dates),
            "volumes_scaled": [None] * len(window_dates),
        }
    payload = {
        "dates": [day.isoformat() for day in window_dates],
        "board_codes": ordered_codes,
        "board_names": board_names,
        "x": theme_x,
        "x_tickvals": theme_x,
        "x_ticktext": board_names,
        "z_short": z_raw,
        "axis_note": STOCK_AXIS_NOTE,
        "as_of": as_of.isoformat(),
        "board_count": len(ordered_codes),
        "densify": densify,
        "return_exceedance": return_exceedance,
        "cross_marks": cross_marks,
        "csi500_returns": _csi["returns"],
        "csi500_volumes": _csi["volumes"],
        "csi500_volumes_scaled": _csi["volumes_scaled"],
        "empty_message": None,
        "heat_by_day": short_by_day,
        "names": names,
    }
    payload = attach_surface_flags(payload)
    dense_x, dense_z = densify_hotness_plane(
        theme_x=theme_x, z_short=z_raw, densify=densify
    )
    payload["z_boards"] = z_raw
    payload["x"] = dense_x
    payload["z_short"] = dense_z
    return payload


def build_trading_slider_dates(
    center: date,
    *,
    before: int = MAP_SLIDER_BEFORE,
    after: int = MAP_SLIDER_AFTER,
) -> tuple[list[date], int]:
    from app.db import fetch_trading_dates_after, fetch_trading_dates_ending

    span = before + 1 + after
    left = fetch_trading_dates_ending("industry", center, before + 1)
    right = fetch_trading_dates_after("industry", center, after)
    if len(left) >= before + 1 and len(right) >= after:
        return left + right[:after], before
    right_end = right[-1] if right else center
    dates = fetch_trading_dates_ending("industry", right_end, span)
    if not dates:
        return [center], 0
    if center in dates:
        return dates, dates.index(center)
    return dates, len(dates) - 1


def build_stock_basket_page_payload(
    *,
    names_text: str,
    as_of: date | None,
    days: int = STOCK_BASKET_WINDOW_DAYS,
    include_plotlyjs: bool = False,
) -> dict:
    from app.charts.theme_wave import render_theme_wave_contour
    from app.db import (
        fetch_board_constituents_named,
        fetch_latest_board_codes,
        fetch_stock_bars_for_codes,
        fetch_stock_code_names,
        fetch_trading_dates_ending,
    )

    queries = parse_name_query(names_text)
    today = date.today()
    calendar_tip = fetch_trading_dates_ending("industry", today, 1)
    selected = as_of or (calendar_tip[-1] if calendar_tip else today)
    slider_dates, slider_index = build_trading_slider_dates(selected)
    if slider_dates:
        selected = slider_dates[slider_index]

    base = {
        "title": "成分股热度水面",
        "names_text": names_text,
        "as_of": selected.isoformat(),
        "days": days,
        "queries": queries,
        "matched_boards": [],
        "unmatched": [],
        "truncated": 0,
        "universe_n": 0,
        "chart_html": None,
        "axis_note": STOCK_AXIS_NOTE,
        "meta_line": "",
        "empty_message": None,
        "window_start": None,
        "window_end": None,
        "board_names": [],
        "board_codes": [],
        "date_count": 0,
        "slider_dates": [day.isoformat() for day in slider_dates],
        "slider_index": slider_index,
        "scrub_frames": [],
        "stock_rim": {"rows": [], "note": ""},
        "include_plotlyjs": include_plotlyjs,
    }
    if not queries:
        base["empty_message"] = "输入行业或概念名称后绘制；热度只在选出的个股并集内排名。"
        base["meta_line"] = "尚未选择板块。"
        return base

    catalog = fetch_latest_board_codes()
    matched, unmatched = match_board_queries(queries, catalog)
    base["matched_boards"] = [
        {
            "board_type": item.board_type,
            "board_code": item.board_code,
            "board_name": item.board_name,
        }
        for item in matched
    ]
    base["unmatched"] = unmatched
    if not matched:
        base["empty_message"] = "没有匹配到板块或概念。"
        base["meta_line"] = "未匹配：" + "、".join(unmatched) if unmatched else "没有匹配。"
        return base

    members_by_board: dict[tuple[str, str], list[tuple[str, str]]] = {}
    by_type: dict[str, list[str]] = defaultdict(list)
    for item in matched:
        by_type[item.board_type].append(item.board_code)
    for board_type, codes in by_type.items():
        named = fetch_board_constituents_named(board_type, codes, selected)
        for code in codes:
            members_by_board[(board_type, code)] = named.get(code) or []

    codes, names, _hits = union_constituents(members_by_board)
    universe_all = len(codes)
    truncated = 0
    if len(codes) > STOCK_BASKET_MAX:
        truncated = len(codes) - STOCK_BASKET_MAX
        codes = codes[:STOCK_BASKET_MAX]
        names = {code: names[code] for code in codes}
    universe_names = fetch_stock_code_names(codes)
    for code in codes:
        if universe_names.get(code):
            names[code] = universe_names[code]
        else:
            names.setdefault(code, code)
    base["universe_n"] = len(codes)
    base["truncated"] = truncated
    matched_label = "、".join(
        f"{item.board_name}（{item.board_type}）" for item in matched
    )
    meta_bits = [
        f"匹配 {len(matched)} 个板块：{matched_label}",
        f"并集 {universe_all} 只",
    ]
    if truncated:
        meta_bits.append(f"按成分重叠优先截取 {STOCK_BASKET_MAX} 只（余 {truncated}）")
    if unmatched:
        meta_bits.append("未匹配：" + "、".join(unmatched))
    base["meta_line"] = " · ".join(meta_bits)
    if not codes:
        base["empty_message"] = "匹配到的板块没有成分股。"
        return base

    slider_end = slider_dates[-1] if slider_dates else selected
    regime_need = REGIME_DISPLAY_DAYS + REGIME_WARMUP_DAYS + REGIME_PLANE_WINDOW
    lookback = max(
        days
        + len(slider_dates)
        + max(RETURN_VOL_LOOKBACK, CROSS_HISTORY_DAYS)
        + 25,
        regime_need + 5,
    )
    all_dates = fetch_trading_dates_ending("industry", slider_end, lookback)
    if not all_dates:
        base["empty_message"] = "没有可用的交易日历。"
        return base
    bar_start = all_dates[0]
    bars = fetch_stock_bars_for_codes(codes, bar_start, slider_end)
    returns = bars_to_returns(bars)
    heat = compute_heat(returns, board_type="stock")
    heat_tuples = heat_rows_to_tuples(heat, names)
    bars_by_code = group_bars_by_code(bars)
    close_heat = close_heat_from_bars_and_heat(bars_by_code, heat)
    csi_closes, csi_volumes = csi500_maps_ending(slider_end)

    window_end_i = (
        all_dates.index(selected) if selected in all_dates else len(all_dates) - 1
    )
    window_start_i = max(0, window_end_i - days + 1)
    window_dates = all_dates[window_start_i : window_end_i + 1]
    plane = build_stock_heat_plane(
        window_dates=window_dates,
        heat_rows=heat_tuples,
        bars_by_code=bars_by_code,
        vol_calendar=all_dates,
        close_heat_by_code=close_heat,
        csi500_closes=csi_closes,
        csi500_volumes=csi_volumes,
        densify=DEFAULT_PLANE_DENSIFY,
    )
    if plane.get("empty_message"):
        base["empty_message"] = plane["empty_message"]
        return base

    chart_html = render_theme_wave_contour(
        dates=plane["dates"],
        x=plane["x"],
        z=plane["z_short"],
        x_tickvals=plane["x_tickvals"],
        x_ticktext=plane["x_ticktext"],
        include_plotlyjs=include_plotlyjs,
        height=620,
        title="成分股短热 · 轨迹聚类叶序",
        xaxis_title="个股（共动近 → 相邻）",
        entity_label="个股",
        tickangle=-55,
        return_exceedance=plane.get("return_exceedance"),
        cross_marks=plane.get("cross_marks"),
        csi500_returns=plane.get("csi500_returns"),
        csi500_volumes=plane.get("csi500_volumes"),
        csi500_volumes_scaled=plane.get("csi500_volumes_scaled"),
    )
    heat_by_day: dict[date, dict[str, float]] = {}
    for trade_date, board_code, _name, heat_short, _long in heat_tuples:
        val = as_float(heat_short)
        if val is None:
            continue
        heat_by_day.setdefault(trade_date, {})[str(board_code)] = val
    ordered = list(plane.get("board_codes") or [])
    board_names = list(plane.get("board_names") or [])
    name_map = {str(k): str(v) for k, v in (plane.get("names") or names).items()}
    stock_rim = build_regime_panel_payload(
        as_of=selected,
        calendar=all_dates,
        heat_by_day=heat_by_day,
        names=name_map,
        bars_by_code=bars_by_code,
        vol_calendar=all_dates,
    )
    scrub = build_industry_scrub_frames(
        slider_dates=slider_dates,
        window_days=days,
        ordered_codes=ordered,
        heat_by_day=heat_by_day,
        all_heat_dates=all_dates,
        densify=int(plane.get("densify") or INDUSTRY_DENSIFY),
        bars_by_code=bars_by_code,
        vol_all_dates=all_dates,
        names=name_map,
        csi500_closes=csi_closes,
        csi500_volumes=csi_volumes,
        close_heat_by_code=close_heat,
    )
    base.update(
        {
            "chart_html": chart_html,
            "axis_note": plane.get("axis_note") or STOCK_AXIS_NOTE,
            "empty_message": None,
            "window_start": window_dates[0].isoformat() if window_dates else None,
            "window_end": window_dates[-1].isoformat() if window_dates else None,
            "board_names": board_names,
            "board_codes": ordered,
            "date_count": len(plane.get("dates") or []),
            "scrub_frames": scrub,
            "stock_rim": stock_rim,
            "universe_n": len(ordered),
        }
    )
    extra = f" · 入选 {len(ordered)} 只 · 窗口 {base['window_start']} → {base['window_end']}"
    extra += f" · 成分重叠优先，热度只在这 {len(ordered)} 只里排名"
    base["meta_line"] = (base["meta_line"] or "") + extra
    return base
