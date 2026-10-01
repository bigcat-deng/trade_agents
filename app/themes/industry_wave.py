"""Industry-board short-heat plane for the theme-wave page."""

from __future__ import annotations

from datetime import date

from app.themes.heat_seriation import (
    as_float,
    hotness_grid,
    hotness_series_by_code,
    order_by_trajectory_seriation,
)
from app.themes.heat_surface_flags import attach_surface_flags

INDUSTRY_AXIS_NOTE = (
    "横轴：全部行业板块，按窗口内短热轨迹相似度做层次聚类最优叶序固定排列"
    "（共动近的挨在一起，整窗不逐日重排）；"
    "颜色为当日短热截面分位翻转（越高越热）；进深为时间。"
)


def build_industry_board_heat_payload(
    *,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, str, object | None, object | None]],
) -> dict:
    """Return industry short-heat plane with trajectory-seriation X order."""
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": INDUSTRY_AXIS_NOTE,
        "as_of": None,
        "board_count": 0,
        "empty_message": "没有可绘制的行业热度窗口",
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

    z_short = hotness_grid(
        window_dates=window_dates,
        ordered_codes=ordered_codes,
        heat_by_day=short_by_day,
    )

    return attach_surface_flags(
        {
            "dates": [day.isoformat() for day in window_dates],
            "board_codes": ordered_codes,
            "board_names": board_names,
            "x": theme_x,
            "x_tickvals": theme_x,
            "x_ticktext": board_names,
            "z_short": z_short,
            "axis_note": INDUSTRY_AXIS_NOTE,
            "as_of": as_of.isoformat(),
            "board_count": len(ordered_codes),
            "empty_message": None,
        }
    )
