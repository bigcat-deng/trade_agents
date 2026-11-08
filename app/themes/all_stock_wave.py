"""All-stock short-heat plane (trajectory seriation, wave only)."""

from __future__ import annotations

from datetime import date

from app.db import (
    fetch_max_stock_heat_date,
    fetch_stock_code_names,
    fetch_stock_heat,
    fetch_stock_heat_dates_ending,
    fetch_stock_industry_names,
)
from app.market_data.codes import to_akshare_em
from app.themes.heat_seriation import (
    DEFAULT_PLANE_DENSIFY,
    as_float,
    densify_hotness_plane,
    hotness_grid,
    hotness_series_by_code,
    order_by_trajectory_seriation,
)

ALL_STOCK_WINDOW_DAYS = 20
# Full market (~5k names) keeps densify at 1 so the Plotly payload stays usable;
# Contour heatmap already fills between adjacent seriated cells.
ALL_STOCK_DENSIFY = 1
ZOOM_NAME_THRESHOLD = 60

ALL_STOCK_AXIS_NOTE = (
    "横轴：全市场个股，按窗口内短热轨迹相似度做层次聚类最优叶序固定排列"
    "（共动近的挨在一起，整窗不逐日重排）；"
    "颜色为当日短热截面分位翻转（越高越热）；进深为时间；"
    "默认不标名称；框选放大后若可见个股不超过"
    f"{ZOOM_NAME_THRESHOLD}只，横坐标显示名称。"
    "本图不标交叉与缠论分型。"
)


def resolve_stock_heat_as_of(requested: date | None) -> date | None:
    """Last stock-heat day on or before ``requested`` (default: today / max)."""
    target = requested or date.today()
    days = fetch_stock_heat_dates_ending(target, 1)
    if days:
        return days[-1]
    return fetch_max_stock_heat_date()


def build_all_stock_heat_payload(
    *,
    as_of: date,
    window_days: int = ALL_STOCK_WINDOW_DAYS,
    densify: int = ALL_STOCK_DENSIFY,
) -> dict:
    """Short-heat water-wave plane for the full stock universe."""
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": ALL_STOCK_AXIS_NOTE,
        "as_of": as_of.isoformat(),
        "board_count": 0,
        "densify": densify,
        "zoom_name_threshold": ZOOM_NAME_THRESHOLD,
        "stock_x": [],
        "stock_names": [],
        "stock_display_codes": [],
        "stock_industries": [],
        "empty_message": "没有可绘制的全股热度窗口",
    }
    window_dates = fetch_stock_heat_dates_ending(as_of, window_days)
    if not window_dates:
        return empty

    rows = fetch_stock_heat(start=window_dates[0], end=window_dates[-1])
    heat_by_day: dict[date, dict[str, float]] = {}
    codes_set: set[str] = set()
    window_set = set(window_dates)
    for row in rows:
        if row.trade_date not in window_set:
            continue
        value = as_float(row.heat_short)
        if value is None:
            continue
        heat_by_day.setdefault(row.trade_date, {})[row.board_code] = value
        codes_set.add(row.board_code)
    codes = sorted(codes_set)
    if not codes or not any(heat_by_day.get(day) for day in window_dates):
        empty["empty_message"] = "窗口内没有个股短热"
        return empty

    names = fetch_stock_code_names(codes)
    for code in codes:
        names.setdefault(code, code)
    industries = fetch_stock_industry_names(codes, as_of=window_dates[-1])

    series_by_code = hotness_series_by_code(
        window_dates=window_dates,
        codes=codes,
        heat_by_day=heat_by_day,
    )
    ordered_codes = order_by_trajectory_seriation(codes, series_by_code)
    board_names = [names[code] for code in ordered_codes]
    display_codes = [_display_code(code) for code in ordered_codes]
    industry_labels = [industries.get(code) or "—" for code in ordered_codes]
    theme_x = [float(i) for i in range(len(ordered_codes))]
    z_raw = hotness_grid(
        window_dates=window_dates,
        ordered_codes=ordered_codes,
        heat_by_day=heat_by_day,
    )
    dense_x, dense_z = densify_hotness_plane(
        theme_x=theme_x, z_short=z_raw, densify=densify
    )
    return {
        "dates": [day.isoformat() for day in window_dates],
        "board_codes": ordered_codes,
        "board_names": board_names,
        "x": dense_x,
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": dense_z,
        "axis_note": ALL_STOCK_AXIS_NOTE,
        "as_of": window_dates[-1].isoformat(),
        "board_count": len(ordered_codes),
        "densify": densify if densify >= 1 else DEFAULT_PLANE_DENSIFY,
        "zoom_name_threshold": ZOOM_NAME_THRESHOLD,
        "stock_x": theme_x,
        "stock_names": board_names,
        "stock_display_codes": display_codes,
        "stock_industries": industry_labels,
        "empty_message": None,
    }


def _display_code(code: str) -> str:
    try:
        return to_akshare_em(code)
    except ValueError:
        return code


def build_all_stock_hover_customdata(
    *,
    dates: list[str],
    x: list[float],
    z: list[list[float | None]],
    stock_x: list[float],
    display_codes: list[str],
    names: list[str],
    industries: list[str],
) -> list[list[list[str]]]:
    """Hover cells: code, name, date, heat, industry — aligned to densified x."""
    if not dates or not x or not z or not stock_x:
        return []
    nearest = [_nearest_stock_index(value, stock_x) for value in x]
    out: list[list[list[str]]] = []
    for day_i, day in enumerate(dates):
        row_z = z[day_i] if day_i < len(z) else []
        row: list[list[str]] = []
        for col_i, stock_i in enumerate(nearest):
            heat = row_z[col_i] if col_i < len(row_z) else None
            row.append(
                [
                    display_codes[stock_i] if stock_i < len(display_codes) else "—",
                    names[stock_i] if stock_i < len(names) else "—",
                    day,
                    _format_heat(heat),
                    industries[stock_i] if stock_i < len(industries) else "—",
                ]
            )
        out.append(row)
    return out


def _nearest_stock_index(x_value: float, stock_x: list[float]) -> int:
    best_i = 0
    best_dist = abs(x_value - stock_x[0])
    for i in range(1, len(stock_x)):
        dist = abs(x_value - stock_x[i])
        if dist < best_dist:
            best_i = i
            best_dist = dist
    return best_i


def _format_heat(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.3f}"


ALL_STOCK_HOVERTEMPLATE = (
    "代码 %{customdata[0]}<br>"
    "名称 %{customdata[1]}<br>"
    "日期 %{customdata[2]}<br>"
    "热度 %{customdata[3]}<br>"
    "行业板块 %{customdata[4]}<extra></extra>"
)
