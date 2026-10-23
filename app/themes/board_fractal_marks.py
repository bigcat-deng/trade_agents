"""Price-fractal dots for the industry short-heat plane.

The fractals are the same raw tops and bottoms drawn on a board K-line:
avg smoothed by a trailing MA5, a 7-point extremum, then same-type repair.
Inserts, endpoints, and fractals removed by a merge are not marked.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import numpy as np

from app.charts.chan_board import WINDOW as CHAN_BARS
from scripts.chan_fractal_probe import (
    MA,
    WARMUP,
    alternate_fractals,
    find_fractals,
    _trailing_ma,
)

FRACTAL_STYLE = {
    "top": {"symbol": "circle", "color": "#dc2626", "name": "顶分型", "size": 8},
    "bottom": {"symbol": "circle", "color": "#111827", "name": "底分型", "size": 8},
}


def empty_fractal_mark_overlay() -> dict[str, object]:
    out: dict[str, object] = {}
    for key in FRACTAL_STYLE:
        out[f"{key}_x"] = []
        out[f"{key}_y"] = []
        out[f"{key}_text"] = []
        out[f"{key}_count"] = 0
    return out


def surviving_raw_fractals(
    bars: Sequence[Mapping[str, object]],
) -> list[tuple[date, str]]:
    """Raw top/bottom fractals that remain after same-type repair."""
    usable = [
        row
        for row in bars
        if row.get("trade_date") is not None
        and row.get("high") is not None
        and row.get("low") is not None
        and row.get("close") is not None
    ]
    if len(usable) < MA + 2:
        return []
    highs = np.array([float(row["high"]) for row in usable])
    lows = np.array([float(row["low"]) for row in usable])
    closes = np.array([float(row["close"]) for row in usable])
    smooth = _trailing_ma((highs + lows + closes) / 3.0, MA)
    repaired, _events = alternate_fractals(find_fractals(smooth, highs, lows), highs, lows)
    marks: list[tuple[date, str]] = []
    for item in repaired:
        if item.source != "raw" or item.kind not in FRACTAL_STYLE:
            continue
        trade_date = usable[item.index]["trade_date"]
        if isinstance(trade_date, date):
            marks.append((trade_date, item.kind))
    return marks


def build_fractal_mark_overlay(
    *,
    ordered_codes: list[str],
    window_dates: list[date],
    bars_by_code: dict[str, list[dict[str, object]]],
    names: dict[str, str] | None = None,
) -> dict[str, object]:
    """Scatter coords for raw fractals whose date falls inside ``window_dates``.

    Bars on or before the window end are used, including earlier warmup bars.
    """
    empty = empty_fractal_mark_overlay()
    if not ordered_codes or not window_dates:
        return empty
    window_set = set(window_dates)
    end = window_dates[-1]
    keep = CHAN_BARS + WARMUP
    code_x = {code: float(index) for index, code in enumerate(ordered_codes)}
    day_y = {day: float(index) for index, day in enumerate(window_dates)}
    name_map = names or {}
    buckets: dict[str, list[tuple[float, float, str]]] = {
        key: [] for key in FRACTAL_STYLE
    }
    for code in ordered_codes:
        rows = [
            row
            for row in (bars_by_code.get(code) or [])
            if isinstance(row.get("trade_date"), date) and row["trade_date"] <= end
        ][-keep:]
        label = name_map.get(code) or code
        x0 = code_x[code]
        for trade_date, kind in surviving_raw_fractals(rows):
            if trade_date not in window_set or kind not in buckets:
                continue
            kind_name = FRACTAL_STYLE[kind]["name"]
            buckets[kind].append(
                (x0, day_y[trade_date], f"{kind_name}<br>{label}<br>{trade_date.isoformat()}")
            )
    out = empty_fractal_mark_overlay()
    for key, points in buckets.items():
        out[f"{key}_x"] = [point[0] for point in points]
        out[f"{key}_y"] = [point[1] for point in points]
        out[f"{key}_text"] = [point[2] for point in points]
        out[f"{key}_count"] = len(points)
    return out
