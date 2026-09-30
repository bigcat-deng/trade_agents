"""Top concept short-heat plane for the theme-wave page."""

from __future__ import annotations

from datetime import date

from app.themes.heat_seriation import (
    as_float,
    hotness_grid,
    hotness_series_by_code,
    late_quarter_dates,
    order_by_trajectory_seriation,
    select_top_codes_by_late_short_heat,
)

CONCEPT_TOP_N = 200

CONCEPT_AXIS_NOTE = (
    f"横轴：近窗靠后四分之一短热均值最热的前 {CONCEPT_TOP_N} 个概念，"
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
    """Return top-N concept short-heat plane with late-quarter pick + seriation."""
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": CONCEPT_AXIS_NOTE,
        "as_of": None,
        "select_from": None,
        "select_to": None,
        "board_count": 0,
        "top_n": top_n,
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

    selected = select_top_codes_by_late_short_heat(
        window_dates=window_dates,
        heat_by_day=short_by_day,
        candidate_codes=all_codes,
        top_n=top_n,
    )
    if not selected:
        return empty

    late_days = late_quarter_dates(window_dates)
    as_of = window_dates[-1]
    # Seriation / coloring percentiles use the full concept cross-section each day,
    # but columns are only the selected Top-N.
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

    return {
        "dates": [day.isoformat() for day in window_dates],
        "board_codes": ordered_codes,
        "board_names": board_names,
        "x": theme_x,
        "x_tickvals": theme_x,
        "x_ticktext": board_names,
        "z_short": z_short,
        "axis_note": CONCEPT_AXIS_NOTE,
        "as_of": as_of.isoformat(),
        "select_from": late_days[0].isoformat() if late_days else None,
        "select_to": late_days[-1].isoformat() if late_days else None,
        "board_count": len(ordered_codes),
        "top_n": top_n,
        "empty_message": None,
    }
