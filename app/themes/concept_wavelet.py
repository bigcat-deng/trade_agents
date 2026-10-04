"""2D wavelet analysis on concept short-heat Top200 plane."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.themes.concept_wave import CONCEPT_TOP_N, build_concept_top_heat_payload
from app.themes.heat_wavelet2d import (
    FEATURE_TOP_N,
    LEVEL,
    WAVELET,
    analyze_heat_wavelet2d,
)

__all__ = [
    "FEATURE_TOP_N",
    "build_concept_wavelet_payload",
]


def build_concept_wavelet_payload(
    *,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, str, object | None, object | None]],
    top_n: int = CONCEPT_TOP_N,
) -> dict[str, Any]:
    """Return wavelet bands, energy shares, and concept feature tables."""
    concept_top = build_concept_top_heat_payload(
        window_dates=window_dates,
        heat_rows=heat_rows,
        top_n=top_n,
    )
    if concept_top.get("empty_message"):
        return {
            "empty_message": concept_top["empty_message"],
            "as_of": None,
            "dates": [],
            "board_names": [],
            "board_codes": [],
            "top_n": top_n,
        }

    n = concept_top["board_count"]
    base_top_n = concept_top.get("top_n") or CONCEPT_TOP_N
    theme_added = int(concept_top.get("theme_added") or 0)
    result = analyze_heat_wavelet2d(
        z_short=concept_top["z_short"],
        dates=concept_top["dates"],
        board_names=concept_top["board_names"],
        board_codes=concept_top["board_codes"],
        as_of=concept_top["as_of"],
        select_from=concept_top.get("select_from"),
        select_to=concept_top.get("select_to"),
        top_n=n,
        axis_note=(
            f"与概念短热同一入选与叶序"
            f"（近端 Top{base_top_n}∪主题A+B+卫星，共 {n} 列"
            + (f"，其中主题补入 {theme_added}" if theme_added else "")
            + f"）；二维小波 {WAVELET}×{LEVEL} 层；"
            "横轴=轨迹+结构融合叶序（非产业链），纵轴=交易日；颜色越高越热（翻转分位）。"
        ),
    )
    result["top_n"] = base_top_n
    result["top_count"] = concept_top.get("top_count")
    result["theme_added"] = theme_added
    return result
