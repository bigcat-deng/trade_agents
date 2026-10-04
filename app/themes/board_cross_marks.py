"""MACD / short-long heat cross markers for industry & concept heat planes."""

from __future__ import annotations

from datetime import date

# Warm-up for MACD(12,26,9); matches interpret/cross_stats.
CROSS_HISTORY_DAYS = 120

# Plotly marker styles: × = MACD, ◆ = heat; color by direction.
CROSS_STYLE = {
    "macd_up": {"symbol": "x", "color": "#ea580c", "name": "MACD上穿", "size": 8},
    "macd_down": {"symbol": "x", "color": "#2563eb", "name": "MACD下穿", "size": 8},
    "heat_up": {"symbol": "diamond", "color": "#ea580c", "name": "热度上穿", "size": 7},
    "heat_down": {
        "symbol": "diamond",
        "color": "#2563eb",
        "name": "热度下穿",
        "size": 7,
    },
}

# Slight column offset so MACD × and heat ◆ on the same day stay readable.
_X_OFFSET = {
    "macd_up": -0.12,
    "macd_down": -0.12,
    "heat_up": 0.12,
    "heat_down": 0.12,
}


def empty_cross_mark_overlay() -> dict[str, object]:
    out: dict[str, object] = {}
    for key in CROSS_STYLE:
        out[f"{key}_x"] = []
        out[f"{key}_y"] = []
        out[f"{key}_text"] = []
        out[f"{key}_count"] = 0
    return out


def build_cross_mark_overlay(
    *,
    ordered_codes: list[str],
    window_dates: list[date],
    close_heat_by_code: dict[str, list[tuple[date, object, object, object]]],
    names: dict[str, str] | None = None,
) -> dict[str, object]:
    """Scatter coords for MACD/heat crosses that fall inside ``window_dates``."""
    # Lazy import: cross_stats → concept/industry_wave → this module.
    from app.interpret.cross_stats import list_cross_event_dates

    empty = empty_cross_mark_overlay()
    if not ordered_codes or not window_dates:
        return empty
    window_set = set(window_dates)
    code_x = {code: float(i) for i, code in enumerate(ordered_codes)}
    day_y = {day: float(i) for i, day in enumerate(window_dates)}
    name_map = names or {}

    buckets: dict[str, list[tuple[float, float, str]]] = {
        key: [] for key in CROSS_STYLE
    }
    for code in ordered_codes:
        rows = close_heat_by_code.get(code) or []
        if not rows:
            continue
        events = list_cross_event_dates(rows)
        label = name_map.get(code) or code
        x0 = code_x[code]
        for key, days in events.items():
            if key not in buckets:
                continue
            dx = _X_OFFSET[key]
            for day in days:
                if day not in window_set:
                    continue
                buckets[key].append((x0 + dx, day_y[day], f"{label}<br>{day.isoformat()}"))

    out = empty_cross_mark_overlay()
    for key, points in buckets.items():
        out[f"{key}_x"] = [p[0] for p in points]
        out[f"{key}_y"] = [p[1] for p in points]
        out[f"{key}_text"] = [p[2] for p in points]
        out[f"{key}_count"] = len(points)
    return out
