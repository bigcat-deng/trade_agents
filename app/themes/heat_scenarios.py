"""Theme-wave scenario tags: 萌芽 / 中位 / 久热 + near-end slope.

Rules match the Mon→Fri reading backtest discussion:
classify by trailing group-A hotness level/duration/slope on the spectrum
surface (1 = hottest). Tags are attention scenarios, not trade triggers.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.themes.heat_surface_flags import NEAR_K, NEAR_SLOPE_EPS, _hotness_slope

TRAIL_DAYS = 20
BUD_LEVEL_MIN = 0.35
BUD_LEVEL_MAX = 0.70
BUD_EARLY_MAX = 0.55
MID_LEVEL_MIN = 0.55
MID_LEVEL_MAX = 0.85
MID_SLOPE_FLOOR = -0.03
CROWDED_LEVEL = 0.90
CROWDED_HIGH = 0.80
CROWDED_DAYS = 8

SCENARIO_ORDER = ("萌芽", "中位", "久热")

SCENARIO_HINTS = {
    "萌芽": "观察；近端续热再加重",
    "中位": "降预期；近端抬升才可跟",
    "久热": "降权新仓；转冷坐实再撤离",
}

SLOPE_LABELS = {
    "up": "抬升",
    "flat": "走平",
    "down": "回落",
}

SCENARIO_NOTE = (
    "情景按截止日群 A 光谱热度自动标注：跟过程不跟色块高度；"
    "周一立假说 → 周中看续热 → 周末复盘；"
    "周一只分情景，是否加重看近端斜率是否续演。"
)


def slope_bucket(slope: float | None) -> str:
    if slope is None or not np.isfinite(slope):
        return "flat"
    if slope > NEAR_SLOPE_EPS:
        return "up"
    if slope < -NEAR_SLOPE_EPS:
        return "down"
    return "flat"


def classify_hotness_scenario(
    series: np.ndarray,
    *,
    trail: int = TRAIL_DAYS,
    near_k: int = NEAR_K,
) -> tuple[str | None, float | None, float | None]:
    """Return (scenario, hotness_asof, near_slope) for one theme series."""
    if series.size == 0:
        return None, None, None
    window = series[-max(1, min(trail, series.size)) :]
    level = float(window[-1]) if np.isfinite(window[-1]) else float("nan")
    if not np.isfinite(level):
        return None, None, None
    slope = _hotness_slope(window, k=near_k)
    slope_v = float(slope) if np.isfinite(slope) else None
    high_days = int(np.sum(np.isfinite(window) & (window >= CROWDED_HIGH)))
    early = window[: max(1, len(window) // 2)]
    early_mean = (
        float(np.nanmean(early)) if np.any(np.isfinite(early)) else float("nan")
    )

    scenario: str | None = None
    late5 = (
        float(np.nanmean(window[-5:]))
        if np.any(np.isfinite(window[-5:]))
        else float("nan")
    )
    crowded_long = level >= CROWDED_LEVEL and high_days >= min(
        CROWDED_DAYS, len(window)
    )
    crowded_plateau = (
        level >= 0.95
        and np.isfinite(late5)
        and late5 >= CROWDED_LEVEL
    )
    if crowded_long or crowded_plateau:
        scenario = "久热"
    elif (
        BUD_LEVEL_MIN <= level <= BUD_LEVEL_MAX
        and slope_v is not None
        and slope_v >= NEAR_SLOPE_EPS
        and (not np.isfinite(early_mean) or early_mean <= BUD_EARLY_MAX)
    ):
        scenario = "萌芽"
    elif MID_LEVEL_MIN <= level <= MID_LEVEL_MAX and not (
        slope_v is not None and slope_v < MID_SLOPE_FLOOR
    ):
        scenario = "中位"

    return scenario, round(level, 4), None if slope_v is None else round(slope_v, 5)


def build_theme_scenarios(
    *,
    theme_ids: list[str],
    theme_labels: list[str],
    theme_hrefs: list[str] | None = None,
    raw_z: list[list[float | None]] | np.ndarray,
    trail: int = TRAIL_DAYS,
    near_k: int = NEAR_K,
) -> list[dict[str, Any]]:
    """Per-theme scenario row from spectrum `raw_z` (dates × themes)."""
    z = np.asarray(raw_z, dtype=float)
    if z.ndim != 2 or z.size == 0 or not theme_ids:
        return []
    if z.shape[1] != len(theme_ids):
        raise ValueError("raw_z width must match theme_ids")
    hrefs = list(theme_hrefs or [])
    rows: list[dict[str, Any]] = []
    for i, theme_id in enumerate(theme_ids):
        scenario, level, slope = classify_hotness_scenario(
            z[:, i], trail=trail, near_k=near_k
        )
        bucket = slope_bucket(slope)
        rows.append(
            {
                "theme_id": theme_id,
                "label": theme_labels[i] if i < len(theme_labels) else theme_id,
                "href": hrefs[i] if i < len(hrefs) else f"/boards/concept/themes/{theme_id}",
                "scenario": scenario,
                "hotness": level,
                "near_slope": slope,
                "slope_key": bucket,
                "slope_label": SLOPE_LABELS[bucket],
                "hint": SCENARIO_HINTS.get(scenario or "", "未归入三类；先看近端斜率"),
            }
        )
    return rows
