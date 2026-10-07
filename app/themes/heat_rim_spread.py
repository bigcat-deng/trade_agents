"""Near-end expanding-bright patches on a seriated short-heat grid.

Paint-only contour interpolation is ignored: detection uses native columns.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

RIM_DAYS = 6
SLOPE_DAYS = 5
SLOPE_EPS = 0.01
LIFT_EPS = 0.02
HEAT_FLOOR = 0.40
BRIGHTEN_EPS = 0.015
TOP_N = 5

_SCORE_IN = 20
_SCORE_HEAT = 25
_SCORE_SLOPE = 15
_SCORE_EXPAND = 15
_SCORE_CORE = 5
_SCORE_MACD = 25

RIM_NOTE = (
    "近端最上沿：刚亮、铺开、加亮的连通段；同分列近端有 MACD 上穿另加分，"
    "上穿越靠近最上沿加分越多。只列总分最高的 5 个标的。"
)


def macd_up_by_code_from_overlay(
    *,
    codes: list[str],
    dates: list[date],
    overlay: dict[str, object] | None,
) -> dict[str, list[date]]:
    """Map overlay cell centers back to board codes and window dates."""
    if not codes or not dates or not overlay:
        return {}
    xs = list(overlay.get("macd_up_x") or [])
    ys = list(overlay.get("macd_up_y") or [])
    out: dict[str, list[date]] = {}
    for x, y in zip(xs, ys):
        try:
            col = int(round(float(x)))
            row = int(round(float(y)))
        except (TypeError, ValueError):
            continue
        if col < 0 or col >= len(codes) or row < 0 or row >= len(dates):
            continue
        code = codes[col]
        day = dates[row]
        bucket = out.setdefault(code, [])
        if day not in bucket:
            bucket.append(day)
    return out


def list_heat_rim_patches(
    *,
    dates: list[date],
    codes: list[str],
    names: list[str],
    z: list[list[float | None]] | np.ndarray,
    rim_days: int = RIM_DAYS,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Near-end connected bright runs.

    By default only expanding or brightening runs. ``include_inactive`` keeps
    stale bright runs (still lit, no longer spreading) for exit matching.
    """
    empty: dict[str, Any] = {"as_of": None, "t0": None, "t_end": None, "patches": []}
    if not dates or not codes or z is None:
        return empty
    grid = np.asarray(z, dtype=float)
    if grid.ndim != 2 or grid.size == 0:
        return empty
    n_t, n_c = grid.shape
    if n_c != len(codes) or n_t != len(dates):
        return empty
    finite_rows = np.isfinite(grid).any(axis=1)
    if not bool(finite_rows.any()):
        return empty
    t_end = int(np.max(np.flatnonzero(finite_rows)))
    n_t_eff = t_end + 1
    rim = max(2, min(int(rim_days), n_t_eff))
    t0 = n_t_eff - rim
    last_mask = _bright_mask(grid, t_end, rim_days=rim)
    start_mask = _bright_mask(grid, t0, rim_days=rim)
    patches: list[dict[str, Any]] = []
    for patch_i, (lo, hi) in enumerate(_true_runs(last_mask)):
        width_now = hi - lo
        width_then = int(np.count_nonzero(start_mask[lo:hi]))
        expanding = width_now > width_then
        mean_now = _nanmean(grid[t_end, lo:hi])
        mean_then = _nanmean(grid[t0, lo:hi])
        brightening = (
            np.isfinite(mean_now)
            and np.isfinite(mean_then)
            and mean_now > mean_then + BRIGHTEN_EPS
        )
        if not expanding and not brightening and not include_inactive:
            continue
        members: list[dict[str, Any]] = []
        for i in range(lo, hi):
            asof = grid[t_end, i]
            if not np.isfinite(asof):
                continue
            slope = _ols_slope(grid[max(0, t_end - SLOPE_DAYS + 1) : t_end + 1, i])
            name = names[i] if i < len(names) else codes[i]
            members.append(
                {
                    "board_code": codes[i],
                    "board_name": name,
                    "col": i,
                    "role": "核" if bool(start_mask[i]) else "边",
                    "hotness_asof": round(float(asof), 3),
                    "near_slope": None
                    if not np.isfinite(slope)
                    else round(float(slope), 4),
                }
            )
        if not members:
            continue
        left_name = names[lo] if lo < len(names) else codes[lo]
        right_name = names[hi - 1] if hi - 1 < len(names) else codes[hi - 1]
        patches.append(
            {
                "patch_i": patch_i,
                "lo": lo,
                "hi": hi,
                "width_now": width_now,
                "width_then": width_then,
                "expanding": expanding,
                "brightening": brightening,
                "active": bool(expanding or brightening),
                "mean_heat": None if not np.isfinite(mean_now) else round(float(mean_now), 3),
                "label": f"{left_name} → {right_name}",
                "members": members,
            }
        )
    empty["as_of"] = dates[t_end].isoformat()
    empty["t0"] = dates[t0].isoformat()
    empty["t_end"] = dates[t_end].isoformat()
    empty["patches"] = patches
    return empty


