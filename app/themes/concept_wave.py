"""Concept short-heat plane for the theme-wave page.

Roster = late-quarter short-heat TopN ∪ all theme-domain concepts
(group A + group B + satellites), then fused trajectory+structure seriation.
"""

from __future__ import annotations

from datetime import date

from app.db import (
    fetch_board_close_heat,
    fetch_board_constituents_many,
    fetch_board_daily_bars_many,
    fetch_heat_dates_ending,
)
from app.market_data.csi500 import csi500_overlay_for_dates, csi500_overlay_series
from app.themes.board_cross_marks import (
    CROSS_HISTORY_DAYS,
    build_cross_mark_overlay,
    empty_cross_mark_overlay,
)
from app.themes.config import theme_board_codes
from app.themes.heat_seriation import (
    DEFAULT_PLANE_DENSIFY,
    DEFAULT_TRAJ_WEIGHT,
    as_float,
    densify_hotness_plane,
    hotness_grid,
    hotness_series_by_code,
    late_quarter_dates,
    order_by_fused_seriation,
    select_top_codes_by_late_short_heat,
)
from app.themes.heat_surface_flags import attach_surface_flags
from app.themes.industry_return_flags import (
    RETURN_VOL_LOOKBACK,
    RETURN_VOL_MULT,
    build_return_exceedance_overlay,
)
from app.themes.service import list_themes

CONCEPT_TOP_N = 200
CONCEPT_DENSIFY = DEFAULT_PLANE_DENSIFY
CONCEPT_TRAJ_WEIGHT = DEFAULT_TRAJ_WEIGHT


def _empty_return_overlay() -> dict[str, object]:
    return {
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
    }


def _theme_member_codes() -> list[str]:
    """Deduped group A + B + satellite codes across all registered themes."""
    seen: set[str] = set()
    ordered: list[str] = []
    for theme in list_themes():
        for code in theme_board_codes(theme):
            if code in seen:
                continue
            seen.add(code)
            ordered.append(code)
    return ordered


def _theme_ids_by_concept_code() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for theme in list_themes():
        for code in theme_board_codes(theme):
            out.setdefault(code, set()).add(theme.theme_id)
    return out


def _axis_note(*, top_n: int, top_count: int, theme_added: int, board_count: int) -> str:
    return (
        f"横轴：近窗靠后四分之一短热均值最热的前 {top_n} 个概念"
        f"（实取 {top_count}）"
        f"∪ 全部主题分析概念（群A+群B+卫星，补入 {theme_added} 个），"
        f"合计 {board_count} 列；"
        "叶序=轨迹相关距离与结构先验融合（成分股 Jaccard + 名称字集相似"
        f" + 同主题软提升；轨迹权重 α≈{CONCEPT_TRAJ_WEIGHT:.2f}），"
        "再层次聚类最优叶序固定排列；"
        "相邻概念之间已插值成连续色场（轮转轴本就不精确，平滑插值是读图手段）；"
        "颜色为当日全市场概念短热分位翻转（越高越热）；进深为时间；"
        f"方格下沿细线=该日收盘收益超过自身近{RETURN_VOL_LOOKBACK}日收益波动率"
        f"{RETURN_VOL_MULT:.0f}倍（黑=正超，白=负超）；"
        "最后交易日顶上红/绿字=当日正超/负超的概念名；"
        "小交叉：×=MACD、◆=短长热交叉，上穿橙、下穿蓝；"
        "右侧细折线=中证500（sh.000905）同日收盘收益，虚线=成交量（已按双方波动对齐到收益尺度）。"
    )


