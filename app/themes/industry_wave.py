"""Industry-board short-heat plane for the theme-wave page."""

from __future__ import annotations

from datetime import date

from app.db import (
    fetch_board_close_heat,
    fetch_board_daily_bars_many,
    fetch_heat_dates_ending,
)
from app.market_data.csi500 import csi500_overlay_for_dates, csi500_overlay_series
from app.themes.board_cross_marks import (
    CROSS_HISTORY_DAYS,
    build_cross_mark_overlay,
    empty_cross_mark_overlay,
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

INDUSTRY_AXIS_NOTE = (
    "横轴：全部行业板块，按窗口内短热轨迹相似度做层次聚类最优叶序固定排列"
    "（共动近的挨在一起，整窗不逐日重排）；相邻行业之间已插值成连续色场"
    "（轮转轴本就不精确，平滑插值是读图手段）；"
    "颜色为当日短热截面分位翻转（越高越热）；进深为时间；"
    f"方格下沿细线=该日收盘收益超过自身近{RETURN_VOL_LOOKBACK}日收益波动率"
    f"{RETURN_VOL_MULT:.0f}倍（黑=正超，白=负超）；"
    "最后交易日顶上红/绿字=当日正超/负超的行业名；"
    "小交叉×=MACD（上穿橙、下穿蓝）；"
    "右侧细折线=中证500（sh.000905）同日收盘收益，虚线=成交量（已按双方波动对齐到收益尺度）。"
)

INDUSTRY_DENSIFY = DEFAULT_PLANE_DENSIFY


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


def build_industry_board_heat_payload(
    *,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, str, object | None, object | None]],
    densify: int = INDUSTRY_DENSIFY,
    csi500_closes: dict[date, float] | None = None,
    csi500_volumes: dict[date, float] | None = None,
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
        "densify": densify,
        "return_exceedance": _empty_return_overlay(),
        "cross_marks": empty_cross_mark_overlay(),
        "csi500_returns": [],
        "csi500_volumes": [],
        "csi500_volumes_scaled": [],
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

    z_raw = hotness_grid(
        window_dates=window_dates,
        ordered_codes=ordered_codes,
        heat_by_day=short_by_day,
    )

    vol_calendar = fetch_heat_dates_ending(
        "industry", as_of, RETURN_VOL_LOOKBACK + 1
    )
    bars_by_code: dict[str, list[dict[str, object]]] = {}
    if vol_calendar:
        bars_by_code = fetch_board_daily_bars_many(
            "industry", ordered_codes, vol_calendar[0], as_of
        )
    return_exceedance = build_return_exceedance_overlay(
        ordered_codes=ordered_codes,
        window_dates=window_dates,
        bars_by_code=bars_by_code,
        vol_calendar=vol_calendar or window_dates,
        names=names,
    )
    cross_hist = fetch_heat_dates_ending(
        "industry", as_of, CROSS_HISTORY_DAYS + len(window_dates)
    )
    cross_start = cross_hist[0] if cross_hist else window_dates[0]
    close_heat = fetch_board_close_heat(
        "industry", ordered_codes, cross_start, as_of
    )
    cross_marks = build_cross_mark_overlay(
        ordered_codes=ordered_codes,
        window_dates=window_dates,
        close_heat_by_code=close_heat,
        names=names,
    )
    if csi500_closes is not None:
        _csi = csi500_overlay_series(
            window_dates,
            closes=csi500_closes,
            volumes=csi500_volumes or {},
        )
    else:
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
            "axis_note": INDUSTRY_AXIS_NOTE,
            "as_of": as_of.isoformat(),
            "board_count": len(ordered_codes),
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
    # Densified plane is for plotting; wavelet/features need native board columns.
    payload["z_boards"] = z_raw
    payload["x"] = dense_x
    payload["z_short"] = dense_z
    return payload


def build_industry_scrub_frames(
    *,
    slider_dates: list[date],
    window_days: int,
    ordered_codes: list[str],
    heat_by_day: dict[date, dict[str, float]],
    all_heat_dates: list[date],
    densify: int = INDUSTRY_DENSIFY,
    bars_by_code: dict[str, list[dict[str, object]]] | None = None,
    vol_all_dates: list[date] | None = None,
    names: dict[str, str] | None = None,
    csi500_closes: dict[date, float] | None = None,
    csi500_volumes: dict[date, float] | None = None,
    close_heat_by_code: (
        dict[str, list[tuple[date, object, object, object]]] | None
    ) = None,
) -> list[dict]:
    """Per slider day: trailing industry hotness grid with frozen densified X."""
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
