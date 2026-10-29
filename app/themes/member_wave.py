"""Constituent-stock short-heat plane (trajectory seriation leaf order)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.charts.chan_board import WINDOW as CHAN_BARS
from app.db import (
    fetch_board_constituents_named,
    fetch_stock_bars_for_codes,
    fetch_trading_dates_ending,
)
from app.market_data.board_heat import BoardReturn, compute_heat
from app.market_data.csi500 import csi500_overlay_for_dates
from app.themes.board_cross_marks import (
    CROSS_HISTORY_DAYS,
    build_cross_mark_overlay,
    empty_cross_mark_overlay,
)
from app.themes.board_fractal_marks import (
    build_fractal_mark_overlay,
    empty_fractal_mark_overlay,
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
from scripts.chan_fractal_probe import WARMUP

MEMBER_WINDOW_DAYS = 40
MEMBER_DENSIFY = DEFAULT_PLANE_DENSIFY

MEMBER_AXIS_NOTE = (
    "横轴：本板块成分股，按窗口内短热轨迹相似度做层次聚类最优叶序固定排列"
    "（共动近的挨在一起，整窗不逐日重排）；相邻个股之间已插值成连续色场；"
    "颜色为当日短热截面分位翻转（越高越热，热度只在本集合内计算）；进深为时间；"
    f"方格下沿细线=该日收盘收益超过自身近{RETURN_VOL_LOOKBACK}日收益波动率"
    f"{RETURN_VOL_MULT:.0f}倍（黑=正超，白=负超）；"
    "最后交易日顶上红/绿字=当日正超/负超的个股名；"
    "小交叉×=MACD（上穿橙、下穿蓝）；"
    "红圆点=顶分型，黑圆点=底分型（与个股缠论同一套分型，只标落在本图日期内的）；"
    "右侧细折线=中证500同日收盘收益，虚线=成交量（已按双方波动对齐到收益尺度）。"
)


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


def build_member_short_heat_payload(
    *,
    board_type: str,
    board_code: str,
    as_of: date,
    window_days: int = MEMBER_WINDOW_DAYS,
    densify: int = MEMBER_DENSIFY,
) -> dict:
    """Short-heat plane for one board's constituents."""
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": MEMBER_AXIS_NOTE,
        "as_of": as_of.isoformat(),
        "board_count": 0,
        "densify": densify,
        "return_exceedance": _empty_return_overlay(),
        "cross_marks": empty_cross_mark_overlay(),
        "fractal_marks": empty_fractal_mark_overlay(),
        "csi500_returns": [],
        "csi500_volumes": [],
        "csi500_volumes_scaled": [],
        "empty_message": "没有可绘制的成分股热度窗口",
    }
    named = fetch_board_constituents_named(board_type, [board_code], as_of=as_of)
    members = named.get(board_code) or []
    if not members:
        return attach_surface_flags(empty)
    names = {code: (name or code) for code, name in members}
    codes = list(names.keys())
    window_dates = fetch_trading_dates_ending(board_type, as_of, window_days)
    if not window_dates:
        return attach_surface_flags(empty)
    hist_n = max(
        CROSS_HISTORY_DAYS + len(window_dates),
        CHAN_BARS + WARMUP + len(window_dates),
        RETURN_VOL_LOOKBACK + len(window_dates) + 5,
        window_days + 40,
    )
    hist_dates = fetch_trading_dates_ending(board_type, as_of, hist_n)
    bar_start = hist_dates[0] if hist_dates else window_dates[0]
    raw_bars = fetch_stock_bars_for_codes(codes, bar_start, as_of)
    bars_by_code: dict[str, list[dict[str, object]]] = {code: [] for code in codes}
    for row in raw_bars:
        code = str(row["code"])
        bars_by_code.setdefault(code, []).append(row)

    heat_by_day, close_heat = _heat_and_close_series(bars_by_code, as_of)
    if not any(heat_by_day.get(day) for day in window_dates):
        empty["empty_message"] = "成分股短热还不足以画图"
        return attach_surface_flags(empty)

    series_by_code = hotness_series_by_code(
        window_dates=window_dates,
        codes=codes,
        heat_by_day=heat_by_day,
    )
    ordered_codes = order_by_trajectory_seriation(codes, series_by_code)
    board_names = [names[code] for code in ordered_codes]
    theme_x = [float(i) for i in range(len(ordered_codes))]
    z_raw = hotness_grid(
        window_dates=window_dates,
        ordered_codes=ordered_codes,
        heat_by_day=heat_by_day,
    )
    vol_calendar = fetch_trading_dates_ending(
        board_type, as_of, RETURN_VOL_LOOKBACK + 1
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
        close_heat_by_code=close_heat,
        names=names,
    )
    fractal_marks = build_fractal_mark_overlay(
        ordered_codes=ordered_codes,
        window_dates=window_dates,
        bars_by_code=bars_by_code,
        names=names,
    )
    csi = csi500_overlay_for_dates(window_dates)
    payload = attach_surface_flags(
        {
            "dates": [day.isoformat() for day in window_dates],
            "board_codes": ordered_codes,
            "board_names": board_names,
            "x": theme_x,
            "x_tickvals": theme_x,
            "x_ticktext": board_names,
            "z_short": z_raw,
            "axis_note": MEMBER_AXIS_NOTE,
            "as_of": window_dates[-1].isoformat(),
            "board_count": len(ordered_codes),
            "densify": densify,
            "return_exceedance": return_exceedance,
            "cross_marks": cross_marks,
            "fractal_marks": fractal_marks,
            "csi500_returns": csi["returns"],
            "csi500_volumes": csi["volumes"],
            "csi500_volumes_scaled": csi["volumes_scaled"],
            "empty_message": None,
        }
    )
    dense_x, dense_z = densify_hotness_plane(
        theme_x=theme_x, z_short=z_raw, densify=densify
    )
    payload["x"] = dense_x
    payload["z_short"] = dense_z
    return payload


def _heat_and_close_series(
    bars_by_code: dict[str, list[dict[str, object]]],
    as_of: date,
) -> tuple[dict[date, dict[str, float]], dict[str, list[tuple[date, object, object, object]]]]:
    returns: list[BoardReturn] = []
    for code, rows in bars_by_code.items():
        for row in rows:
            if row.get("trade_date") is None or row.get("high") is None:
                continue
            if row.get("low") is None or row.get("close") is None:
                continue
            if row["trade_date"] > as_of:
                continue
            pct = row.get("pct_chg")
            returns.append(
                BoardReturn(
                    trade_date=row["trade_date"],  # type: ignore[arg-type]
                    board_code=code,
                    pct_chg=None if pct is None else Decimal(str(pct)),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                )
            )
    heat_by_day: dict[date, dict[str, float]] = {}
    heat_lookup: dict[tuple[date, str], float] = {}
    if returns:
        for row in compute_heat(returns, board_type="member"):
            if row.heat_short is None:
                continue
            value = float(row.heat_short)
            heat_by_day.setdefault(row.trade_date, {})[row.board_code] = value
            heat_lookup[(row.trade_date, row.board_code)] = value

    close_heat: dict[str, list[tuple[date, object, object, object]]] = {}
    for code, rows in bars_by_code.items():
        series: list[tuple[date, object, object, object]] = []
        for row in rows:
            day = row.get("trade_date")
            if not isinstance(day, date) or day > as_of or row.get("close") is None:
                continue
            series.append(
                (
                    day,
                    row["close"],
                    heat_lookup.get((day, code)),
                    None,
                )
            )
        close_heat[code] = series
    return heat_by_day, close_heat