def build_concept_top_heat_payload(
    *,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, str, object | None, object | None]],
    top_n: int = CONCEPT_TOP_N,
    densify: int = CONCEPT_DENSIFY,
) -> dict:
    """Return concept short-heat plane: TopN ∪ theme members, fused seriation."""
    axis_note = _axis_note(top_n=top_n, top_count=0, theme_added=0, board_count=0)
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": axis_note,
        "as_of": None,
        "select_from": None,
        "select_to": None,
        "board_count": 0,
        "top_n": top_n,
        "top_count": 0,
        "theme_added": 0,
        "densify": densify,
        "return_exceedance": _empty_return_overlay(),
        "cross_marks": empty_cross_mark_overlay(),
        "csi500_returns": [],
        "csi500_volumes": [],
        "csi500_volumes_scaled": [],
        "empty_message": "没有可绘制的概念热度窗口",
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
    available = set(all_codes)

    top_selected = select_top_codes_by_late_short_heat(
        window_dates=window_dates,
        heat_by_day=short_by_day,
        candidate_codes=all_codes,
        top_n=top_n,
    )
    if not top_selected:
        return attach_surface_flags(empty)

    selected_set = set(top_selected)
    theme_added_codes: list[str] = []
    for code in _theme_member_codes():
        if code not in available or code in selected_set:
            continue
        selected_set.add(code)
        theme_added_codes.append(code)

    selected = list(top_selected) + theme_added_codes
    late_days = late_quarter_dates(window_dates)
    as_of = window_dates[-1]
    series_by_code = hotness_series_by_code(
        window_dates=window_dates,
        codes=selected,
        heat_by_day=short_by_day,
    )
    constituents = fetch_board_constituents_many(
        "concept", selected, as_of=as_of
    )
    ordered_codes = order_by_fused_seriation(
        selected,
        series_by_code,
        names=names,
        constituents=constituents,
        theme_ids_by_code=_theme_ids_by_concept_code(),
        traj_weight=CONCEPT_TRAJ_WEIGHT,
    )
    board_names = [names[code] for code in ordered_codes]
    theme_x = [float(i) for i in range(len(ordered_codes))]

    z_raw = hotness_grid(
        window_dates=window_dates,
        ordered_codes=ordered_codes,
        heat_by_day=short_by_day,
    )

    top_count = len(top_selected)
    theme_added = len(theme_added_codes)
    board_count = len(ordered_codes)
    vol_calendar = fetch_heat_dates_ending(
        "concept", as_of, RETURN_VOL_LOOKBACK + 1
    )
    bars_by_code: dict[str, list[dict[str, object]]] = {}
    if vol_calendar:
        bars_by_code = fetch_board_daily_bars_many(
            "concept", ordered_codes, vol_calendar[0], as_of
        )
    return_exceedance = build_return_exceedance_overlay(
        ordered_codes=ordered_codes,
        window_dates=window_dates,
        bars_by_code=bars_by_code,
        vol_calendar=vol_calendar or window_dates,
        names=names,
    )
    cross_hist = fetch_heat_dates_ending(
        "concept", as_of, CROSS_HISTORY_DAYS + len(window_dates)
    )
    cross_start = cross_hist[0] if cross_hist else window_dates[0]
    close_heat = fetch_board_close_heat(
        "concept", ordered_codes, cross_start, as_of
    )
    cross_marks = build_cross_mark_overlay(
        ordered_codes=ordered_codes,
        window_dates=window_dates,
        close_heat_by_code=close_heat,
        names=names,
    )
    _csi = csi500_overlay_for_dates(window_dates)
    payload = attach_surface_flags(
        {
            "dates": [day.isoformat() for day in window_dates],
            "board_codes": ordered_codes,
            "board_names": board_names,
            "x": theme_x,
            "x_tickvals": theme_x,
            "x_ticktext": board_names,
            "z_short": z_raw,
            "axis_note": _axis_note(
                top_n=top_n,
                top_count=top_count,
                theme_added=theme_added,
                board_count=board_count,
            ),
            "as_of": as_of.isoformat(),
            "select_from": late_days[0].isoformat() if late_days else None,
            "select_to": late_days[-1].isoformat() if late_days else None,
            "board_count": board_count,
            "top_n": top_n,
            "top_count": top_count,
            "theme_added": theme_added,
            "densify": densify,
            "return_exceedance": return_exceedance,
            "cross_marks": cross_marks,
            "csi500_returns": _csi["returns"],
            "csi500_volumes": _csi["volumes"],
            "csi500_volumes_scaled": _csi["volumes_scaled"],
            "empty_message": None,
        }
    )
    dense_x, dense_z = densify_hotness_plane(
        theme_x=theme_x, z_short=z_raw, densify=densify
    )
    payload["x"] = dense_x
    payload["z_short"] = dense_z
    return payload


def build_concept_scrub_frames(
    *,
    slider_dates: list[date],
    window_days: int,
    ordered_codes: list[str],
    heat_by_day: dict[date, dict[str, float]],
    all_heat_dates: list[date],
    densify: int = CONCEPT_DENSIFY,
    bars_by_code: dict[str, list[dict[str, object]]] | None = None,
    vol_all_dates: list[date] | None = None,
    names: dict[str, str] | None = None,
    csi500_closes: dict[date, float] | None = None,
    csi500_volumes: dict[date, float] | None = None,
    close_heat_by_code: (
        dict[str, list[tuple[date, object, object, object]]] | None
    ) = None,
) -> list[dict]:
    """Per slider day: trailing concept hotness grid with frozen densified X."""
    theme_x = [float(i) for i in range(len(ordered_codes))]
    date_index = {day: i for i, day in enumerate(all_heat_dates)}
    vol_index = {
        day: i for i, day in enumerate(vol_all_dates or all_heat_dates)
    }
    vol_dates = vol_all_dates or all_heat_dates
    bars = bars_by_code or {}
    close_heat = close_heat_by_code or {}
    frames: list[dict] = []
    for end in slider_dates:
        end_i = date_index.get(end)
        if end_i is None:
            window: list[date] = []
        else:
            start_i = max(0, end_i - window_days + 1)
            window = all_heat_dates[start_i : end_i + 1]
        z_raw = hotness_grid(
            window_dates=window,
            ordered_codes=ordered_codes,
            heat_by_day=heat_by_day,
        )
        _dense_x, dense_z = densify_hotness_plane(
            theme_x=theme_x, z_short=z_raw, densify=densify
        )
        vol_end_i = vol_index.get(end)
        if vol_end_i is None or not window:
            overlay = _empty_return_overlay()
            cross_marks = empty_cross_mark_overlay()
        else:
            vol_start_i = max(0, vol_end_i - RETURN_VOL_LOOKBACK)
            vol_calendar = vol_dates[vol_start_i : vol_end_i + 1]
            overlay = build_return_exceedance_overlay(
                ordered_codes=ordered_codes,
                window_dates=window,
                bars_by_code=bars,
                vol_calendar=vol_calendar,
                names=names,
            )
            cross_marks = build_cross_mark_overlay(
                ordered_codes=ordered_codes,
                window_dates=window,
                close_heat_by_code=close_heat,
                names=names,
            )
        csi = csi500_overlay_series(
            window,
            closes=csi500_closes or {},
            volumes=csi500_volumes or {},
        )
        frames.append(
            {
                "as_of": end.isoformat(),
                "dates": [day.isoformat() for day in window],
                "z_short": dense_z,
                "return_exceedance": overlay,
                "cross_marks": cross_marks,
                "csi500_returns": csi["returns"],
                "csi500_volumes": csi["volumes"],
                "csi500_volumes_scaled": csi["volumes_scaled"],
            }
        )
    return frames
