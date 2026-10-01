"""Concept short-heat plane for the theme-wave page.

Roster = late-quarter short-heat TopN ∪ all theme-domain concepts
(group A + group B + satellites).
"""

from __future__ import annotations

from datetime import date

from app.themes.config import theme_board_codes
from app.themes.heat_seriation import (
    as_float,
    hotness_grid,
    hotness_series_by_code,
    late_quarter_dates,
    order_by_trajectory_seriation,
    select_top_codes_by_late_short_heat,
)
from app.themes.service import list_themes

CONCEPT_TOP_N = 200


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


def _axis_note(*, top_n: int, top_count: int, theme_added: int, board_count: int) -> str:
    return (
        f"横轴：近窗靠后四分之一短热均值最热的前 {top_n} 个概念"
        f"（实取 {top_count}）"
        f"∪ 全部主题分析概念（群A+群B+卫星，补入 {theme_added} 个），"
        f"合计 {board_count} 列；"
        "再按整窗短热轨迹相似度做层次聚类最优叶序固定排列"
        "（共动近的挨在一起，名单与顺序整窗不重排）；"
        "颜色为当日全市场概念短热分位翻转（越高越热）；进深为时间。"
    )


def build_concept_top_heat_payload(
    *,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, str, object | None, object | None]],
    top_n: int = CONCEPT_TOP_N,
) -> dict:
    """Return concept short-heat plane: TopN ∪ theme members, then seriation."""
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
        "empty_message": "没有可绘制的概念热度窗口",
    }
    if not window_dates:
        return empty

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
        return empty

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
        return empty

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
    ordered_codes = order_by_trajectory_seriation(selected, series_by_code)
    board_names = [names[code] for code in ordered_codes]
    theme_x = [float(i) for i in range(len(ordered_codes))]

    z_short = hotness_grid(
        window_dates=window_dates,
        ordered_codes=ordered_codes,
        heat_by_day=short_by_day,
    )

    top_count = len(top_selected)
    theme_added = len(theme_added_codes)
    board_count = len(ordered_codes)
    return {
        "dates": [day.isoformat() for day in window_dates],
        "board_codes": ordered_codes,
        "board_names": board_names,
        "x": theme_x,
        "x_tickvals": theme_x,
        "x_ticktext": board_names,
        "z_short": z_short,
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
        "empty_message": None,
    }
