"""Theme-wave scenario tags along one heat path.

冷寂 → 萌芽 → 升温 → 中位 → 高位 → 久热, and 退潮 when a mid-or-higher
theme turns down. Every finite hotness lands in exactly one tag.
Tags are attention scenarios, not trade triggers.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.themes.heat_surface_flags import NEAR_K, NEAR_SLOPE_EPS, _hotness_slope

TRAIL_DAYS = 20
LEVEL_MID = 0.55
LEVEL_HIGH = 0.85
CROWDED_LEVEL = 0.90
CROWDED_HIGH = 0.80
CROWDED_DAYS = 8

SCENARIO_ORDER = ("冷寂", "萌芽", "升温", "中位", "高位", "久热", "退潮")

SCENARIO_HINTS = {
    "冷寂": "低位未起；抬升才入萌芽",
    "萌芽": "观察；近端续热再加重",
    "升温": "离开冷区仍在抬；看能否进入高位",
    "中位": "中段走平；转落即退潮",
    "高位": "高位未拥挤；天数坐实才是久热",
    "久热": "降权新仓；转冷进入退潮",
    "退潮": "中高位转落；掉回低位看冷寂或萌芽",
}
REBOUND_HINT = "回抽再起；近端续热再加重"

SLOPE_LABELS = {
    "up": "抬升",
    "flat": "走平",
    "down": "回落",
}

SCENARIO_NOTE = (
    "情景按截止日群 A 光谱热度归入一条过程链："
    "冷寂→萌芽→升温→中位→高位→久热，中高位转落为退潮。"
    "跟过程不跟色块高度；周一立假说 → 周中看续热 → 周末复盘。"
)


def slope_bucket(slope: float | None) -> str:
    if slope is None or not np.isfinite(slope):
        return "flat"
    if slope >= NEAR_SLOPE_EPS:
        return "up"
    if slope <= -NEAR_SLOPE_EPS:
        return "down"
    return "flat"


def _window(series: np.ndarray, trail: int) -> np.ndarray:
    return series[-max(1, min(trail, series.size)) :]


def _early_mean(window: np.ndarray) -> float:
    early = window[: max(1, len(window) // 2)]
    if not np.any(np.isfinite(early)):
        return float("nan")
    return float(np.nanmean(early))


def _crowded(level: float, window: np.ndarray) -> bool:
    high_days = int(np.sum(np.isfinite(window) & (window >= CROWDED_HIGH)))
    late = window[-5:]
    late5 = float(np.nanmean(late)) if np.any(np.isfinite(late)) else float("nan")
    crowded_long = level >= CROWDED_LEVEL and high_days >= min(CROWDED_DAYS, len(window))
    crowded_plateau = level >= 0.95 and np.isfinite(late5) and late5 >= CROWDED_LEVEL
    return bool(crowded_long or crowded_plateau)


def classify_hotness_scenario(
    series: np.ndarray,
    *,
    trail: int = TRAIL_DAYS,
    near_k: int = NEAR_K,
) -> tuple[str | None, float | None, float | None]:
    """Return (scenario, hotness_asof, near_slope) for one theme series.

    A finite ending hotness always receives one tag. Falling out of the
    mid band is checked first, so a crowded theme that turns down leaves
    久热 for 退潮.
    """
    if series.size == 0:
        return None, None, None
    window = _window(series, trail)
    level = float(window[-1]) if np.isfinite(window[-1]) else float("nan")
    if not np.isfinite(level):
        return None, None, None
    slope = _hotness_slope(window, k=near_k)
    slope_v = float(slope) if np.isfinite(slope) else None
    rising = slope_v is not None and slope_v >= NEAR_SLOPE_EPS
    falling = slope_v is not None and slope_v <= -NEAR_SLOPE_EPS

    if level >= LEVEL_MID and falling:
        scenario = "退潮"
    elif _crowded(level, window):
        scenario = "久热"
    elif level > LEVEL_HIGH:
        scenario = "高位"
    elif level >= LEVEL_MID and rising:
        scenario = "升温"
    elif level >= LEVEL_MID:
        scenario = "中位"
    elif rising:
        scenario = "萌芽"
    else:
        scenario = "冷寂"

    return scenario, round(level, 4), None if slope_v is None else round(slope_v, 5)


def scenario_hint(
    scenario: str | None,
    series: np.ndarray,
    *,
    trail: int = TRAIL_DAYS,
) -> str:
    """Reading line. A low theme that is rising again after a warm first half is 回抽再起."""
    if not scenario:
        return "热度无效"
    if scenario == "萌芽" and series.size:
        early = _early_mean(_window(series, trail))
        if np.isfinite(early) and early > LEVEL_MID:
            return REBOUND_HINT
    return SCENARIO_HINTS[scenario]


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
                "hint": scenario_hint(scenario, z[:, i], trail=trail),
            }
        )
    return rows
