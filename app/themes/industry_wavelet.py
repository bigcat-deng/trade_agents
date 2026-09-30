"""2D wavelet analysis on industry-board short-heat plane."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.themes.heat_wavelet2d import (
    FEATURE_TOP_N,
    LEVEL,
    WAVELET,
    analyze_heat_wavelet2d,
)
from app.themes.industry_wave import build_industry_board_heat_payload

__all__ = [
    "FEATURE_TOP_N",
    "build_industry_wavelet_payload",
]


def build_industry_wavelet_payload(
    *,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, str, object | None, object | None]],
) -> dict[str, Any]:
    """Return wavelet bands, energy shares, and industry feature tables."""
    industry = build_industry_board_heat_payload(
        window_dates=window_dates,
        heat_rows=heat_rows,
    )
    if industry.get("empty_message"):
        return {
            "empty_message": industry["empty_message"],
            "as_of": None,
            "dates": [],
            "board_names": [],
            "board_codes": [],
            "top_n": None,
        }

    n = industry["board_count"]
    return analyze_heat_wavelet2d(
        z_short=industry["z_short"],
        dates=industry["dates"],
        board_names=industry["board_names"],
        board_codes=industry["board_codes"],
        as_of=industry["as_of"],
        select_from=None,
        select_to=None,
        top_n=n,
        axis_note=(
            f"与行业板块短热平面同一全样本叶序（共 {n} 个行业，无 TopN 截断）；"
            f"二维小波 {WAVELET}×{LEVEL} 层；"
            "横轴=共动叶序（非产业链），纵轴=交易日；颜色越高越热（翻转分位）。"
        ),
    )