def rank_heat_rim_spread(
    *,
    dates: list[date],
    codes: list[str],
    names: list[str],
    z: list[list[float | None]] | np.ndarray,
    macd_up_by_code: dict[str, list[date]] | None = None,
    top_n: int = TOP_N,
    rim_days: int = RIM_DAYS,
) -> dict[str, Any]:
    """Return top-n scored names in near-end expanding bright runs."""
    empty = {
        "as_of": None,
        "note": RIM_NOTE,
        "rows": [],
    }
    listed = list_heat_rim_patches(
        dates=dates, codes=codes, names=names, z=z, rim_days=rim_days
    )
    as_of = listed.get("as_of")
    empty["as_of"] = as_of
    patches = list(listed.get("patches") or [])
    t0_iso = listed.get("t0")
    if not dates or not patches or as_of is None or t0_iso is None:
        return empty
    try:
        t_end = dates.index(date.fromisoformat(str(as_of)))
        t0 = dates.index(date.fromisoformat(str(t0_iso)))
    except ValueError:
        return empty
    macd = macd_up_by_code or {}
    near_list = list(dates[t0 : t_end + 1])
    near_dates = set(near_list)

    scored: list[dict[str, Any]] = []
    for patch in patches:
        expanding = bool(patch["expanding"])
        width_now = int(patch["width_now"])
        width_then = int(patch["width_then"])
        label = str(patch["label"])
        for member in patch["members"]:
            code = str(member["board_code"])
            slope = member.get("near_slope")
            slope_f = float("nan") if slope is None else float(slope)
            is_core = member["role"] == "核"
            macd_days = [
                day for day in (macd.get(code) or []) if day in near_dates
            ]
            macd_weight = _macd_recency_weight(macd_days, near_list)
            scored.append(
                {
                    "board_code": code,
                    "board_name": member["board_name"],
                    "score": _score(
                        asof=float(member["hotness_asof"]),
                        slope=slope_f,
                        expanding=expanding,
                        width_delta=width_now - width_then,
                        is_core=is_core,
                        macd_weight=macd_weight,
                    ),
                    "hotness_asof": member["hotness_asof"],
                    "near_slope": member["near_slope"],
                    "role": member["role"],
                    "expanding": expanding,
                    "brightening": bool(patch["brightening"]),
                    "width_now": width_now,
                    "width_then": width_then,
                    "macd_up": bool(macd_days),
                    "macd_up_dates": [day.isoformat() for day in sorted(macd_days)],
                    "macd_weight": round(macd_weight, 4),
                    "patch": label,
                }
            )

    scored.sort(
        key=lambda row: (
            -int(row["score"]),
            -float(row.get("macd_weight") or 0.0),
            -(row["near_slope"] or 0.0),
            -float(row["hotness_asof"]),
            str(row["board_code"]),
        )
    )
    limit = max(1, int(top_n))
    rows = []
    for rank, row in enumerate(scored[:limit], start=1):
        rows.append({**row, "rank": rank, "rim_label": _rim_label(row)})
    empty["rows"] = rows
    return empty


def _rim_label(row: dict[str, Any]) -> str:
    parts: list[str] = []
    if row.get("brightening"):
        parts.append("加亮")
    if row.get("expanding"):
        parts.append(f"扩开{row.get('width_then')}→{row.get('width_now')}")
    role = row.get("role")
    if role:
        parts.append(role)
    return " · ".join(parts) if parts else "—"


def _macd_recency_weight(macd_days: list[date], near_list: list[date]) -> float:
    """1.0 = 上穿在近端最后一天；窗口最早一天接近 0。"""
    if not macd_days or not near_list:
        return 0.0
    latest = max(macd_days)
    try:
        idx = near_list.index(latest)
    except ValueError:
        return 0.0
    span = len(near_list) - 1
    if span <= 0:
        return 1.0
    return idx / span


def _score(
    *,
    asof: float,
    slope: float,
    expanding: bool,
    width_delta: int,
    is_core: bool,
    macd_weight: float,
) -> int:
    heat = max(0.0, min(1.0, (asof - HEAT_FLOOR) / max(1e-6, 1.0 - HEAT_FLOOR)))
    slope_part = 0.0
    if np.isfinite(slope) and slope > 0:
        slope_part = min(1.0, float(slope) / 0.05)
    expand_part = 0.0
    if expanding:
        expand_part = min(1.0, max(0, width_delta) / 4.0)
    macd_part = max(0.0, min(1.0, float(macd_weight)))
    total = (
        _SCORE_IN
        + _SCORE_HEAT * heat
        + _SCORE_SLOPE * slope_part
        + _SCORE_EXPAND * expand_part
        + (_SCORE_CORE if is_core else 0)
        + _SCORE_MACD * macd_part
    )
    return int(round(min(100.0, total)))


def _bright_mask(z: np.ndarray, t: int, *, rim_days: int) -> np.ndarray:
    n_t, n_c = z.shape
    mask = np.zeros(n_c, dtype=bool)
    if t < 1 or t >= n_t:
        return mask
    t_prev0 = max(0, t - rim_days + 1)
    slope_from = max(0, t - SLOPE_DAYS + 1)
    for i in range(n_c):
        asof = z[t, i]
        if not np.isfinite(asof) or asof < HEAT_FLOOR:
            continue
        slope = _ols_slope(z[slope_from : t + 1, i])
        if not np.isfinite(slope) or slope <= SLOPE_EPS:
            continue
        prev = z[t_prev0:t, i]
        finite = prev[np.isfinite(prev)]
        if finite.size == 0:
            continue
        if asof > float(np.median(finite)) + LIFT_EPS:
            mask[i] = True
    return mask


def _true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    n = int(mask.size)
    i = 0
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i + 1
        while j < n and mask[j]:
            j += 1
        runs.append((i, j))
        i = j
    return runs


def _ols_slope(series: np.ndarray) -> float:
    xs: list[float] = []
    ys: list[float] = []
    for index, value in enumerate(series):
        if value is None or not np.isfinite(value):
            continue
        xs.append(float(index))
        ys.append(float(value))
    if len(xs) < 3:
        return float("nan")
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    denom = float(np.sum((x - x_mean) ** 2))
    if denom <= 0:
        return float("nan")
    return float(np.sum((x - x_mean) * (y - y_mean)) / denom)


def _nanmean(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return float("nan")
    return float(finite.mean())
