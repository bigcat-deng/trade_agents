"""Near-term industry heat-plane forecast (structure scenario, not a price call).

Uses ~200 trading days of short-heat, freezes tip leaf order, extrapolates
each board's raw heat_short with a damped near-end slope, then re-ranks the
cross-section each forecast day. Display = recent actual context + forecast.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np

from app.themes.heat_seriation import (
    DEFAULT_PLANE_DENSIFY,
    densify_hotness_plane,
    hotness_grid,
    hotness_series_by_code,
    order_by_trajectory_seriation,
)
FORECAST_HISTORY_DAYS = 200
FORECAST_DAYS = 5
FORECAST_CONTEXT_DAYS = 40
FORECAST_TREND_LOOKBACK = 12
FORECAST_SLOPE_DAMP = 0.85
FORECAST_SERIATION_WINDOW = 40

FORECAST_AXIS_NOTE = (
    "横轴叶序锁定为截止日轨迹聚类顺序（推演窗内不重排）；"
    "近端实盘短热 + 未来交易日推演色场；"
    "推演=各板块近端斜率阻尼外推后再做当日截面分位，属结构情景，不是点预测。"
)


def synthesize_trading_days(after: date, n: int) -> list[date]:
    """Weekday placeholders when the DB calendar has no forward dates yet."""
    out: list[date] = []
    day = after
    while len(out) < max(0, int(n)):
        day += timedelta(days=1)
        if day.weekday() < 5:
            out.append(day)
    return out


def resolve_forecast_dates(
    *,
    as_of: date,
    n: int,
    known_forward: list[date] | None = None,
) -> list[date]:
    need = max(1, int(n))
    fwd = [d for d in (known_forward or []) if d > as_of][:need]
    if len(fwd) >= need:
        return fwd[:need]
    start = fwd[-1] if fwd else as_of
    return fwd + synthesize_trading_days(start, need - len(fwd))


def extrapolate_series(
    values: list[float],
    *,
    horizon: int,
    lookback: int = FORECAST_TREND_LOOKBACK,
    damp: float = FORECAST_SLOPE_DAMP,
) -> list[float]:
    """Damped linear continuation of the near-end raw heat series."""
    if horizon < 1:
        return []
    clean = [float(v) for v in values if v is not None and np.isfinite(v)]
    if not clean:
        return [0.0] * horizon
    lb = max(2, min(int(lookback), len(clean)))
    tail = clean[-lb:]
    last = float(tail[-1])
    if len(tail) < 2:
        return [last] * horizon
    xs = np.arange(len(tail), dtype=float)
    slope, intercept = np.polyfit(xs, np.asarray(tail, dtype=float), 1)
    out: list[float] = []
    damp_f = float(damp)
    for h in range(1, horizon + 1):
        raw = float(intercept + slope * (len(tail) - 1 + h))
        pred = last + (raw - last) * (damp_f**h)
        out.append(pred)
    return out


def build_industry_heat_forecast_payload(
    *,
    as_of: date,
    history_dates: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
    forecast_dates: list[date],
    ordered_codes: list[str] | None = None,
    context_days: int = FORECAST_CONTEXT_DAYS,
    trend_lookback: int = FORECAST_TREND_LOOKBACK,
    densify: int = DEFAULT_PLANE_DENSIFY,
    seriation_window: int = FORECAST_SERIATION_WINDOW,
) -> dict[str, Any]:
    """Build densified plane: recent actual heat + forecast days."""
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": FORECAST_AXIS_NOTE,
        "as_of": as_of.isoformat(),
        "forecast_dates": [],
        "context_dates": [],
        "board_count": 0,
        "scenario_note": "",
        "empty_message": "没有可推演的行业热度历史",
    }
    hist = [d for d in history_dates if d <= as_of]
    if not hist or not forecast_dates:
        return empty

    codes = sorted(
        {
            code
            for day in hist
            for code in (heat_by_day.get(day) or {})
        }
    )
    if not codes:
        return empty

    tip_n = max(8, min(int(seriation_window), len(hist)))
    tip_window = hist[-tip_n:]
    if ordered_codes:
        ordered = [c for c in ordered_codes if c in set(codes)]
        ordered += [c for c in codes if c not in set(ordered)]
    else:
        series = hotness_series_by_code(
            window_dates=tip_window, codes=codes, heat_by_day=heat_by_day
        )
        ordered = order_by_trajectory_seriation(codes, series)

    labels = [names.get(code, code) for code in ordered]
    ctx_n = max(5, min(int(context_days), len(hist)))
    context = hist[-ctx_n:]
    horizon = len(forecast_dates)

    # Extrapolate raw heat_short per code, then cross-section rank each day.
    forecast_heat: dict[date, dict[str, float]] = {}
    for code in ordered:
        series_raw = [
            heat_by_day[day][code]
            for day in hist
            if code in (heat_by_day.get(day) or {})
        ]
        preds = extrapolate_series(
            series_raw, horizon=horizon, lookback=trend_lookback
        )
        for day, val in zip(forecast_dates, preds):
            forecast_heat.setdefault(day, {})[code] = float(val)

    # Predicted raw heat_short (same scale as history); hotness_grid
    # re-does cross-section percentile flip per day.
    combined_heat = dict(heat_by_day)
    combined_heat.update(forecast_heat)
    display_dates = list(context) + list(forecast_dates)
    z_native = hotness_grid(
        window_dates=display_dates,
        ordered_codes=ordered,
        heat_by_day=combined_heat,
    )
    x_ticks = list(range(len(ordered)))
    dense_x, dense_z = densify_hotness_plane(
        theme_x=[float(i) for i in x_ticks],
        z_short=z_native,
        densify=densify,
    )
    scenario = _scenario_note(
        as_of=as_of,
        forecast_dates=forecast_dates,
        ordered=ordered,
        names=labels,
        z_native=z_native,
        context_len=len(context),
    )
    return {
        "dates": [d.isoformat() for d in display_dates],
        "board_codes": ordered,
        "board_names": labels,
        "x": dense_x,
        "x_tickvals": [float(i) for i in x_ticks],
        "x_ticktext": labels,
        "z_short": dense_z,
        "z_boards": z_native,
        "axis_note": FORECAST_AXIS_NOTE,
        "as_of": as_of.isoformat(),
        "forecast_dates": [d.isoformat() for d in forecast_dates],
        "context_dates": [d.isoformat() for d in context],
        "board_count": len(ordered),
        "scenario_note": scenario,
        "empty_message": None,
        "densify": densify,
    }


def _scenario_note(
    *,
    as_of: date,
    forecast_dates: list[date],
    ordered: list[str],
    names: list[str],
    z_native: list[list[float | None]],
    context_len: int,
) -> str:
    """One-line structure read: who stays hottest into the forecast tip."""
    if not forecast_dates or not z_native or not ordered:
        return ""
    tip_row = z_native[-1]
    scored: list[tuple[float, str]] = []
    for i, code in enumerate(ordered):
        if i >= len(tip_row):
            break
        val = tip_row[i]
        if val is None or not np.isfinite(val):
            continue
        scored.append((float(val), names[i] if i < len(names) else code))
    scored.sort(reverse=True)
    top = "、".join(name for _, name in scored[:5]) or "—"
    # Compare tip context (last actual) vs last forecast mean of top names.
    last_actual_i = context_len - 1
    shift = ""
    if last_actual_i >= 0 and len(z_native) > last_actual_i:
        actual_row = z_native[last_actual_i]
        actual_scored = sorted(
            (
                (float(actual_row[i]), names[i] if i < len(names) else ordered[i])
                for i in range(min(len(ordered), len(actual_row)))
                if actual_row[i] is not None and np.isfinite(actual_row[i])
            ),
            reverse=True,
        )
        actual_top = {name for _, name in actual_scored[:5]}
        forecast_top = {name for _, name in scored[:5]}
        gained = [n for n in forecast_top if n not in actual_top]
        lost = [n for n in actual_top if n not in forecast_top]
        bits = []
        if gained:
            bits.append("推演升温：" + "、".join(gained[:3]))
        if lost:
            bits.append("推演降温：" + "、".join(lost[:3]))
        if bits:
            shift = "；" + "；".join(bits)
    tip = forecast_dates[-1].isoformat()
    return (
        f"截止 {as_of.isoformat()} 起推至 {tip}；"
        f"推演末日相对最热：{top}{shift}。"
    )
