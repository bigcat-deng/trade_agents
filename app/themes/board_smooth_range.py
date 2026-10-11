"""Industry smooth-range plane: typical price → Kalman → 100d min-max."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from app.db import (
    fetch_board_bar_dates_ending,
    fetch_board_daily_bars_many,
    fetch_heat_dates_ending,
)
from app.themes.heat_forecast import tip_hottest_labels
from app.themes.heat_seriation import (
    DEFAULT_PLANE_DENSIFY,
    as_float,
    densify_hotness_plane,
)

SMOOTH_RANGE_NORM_DAYS = 100
SMOOTH_RANGE_MIN_PERIODS = 20
# 1-D random-walk Kalman defaults (stable, reproducible).
KALMAN_Q = 1e-5
KALMAN_R = 1e-3

SMOOTH_RANGE_METRICS = frozenset({"level", "return"})

SMOOTH_RANGE_AXIS_NOTE = (
    "横轴：与上方行业短热同一叶序；"
    "颜色为典型价 avg=(C+H+L)/3 经卡尔曼滤波后，"
    f"在近{SMOOTH_RANGE_NORM_DAYS}个交易日自身区间的 min-max 位置"
    "（越高=平滑价越靠近自身近窗上沿）；进深为时间；"
    "末日前方红字=截止日区间位置最高的行业名。"
)

SMOOTH_RETURN_AXIS_NOTE = (
    "横轴：与上方行业短热/平滑价位同一叶序；"
    "颜色为卡尔曼典型价的简单日收益"
    f"（r=k_t/k_{{t-1}}-1）在近{SMOOTH_RANGE_NORM_DAYS}个交易日自身区间的 min-max 位置"
    "（越高=收益相对自身近窗越高）；进深为时间；"
    "末日前方红字=截止日收益区间位置最高的行业名。"
)


def kalman_typical_overlay(
    bars: list[dict[str, object]],
    *,
    display_start: date | None = None,
    display_end: date | None = None,
    q: float = KALMAN_Q,
    r: float = KALMAN_R,
) -> dict[str, object] | None:
    """Build a price-axis overlay from Kalman-smoothed typical prices.

    Run filter on the full ``bars`` series (for warm-up), then keep points
    inside ``[display_start, display_end]`` when those bounds are set.
    """
    if not bars:
        return None
    ordered = sorted(
        (row for row in bars if isinstance(row.get("trade_date"), date)),
        key=lambda row: row["trade_date"],  # type: ignore[index]
    )
    avgs = [
        typical_price(row.get("high"), row.get("low"), row.get("close"))
        for row in ordered
    ]
    filtered = kalman_filter_1d(avgs, q=q, r=r)
    xs: list[str] = []
    ys: list[float | None] = []
    for row, val in zip(ordered, filtered):
        day = row["trade_date"]
        assert isinstance(day, date)
        if display_start is not None and day < display_start:
            continue
        if display_end is not None and day > display_end:
            continue
        xs.append(day.isoformat())
        ys.append(None if val is None else float(val))
    if not xs or all(v is None for v in ys):
        return None
    return {
        "name": "卡尔曼典型价",
        "x": xs,
        "y": ys,
        "color": "#7c3aed",
        "width": 1.8,
    }


def typical_price(high: object, low: object, close: object) -> float | None:
    h = as_float(high)
    lo = as_float(low)
    c = as_float(close)
    if h is None or lo is None or c is None:
        return None
    if h <= 0 or lo <= 0 or c <= 0:
        return None
    return (h + lo + c) / 3.0


def kalman_filter_1d(
    values: list[float | None],
    *,
    q: float = KALMAN_Q,
    r: float = KALMAN_R,
) -> list[float | None]:
    """Scalar random-walk Kalman; gaps stay None and do not update state."""
    out: list[float | None] = [None] * len(values)
    x: float | None = None
    p = 1.0
    qq = max(1e-12, float(q))
    rr = max(1e-12, float(r))
    for i, z in enumerate(values):
        if z is None or not np.isfinite(z):
            continue
        if x is None:
            x = float(z)
            p = 1.0
            out[i] = x
            continue
        p_pred = p + qq
        k = p_pred / (p_pred + rr)
        x = x + k * (float(z) - x)
        p = (1.0 - k) * p_pred
        out[i] = float(x)
    return out


def rolling_minmax_norm(
    values: list[float | None],
    *,
    window: int = SMOOTH_RANGE_NORM_DAYS,
    min_periods: int = SMOOTH_RANGE_MIN_PERIODS,
) -> list[float | None]:
    """Per-index min-max over the trailing ``window`` observations (incl. today)."""
    w = max(2, int(window))
    mp = max(2, min(int(min_periods), w))
    out: list[float | None] = [None] * len(values)
    for i, val in enumerate(values):
        if val is None or not np.isfinite(val):
            continue
        start = max(0, i - w + 1)
        tail = [
            float(v)
            for v in values[start : i + 1]
            if v is not None and np.isfinite(v)
        ]
        if len(tail) < mp:
            continue
        lo = min(tail)
        hi = max(tail)
        if hi - lo <= 1e-12:
            out[i] = 0.5
        else:
            out[i] = (float(val) - lo) / (hi - lo)
    return out


def simple_returns(values: list[float | None]) -> list[float | None]:
    """Simple returns r_t = x_t / x_{t-1} - 1; gaps / non-positive prev → None."""
    out: list[float | None] = [None] * len(values)
    prev: float | None = None
    for i, val in enumerate(values):
        if val is None or not np.isfinite(val):
            prev = None
            continue
        cur = float(val)
        if prev is not None and prev > 0:
            out[i] = cur / prev - 1.0
        prev = cur
    return out


def _series_on_calendar(
    bars: list[dict[str, object]],
    calendar: list[date],
) -> list[float | None]:
    by_day = {
        row["trade_date"]: typical_price(row.get("high"), row.get("low"), row.get("close"))
        for row in bars
        if isinstance(row.get("trade_date"), date)
    }
    return [by_day.get(day) for day in calendar]


def build_industry_smooth_range_plane(
    *,
    window_dates: list[date],
    history_dates: list[date],
    ordered_codes: list[str],
    names: dict[str, str] | list[str] | None = None,
    bars_by_code: dict[str, list[dict[str, object]]],
    densify: int = DEFAULT_PLANE_DENSIFY,
    norm_days: int = SMOOTH_RANGE_NORM_DAYS,
    kalman_q: float = KALMAN_Q,
    kalman_r: float = KALMAN_R,
    metric: str = "level",
) -> dict[str, Any]:
    """Grid of Kalman level or Kalman simple-return, each 100d self min-max."""
    metric_key = str(metric or "level").strip().lower()
    if metric_key not in SMOOTH_RANGE_METRICS:
        metric_key = "level"
    axis_note = (
        SMOOTH_RETURN_AXIS_NOTE if metric_key == "return" else SMOOTH_RANGE_AXIS_NOTE
    )
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
        "board_count": 0,
        "densify": densify,
        "metric": metric_key,
        "tip_labels": {"x": [], "y": [], "text": [], "color": "#dc2626"},
        "empty_message": (
            "没有可绘制的行业平滑收益窗口"
            if metric_key == "return"
            else "没有可绘制的行业平滑价位窗口"
        ),
    }
    if not window_dates or not ordered_codes or not history_dates:
        return empty

    name_map: dict[str, str] = {}
    if isinstance(names, dict):
        name_map = {str(k): str(v) for k, v in names.items()}
    elif isinstance(names, list):
        for i, code in enumerate(ordered_codes):
            if i < len(names) and names[i]:
                name_map[code] = str(names[i])

    win_set = set(window_dates)
    win_index = {day: i for i, day in enumerate(window_dates)}
    z_native: list[list[float | None]] = [
        [None] * len(ordered_codes) for _ in window_dates
    ]

    for col, code in enumerate(ordered_codes):
        avg = _series_on_calendar(bars_by_code.get(code) or [], history_dates)
        filtered = kalman_filter_1d(avg, q=kalman_q, r=kalman_r)
        series = (
            simple_returns(filtered) if metric_key == "return" else filtered
        )
        normed = rolling_minmax_norm(
            series, window=norm_days, min_periods=SMOOTH_RANGE_MIN_PERIODS
        )
        for day, val in zip(history_dates, normed):
            if day not in win_set or val is None:
                continue
            z_native[win_index[day]][col] = float(val)
        name_map.setdefault(code, code)

    labels = [name_map.get(c, c) for c in ordered_codes]
    theme_x = [float(i) for i in range(len(ordered_codes))]
    dense_x, dense_z = densify_hotness_plane(
        theme_x=theme_x, z_short=z_native, densify=densify
    )
    tip_labels = tip_hottest_labels(
        ordered_codes=ordered_codes,
        names=labels,
        z_native=z_native,
        n_dates=len(window_dates),
        top_n=5,
    )
    return {
        "dates": [d.isoformat() for d in window_dates],
        "board_codes": list(ordered_codes),
        "board_names": labels,
        "x": dense_x,
        "x_tickvals": theme_x,
        "x_ticktext": labels,
        "z_short": dense_z,
        "z_boards": z_native,
        "axis_note": axis_note,
        "as_of": window_dates[-1].isoformat(),
        "board_count": len(ordered_codes),
        "densify": densify,
        "metric": metric_key,
        "tip_labels": tip_labels,
        "empty_message": None,
    }


def build_industry_smooth_range_panel_payload(
    *,
    as_of: date | None,
    days: int = 40,
    ordered_codes: list[str] | None = None,
    names: list[str] | None = None,
    metric: str = "level",
    include_plotlyjs: bool = False,
    height: int = 520,
) -> dict[str, Any]:
    """JSON panel for theme-wave lazy embed (level or return metric)."""
    from app.charts.theme_wave import render_theme_wave_contour

    metric_key = str(metric or "level").strip().lower()
    if metric_key not in SMOOTH_RANGE_METRICS:
        metric_key = "level"
    default_note = (
        SMOOTH_RETURN_AXIS_NOTE if metric_key == "return" else SMOOTH_RANGE_AXIS_NOTE
    )
    requested = as_of or date.today()
    frozen = [str(c) for c in (ordered_codes or []) if c]
    out: dict[str, Any] = {
        "as_of": None,
        "requested_as_of": requested.isoformat(),
        "days": days,
        "window_start": None,
        "window_end": None,
        "note": default_note,
        "html": "",
        "error": None,
        "heat_aligned": bool(frozen),
        "board_codes": frozen,
        "metric": metric_key,
    }
    tip_days = fetch_heat_dates_ending("industry", requested, 1)
    if not tip_days:
        tip_days = fetch_board_bar_dates_ending("industry", requested, 1)
    if not tip_days:
        out["error"] = "没有可用的行业截止日。"
        return out
    tip = tip_days[-1]
    window = fetch_heat_dates_ending("industry", tip, days)
    if len(window) < 5:
        window = fetch_board_bar_dates_ending("industry", tip, days)
    if len(window) < 5:
        out["error"] = "行业历史不足，无法绘制平滑图。"
        return out
    if not frozen:
        out["error"] = "需要热度叶序 codes 才能与上方行业图对齐。"
        return out

    need = len(window) + SMOOTH_RANGE_NORM_DAYS + 20
    history = fetch_heat_dates_ending("industry", tip, need)
    if len(history) < SMOOTH_RANGE_MIN_PERIODS + 5:
        history = fetch_board_bar_dates_ending("industry", tip, need)
    if not history:
        history = list(window)
    # Ensure window days present.
    history = sorted(set(history) | set(window))

    bars = fetch_board_daily_bars_many("industry", frozen, history[0], tip)
    name_list = list(names or [])
    name_map = {
        code: (name_list[i] if i < len(name_list) and name_list[i] else code)
        for i, code in enumerate(frozen)
    }
    plane = build_industry_smooth_range_plane(
        window_dates=window,
        history_dates=history,
        ordered_codes=frozen,
        names=name_map,
        bars_by_code=bars,
        metric=metric_key,
    )
    if plane.get("empty_message"):
        out["error"] = str(plane["empty_message"])
        return out
    out["as_of"] = tip.isoformat()
    out["window_start"] = window[0].isoformat()
    out["window_end"] = window[-1].isoformat()
    out["note"] = str(plane.get("axis_note") or default_note)
    out["board_codes"] = list(plane.get("board_codes") or frozen)
    if metric_key == "return":
        title = "行业平滑收益 · 卡尔曼日收益 + 100日区间"
    else:
        title = "行业平滑价位 · 卡尔曼 + 100日区间"
    out["html"] = render_theme_wave_contour(
        dates=plane["dates"],
        x=plane["x"],
        z=plane["z_short"],
        x_tickvals=plane["x_tickvals"],
        x_ticktext=plane["x_ticktext"],
        include_plotlyjs=include_plotlyjs,
        height=height,
        title=title,
        xaxis_title="行业（与热度叶序对齐）",
        entity_label="行业",
        tickangle=-45,
        tip_labels=plane.get("tip_labels"),
        show_colorbar=False,
    )
    return out
