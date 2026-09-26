"""Assemble a concept theme page/API payload from heat rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.themes.badges import (
    build_members,
    daily_group_median_series,
    judge_group_a,
    judge_pair,
    judge_satellite,
    percentiles_from_heats,
    window_delta,
)
from app.themes.config import ThemeConfig, constants_footnote, theme_board_codes
from app.themes.medicine import MEDICINE_THEME

_THEMES: dict[str, ThemeConfig] = {
    MEDICINE_THEME.theme_id: MEDICINE_THEME,
}


def get_theme(theme_id: str) -> ThemeConfig | None:
    return _THEMES.get(theme_id)


def list_themes() -> list[ThemeConfig]:
    return list(_THEMES.values())


def _as_float(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def build_theme_view(
    theme: ThemeConfig,
    *,
    as_of: date,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, object | None]],
    slider_dates: list[date],
) -> dict:
    """Build JSON-serializable theme view.

    ``heat_rows`` are (trade_date, board_code, heat_short) for the board type
    across the window (all concepts needed for percentiles).
    """
    if not window_dates:
        return _empty_view(theme, as_of, slider_dates, "窗口内没有热度日期")

    d0 = window_dates[0]
    as_of_eff = window_dates[-1]
    if as_of_eff != as_of:
        # Caller asked for a day without heat; use last window day.
        as_of = as_of_eff

    heat_by_day: dict[date, dict[str, float]] = {}
    for trade_date, board_code, heat_short in heat_rows:
        value = _as_float(heat_short)
        if value is None:
            continue
        heat_by_day.setdefault(trade_date, {})[board_code] = value

    pct_by_day = {
        day: percentiles_from_heats(heats) for day, heats in heat_by_day.items()
    }

    heat_d0 = {code: heat_by_day.get(d0, {}).get(code) for code in theme_board_codes(theme)}
    heat_as = {
        code: heat_by_day.get(as_of, {}).get(code) for code in theme_board_codes(theme)
    }
    pct_d0 = {code: pct_by_day.get(d0, {}).get(code) for code in theme_board_codes(theme)}
    pct_as = {code: pct_by_day.get(as_of, {}).get(code) for code in theme_board_codes(theme)}

    a_boards = [(b.board_code, b.board_name) for b in theme.group_a]
    b_boards = [(b.board_code, b.board_name) for b in theme.group_b]

    members_a = build_members(a_boards, heat_d0, heat_as, pct_d0, pct_as, theme.epsilon)
    members_b = build_members(b_boards, heat_d0, heat_as, pct_d0, pct_as, theme.epsilon)

    badge_a = judge_group_a(members_a, theme)

    a_codes = [b.board_code for b in theme.group_a]
    b_codes = [b.board_code for b in theme.group_b]
    series_a_heat = daily_group_median_series(window_dates, a_codes, heat_by_day, False)
    series_b_heat = daily_group_median_series(window_dates, b_codes, heat_by_day, False)
    series_a_pct = daily_group_median_series(
        window_dates, a_codes, heat_by_day, True, pct_by_day
    )
    series_b_pct = daily_group_median_series(
        window_dates, b_codes, heat_by_day, True, pct_by_day
    )

    delta_a = window_delta(
        series_a_heat[0][1] if series_a_heat else None,
        series_a_heat[-1][1] if series_a_heat else None,
    )
    delta_b = window_delta(
        series_b_heat[0][1] if series_b_heat else None,
        series_b_heat[-1][1] if series_b_heat else None,
    )
    badge_ab = judge_pair(
        delta_a,
        delta_b,
        series_a_pct[0][1] if series_a_pct else None,
        series_a_pct[-1][1] if series_a_pct else None,
        series_b_pct[0][1] if series_b_pct else None,
        series_b_pct[-1][1] if series_b_pct else None,
        theme,
    )

    domain_deltas = [m.delta for m in members_a + members_b]
    satellites = []
    for sat in theme.satellites:
        judged = judge_satellite(
            sat.board_code,
            sat.board_name,
            heat_d0.get(sat.board_code),
            heat_as.get(sat.board_code),
            pct_as.get(sat.board_code),
            domain_deltas,
            theme,
            badge_a.label,
        )
        satellites.append(
            {
                "board_code": judged.board_code,
                "board_name": judged.board_name,
                "label": judged.label,
                "detail": judged.detail,
                "delta": _round(judged.delta, 1),
                "percentile_as_of": _round(judged.percentile_as_of, 3),
            }
        )

    member_series = {}
    for code, name in a_boards + b_boards + [
        (s.board_code, s.board_name) for s in theme.satellites
    ]:
        points = []
        for day in window_dates:
            heat = heat_by_day.get(day, {}).get(code)
            pct = pct_by_day.get(day, {}).get(code)
            points.append(
                {
                    "trade_date": day.isoformat(),
                    "heat_short": heat,
                    "percentile": pct,
                }
            )
        member_series[code] = {"board_name": name, "points": points}

    return {
        "theme_id": theme.theme_id,
        "title": theme.title,
        "as_of": as_of.isoformat(),
        "window_start": d0.isoformat(),
        "window_days": len(window_dates),
        "dates": [day.isoformat() for day in slider_dates],
        "badge_a": {
            "label": badge_a.label,
            "detail": badge_a.detail,
            "delta": _round(badge_a.delta, 1),
            "spread_d0": _round(badge_a.spread_d0, 3),
            "spread_as_of": _round(badge_a.spread_as_of, 3),
            "co_move_ratio": _round(badge_a.co_move_ratio, 3),
        },
        "badge_ab": {
            "label": badge_ab.label,
            "sublabel": badge_ab.sublabel,
            "detail": badge_ab.detail,
            "delta_a": _round(badge_ab.delta_a, 1),
            "delta_b": _round(badge_ab.delta_b, 1),
            "gap_d0": _round(badge_ab.gap_d0, 3),
            "gap_as_of": _round(badge_ab.gap_as_of, 3),
        },
        "members_a": [_member_payload(m) for m in members_a],
        "members_b": [_member_payload(m) for m in members_b],
        "satellites": satellites,
        "series_group_a": _series_payload(series_a_pct),
        "series_group_b": _series_payload(series_b_pct),
        "member_series": member_series,
        "group_a_names": [b.board_name for b in theme.group_a],
        "group_b_names": [b.board_name for b in theme.group_b],
        "constants": [
            {"name": name, "value": value}
            for name, value in constants_footnote(theme)
        ],
        "membership_note": (
            "试点配置：A="
            + "、".join(b.board_name for b in theme.group_a)
            + "；B="
            + "、".join(b.board_name for b in theme.group_b)
            + "；卫星="
            + "、".join(b.board_name for b in theme.satellites)
        ),
        "empty_message": None,
    }


def _member_payload(member) -> dict:
    return {
        "board_code": member.board_code,
        "board_name": member.board_name,
        "heat_short": _round(member.heat_as_of, 1),
        "percentile": _round(member.pct_as_of, 3),
        "delta": _round(member.delta, 1),
        "role": member.role,
    }


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _series_payload(series: list[tuple[date, float | None]]) -> list[dict]:
    return [
        {"trade_date": day.isoformat(), "value": value} for day, value in series
    ]


def _empty_view(
    theme: ThemeConfig,
    as_of: date | None,
    slider_dates: list[date],
    message: str,
) -> dict:
    return {
        "theme_id": theme.theme_id,
        "title": theme.title,
        "as_of": as_of.isoformat() if as_of else None,
        "window_start": None,
        "window_days": 0,
        "dates": [day.isoformat() for day in slider_dates],
        "badge_a": {"label": "数据不足", "detail": message, "delta": None},
        "badge_ab": {
            "label": "数据不足",
            "sublabel": None,
            "detail": message,
            "delta_a": None,
            "delta_b": None,
            "gap_d0": None,
            "gap_as_of": None,
        },
        "members_a": [],
        "members_b": [],
        "satellites": [],
        "series_group_a": [],
        "series_group_b": [],
        "member_series": {},
        "group_a_names": [b.board_name for b in theme.group_a],
        "group_b_names": [b.board_name for b in theme.group_b],
        "constants": [
            {"name": name, "value": value}
            for name, value in constants_footnote(theme)
        ],
        "membership_note": "",
        "empty_message": message,
    }
