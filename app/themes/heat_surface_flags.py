"""Hard surface-plane flags for backtest filters (not LLM prose).

Derived from the same short-heat hotness grid as the theme-wave pages:
flipped cross-section percentile (1 = hottest) on the seriated roster.
"""

from __future__ import annotations

from typing import Any

import numpy as np

SURFACE_FLAG_KEYS = (
    "near_warming",
    "near_cooling",
    "crowded_top",
    "in_hot_cluster",
)

NEAR_K = 5
NEAR_SLOPE_EPS = 0.01  # hotness units / day; abs(slope) below → flat
CROWDED_CUT = 0.90  # as-of hotness ≥ this → crowded top
CLUSTER_RADIUS = 2  # leaf-order neighbors on each side
CLUSTER_HOT_CUT = 0.70  # late mean hotness to count as "hot"
CLUSTER_NEIGHBOR_FRAC = 0.50  # share of neighbors that must be hot
LATE_N = 5  # days for late mean used by cluster / levels


def compute_surface_flags(
    *,
    names: list[str],
    codes: list[str],
    z_short: list[list[float | None]] | np.ndarray,
    as_of: str | None = None,
    near_k: int = NEAR_K,
    near_slope_eps: float = NEAR_SLOPE_EPS,
    crowded_cut: float = CROWDED_CUT,
    cluster_radius: int = CLUSTER_RADIUS,
    cluster_hot_cut: float = CLUSTER_HOT_CUT,
    cluster_neighbor_frac: float = CLUSTER_NEIGHBOR_FRAC,
    late_n: int = LATE_N,
) -> list[dict[str, Any]]:
    """Per-board binary surface flags for the window's last day (`as_of`)."""
    z = np.asarray(z_short, dtype=float)
    if z.ndim != 2 or z.size == 0 or not codes:
        return []
    t0, n0 = z.shape
    if n0 != len(codes):
        raise ValueError("z_short width must match codes")
    late = max(1, min(late_n, t0))
    late_mean = np.nanmean(z[-late:, :], axis=0)
    asof = z[-1, :]

    slopes = np.asarray(
        [_hotness_slope(z[:, i], k=near_k) for i in range(n0)],
        dtype=float,
    )

    rows: list[dict[str, Any]] = []
    for i, code in enumerate(codes):
        slope = slopes[i]
        near_warming = bool(np.isfinite(slope) and slope > near_slope_eps)
        near_cooling = bool(np.isfinite(slope) and slope < -near_slope_eps)
        level = float(asof[i]) if np.isfinite(asof[i]) else float("nan")
        crowded_top = bool(np.isfinite(level) and level >= crowded_cut)
        in_hot_cluster = _in_hot_cluster(
            i,
            late_mean=late_mean,
            radius=cluster_radius,
            hot_cut=cluster_hot_cut,
            neighbor_frac=cluster_neighbor_frac,
        )
        rows.append(
            {
                "as_of": as_of,
                "board_code": code,
                "board_name": names[i] if i < len(names) else code,
                "near_warming": near_warming,
                "near_cooling": near_cooling,
                "crowded_top": crowded_top,
                "in_hot_cluster": in_hot_cluster,
                "hotness_asof": None if not np.isfinite(level) else round(level, 4),
                "hotness_late": (
                    None
                    if not np.isfinite(late_mean[i])
                    else round(float(late_mean[i]), 4)
                ),
                "near_slope": None if not np.isfinite(slope) else round(float(slope), 5),
            }
        )
    return rows


def _hotness_slope(series: np.ndarray, *, k: int) -> float:
    """OLS slope on last k hotness points; >0 means getting hotter."""
    if k < 2:
        return float("nan")
    window = series[-k:]
    xs: list[float] = []
    ys: list[float] = []
    for index, value in enumerate(window):
        if value is None or not np.isfinite(value):
            continue
        xs.append(float(index))
        ys.append(float(value))
    if len(xs) < max(3, k - 1):
        return float("nan")
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    denom = float(np.sum((x - x_mean) ** 2))
    if denom <= 0:
        return float("nan")
    return float(np.sum((x - x_mean) * (y - y_mean)) / denom)


def _in_hot_cluster(
    index: int,
    *,
    late_mean: np.ndarray,
    radius: int,
    hot_cut: float,
    neighbor_frac: float,
) -> bool:
    self_level = late_mean[index]
    if not np.isfinite(self_level) or self_level < hot_cut:
        return False
    n = len(late_mean)
    left = max(0, index - radius)
    right = min(n, index + radius + 1)
    neighbor_idx = [j for j in range(left, right) if j != index]
    if not neighbor_idx:
        return True
    hot_neighbors = sum(
        1
        for j in neighbor_idx
        if np.isfinite(late_mean[j]) and late_mean[j] >= hot_cut
    )
    return (hot_neighbors / len(neighbor_idx)) >= neighbor_frac


def attach_surface_flags(payload: dict[str, Any]) -> dict[str, Any]:
    """Add `surface_flags` onto an industry/concept heat-plane payload."""
    if payload.get("empty_message"):
        return {**payload, "surface_flags": []}
    flags = compute_surface_flags(
        names=list(payload.get("board_names") or []),
        codes=list(payload.get("board_codes") or []),
        z_short=payload.get("z_short") or [],
        as_of=payload.get("as_of"),
    )
    return {**payload, "surface_flags": flags}
