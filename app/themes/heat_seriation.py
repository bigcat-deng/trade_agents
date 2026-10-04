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
    return order_by_fused_seriation(
        codes,
        series_by_code,
        names=None,
        constituents=None,
        theme_ids_by_code=None,
        traj_weight=1.0,
    )


# Fused seriation: trajectory corr + constituent/name structure.
DEFAULT_TRAJ_WEIGHT = 0.65
DEFAULT_OVERLAP_IN_STRUCT = 0.75
_THEME_COMEMBER_BOOST = 0.12


def name_char_similarity(left: str, right: str) -> float:
    """Jaccard on character sets; light semantic prior for Chinese board names."""
    a = {ch for ch in (left or "").strip() if not ch.isspace()}
    b = {ch for ch in (right or "").strip() if not ch.isspace()}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def constituent_jaccard(left: set[str] | None, right: set[str] | None) -> float:
    a = left or set()
    b = right or set()
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def structural_similarity(
    *,
    left_code: str,
    right_code: str,
    names: dict[str, str] | None,
    constituents: dict[str, set[str]] | None,
    theme_ids_by_code: dict[str, set[str]] | None,
    overlap_weight: float = DEFAULT_OVERLAP_IN_STRUCT,
) -> float:
    """Blend constituent Jaccard + name similarity (+ small theme co-membership)."""
    overlap_w = min(1.0, max(0.0, float(overlap_weight)))
    jacc = constituent_jaccard(
        (constituents or {}).get(left_code),
        (constituents or {}).get(right_code),
    )
    name_s = name_char_similarity(
        (names or {}).get(left_code, left_code),
        (names or {}).get(right_code, right_code),
    )
    score = overlap_w * jacc + (1.0 - overlap_w) * name_s
    themes = theme_ids_by_code or {}
    left_t = themes.get(left_code) or set()
    right_t = themes.get(right_code) or set()
    if left_t and right_t and (left_t & right_t):
        score = min(1.0, score + _THEME_COMEMBER_BOOST)
    return float(min(1.0, max(0.0, score)))


def _trajectory_rows(
    codes: list[str],
    series_by_code: dict[str, list[float | None]],
) -> tuple[list[str], list[str], list[np.ndarray]]:
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
    return usable, unused, rows


def _condensed_traj_distance(rows: list[np.ndarray]) -> np.ndarray:
    matrix = np.vstack(rows)
    condensed = pdist(matrix, metric="correlation")
    condensed = np.nan_to_num(condensed, nan=1.0, posinf=1.0, neginf=1.0)
    return np.clip(condensed, 0.0, 1.0)


def _condensed_struct_distance(
    usable: list[str],
    *,
    names: dict[str, str] | None,
    constituents: dict[str, set[str]] | None,
    theme_ids_by_code: dict[str, set[str]] | None,
    overlap_weight: float,
) -> np.ndarray:
    n = len(usable)
    out = np.zeros(n * (n - 1) // 2, dtype=float)
    k = 0
    for i in range(n):
        for j in range(i + 1, n):
            sim = structural_similarity(
                left_code=usable[i],
                right_code=usable[j],
                names=names,
                constituents=constituents,
                theme_ids_by_code=theme_ids_by_code,
                overlap_weight=overlap_weight,
            )
            out[k] = 1.0 - sim
            k += 1
    return np.clip(out, 0.0, 1.0)


def order_by_fused_seriation(
    codes: list[str],
    series_by_code: dict[str, list[float | None]],
    *,
    names: dict[str, str] | None = None,
    constituents: dict[str, set[str]] | None = None,
    theme_ids_by_code: dict[str, set[str]] | None = None,
    traj_weight: float = DEFAULT_TRAJ_WEIGHT,
    overlap_in_struct: float = DEFAULT_OVERLAP_IN_STRUCT,
) -> list[str]:
    """Leaf-order clustering on fused trajectory + structural distances.

    ``traj_weight`` (α): weight on corr-distance; ``1-α`` on structure
    ``1 - (β·Jaccard + (1-β)·name[+theme])``.
    """
    if len(codes) <= 2:
        return list(codes)

    usable, unused, rows = _trajectory_rows(codes, series_by_code)
    if len(usable) <= 2:
        return usable + sorted(unused)

    alpha = min(1.0, max(0.0, float(traj_weight)))
    traj = _condensed_traj_distance(rows)
    if alpha >= 1.0 - 1e-12 or (
        not constituents and not names and not theme_ids_by_code
    ):
        condensed = traj
    else:
        struct = _condensed_struct_distance(
            usable,
            names=names,
            constituents=constituents,
            theme_ids_by_code=theme_ids_by_code,
            overlap_weight=overlap_in_struct,
        )
        condensed = np.clip(alpha * traj + (1.0 - alpha) * struct, 0.0, 1.0)

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


DEFAULT_PLANE_DENSIFY = 4


def _interp_row(values: list[float | None], densify: int) -> list[float | None]:
    if densify < 1 or len(values) < 2:
        return list(values)
    out: list[float | None] = []
    for i, left in enumerate(values[:-1]):
        right = values[i + 1]
        out.append(left)
        for step in range(1, densify):
            t = step / densify
            if left is None or right is None:
                out.append(None)
            else:
                out.append(left * (1.0 - t) + right * t)
    out.append(values[-1])
    return out


def _fill_time_gaps(grid: list[list[float | None]]) -> list[list[float | None]]:
    if not grid:
        return grid
    cols = len(grid[0])
    out = [list(row) for row in grid]
    for c in range(cols):
        last: float | None = None
        for r in range(len(out)):
            if out[r][c] is None:
                out[r][c] = last
            else:
                last = out[r][c]
        last = None
        for r in range(len(out) - 1, -1, -1):
            if out[r][c] is None:
                out[r][c] = last
            else:
                last = out[r][c]
    return out


def densify_hotness_plane(
    *,
    theme_x: list[float],
    z_short: list[list[float | None]],
    densify: int = DEFAULT_PLANE_DENSIFY,
) -> tuple[list[float], list[list[float | None]]]:
    """Linear-interpolate along the entity axis so adjacent cells form a continuous field.

    Board / concept / theme axes are approximate narratives; densify softens
    hard block boundaries without changing the frozen tick order.
    """
    steps = max(1, densify)
    dense_x: list[float] = []
    for i in range(len(theme_x) - 1):
        dense_x.append(theme_x[i])
        for step in range(1, steps):
            dense_x.append(theme_x[i] + step / steps)
    if theme_x:
        dense_x.append(theme_x[-1])
    dense_z = [_interp_row(row, steps) for row in z_short]
    return dense_x, _fill_time_gaps(dense_z)


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
