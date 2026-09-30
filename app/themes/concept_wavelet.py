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

    return analyze_heat_wavelet2d(
        z_short=concept_top["z_short"],
        dates=concept_top["dates"],
        board_names=concept_top["board_names"],
        board_codes=concept_top["board_codes"],
        as_of=concept_top["as_of"],
        select_from=concept_top.get("select_from"),
        select_to=concept_top.get("select_to"),
        top_n=top_n,
        axis_note=(
            f"与概念短热 Top{top_n} 同一入选与叶序；"
            f"二维小波 {WAVELET}×{LEVEL} 层；"
            "横轴=共动叶序（非产业链），纵轴=交易日；颜色越高越热（翻转分位）。"
        ),
    )
