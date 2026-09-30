"""Short-heat trajectory seriation helpers (hierarchical clustering leaf order)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage, optimal_leaf_ordering
from scipy.spatial.distance import pdist

from app.themes.badges import percentiles_from_heats

_MIN_POINTS = 8
_VAR_EPS = 1e-12


def as_float(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def fill_series(values: list[float | None]) -> list[float | None]:
    out = list(values)
    last: float | None = None
    for i, value in enumerate(out):
        if value is None:
            out[i] = last
        else:
            last = value
    last = None
    for i in range(len(out) - 1, -1, -1):
        if out[i] is None:
            out[i] = last
        else:
            last = out[i]
    return out


def hotness_series_by_code(
    *,
    window_dates: list[date],
    codes: list[str],
    heat_by_day: dict[date, dict[str, float]],
) -> dict[str, list[float | None]]:
    """Flipped cross-section percentile series (1 = hottest), gap-filled."""
    series = {code: [None] * len(window_dates) for code in codes}
    for day_i, day in enumerate(window_dates):
        heats = heat_by_day.get(day, {})
        pct = percentiles_from_heats(heats)
        for code in codes:
            if code in heats and code in pct:
                series[code][day_i] = 1.0 - float(pct[code])
    return {code: fill_series(values) for code, values in series.items()}


def order_by_trajectory_seriation(
    codes: list[str],
    series_by_code: dict[str, list[float | None]],
) -> list[str]:
    """Average-link hierarchical clustering + optimal leaf order on corr distance."""
    if len(codes) <= 2:
        return list(codes)

    usable: list[str] = []
    unused: list[str] = []
    rows: list[np.ndarray] = []
    for code in codes:
        raw = series_by_code.get(code) or []
        vals = [v for v in raw if v is not None]
        if len(vals) < _MIN_POINTS:
            unused.append(code)
            continue
        arr = np.asarray(
            [float(v) if v is not None else float(np.nanmean(vals)) for v in raw],
            dtype=float,
        )
        if float(np.nanvar(arr)) <= _VAR_EPS:
            unused.append(code)
            continue
        arr = (arr - float(np.mean(arr))) / float(np.std(arr))
        usable.append(code)
        rows.append(arr)

    if len(usable) <= 2:
        return usable + sorted(unused)

    matrix = np.vstack(rows)
    condensed = pdist(matrix, metric="correlation")
    condensed = np.nan_to_num(condensed, nan=1.0, posinf=1.0, neginf=1.0)
    condensed = np.clip(condensed, 0.0, 1.0)

    tree = linkage(condensed, method="average")
    ordered_tree = optimal_leaf_ordering(tree, condensed)
    leaf_order = leaves_list(ordered_tree)
    ordered = [usable[i] for i in leaf_order]

    left_level = float(
        np.nanmean(np.asarray(series_by_code[ordered[0]], dtype=float))
    )
    right_level = float(
        np.nanmean(np.asarray(series_by_code[ordered[-1]], dtype=float))
    )
    if right_level > left_level:
        ordered = list(reversed(ordered))

    return ordered + sorted(unused)


def hotness_grid(
    *,
    window_dates: list[date],
    ordered_codes: list[str],
    heat_by_day: dict[date, dict[str, float]],
) -> list[list[float | None]]:
    grid: list[list[float | None]] = []
    for day in window_dates:
        heats = heat_by_day.get(day, {})
        pct = percentiles_from_heats(heats)
        row: list[float | None] = []
        for code in ordered_codes:
            if code not in heats or code not in pct:
                row.append(None)
            else:
                row.append(1.0 - float(pct[code]))
        grid.append(row)
    return grid


def late_quarter_dates(window_dates: list[date]) -> list[date]:
    """Last quarter of the window (closer to current)."""
    if not window_dates:
        return []
    start_i = (len(window_dates) * 3) // 4
    return window_dates[start_i:]


def select_top_codes_by_late_short_heat(
    *,
    window_dates: list[date],
    heat_by_day: dict[date, dict[str, float]],
    candidate_codes: list[str],
    top_n: int,
) -> list[str]:
    """Pick top_n hottest codes by mean heat_short over the late quarter (lower=hotter)."""
    if top_n < 1 or not candidate_codes:
        return []
    late_days = late_quarter_dates(window_dates)
    if not late_days:
        late_days = window_dates[-1:]

    scored: list[tuple[float, str]] = []
    for code in candidate_codes:
        vals = [
            heat_by_day[day][code]
            for day in late_days
            if day in heat_by_day and code in heat_by_day[day]
        ]
        if not vals:
            continue
        scored.append((float(sum(vals) / len(vals)), code))

    scored.sort(key=lambda item: (item[0], item[1]))
    return [code for _score, code in scored[:top_n]]
