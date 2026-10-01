"""Count recent MACD/heat crosses, range-position buckets, and trusted signals."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.charts.kline import MACD_FAST, MACD_SIGNAL, MACD_SLOW, _macd
from app.db import (
    fetch_board_close_heat,
    fetch_board_daily_bars_many,
    fetch_board_type_heat_window,
    fetch_heat_dates_ending,
    fetch_trading_dates_ending,
)
from app.themes.concept_wave import build_concept_top_heat_payload
from app.themes.industry_wave import build_industry_board_heat_payload

_EMPTY = {"macd_up": 0, "macd_down": 0, "heat_up": 0, "heat_down": 0}
_EMPTY_RANGE = {"top": 0, "mid": 0, "bottom": 0}
_EMPTY_SIGNAL = {
    "macd_up_recent": False,
    "near_warming": False,
    "near_cooling": False,
    "crowded_top": False,
    "in_hot_cluster": False,
    "surface_pass": False,
    "surface_known": False,
    "range_high": False,
    "trusted_macd_up": False,
    "label": "",
}
_HISTORY_DAYS = 120
# Match default board kline page window (/boards/{type}/{code}/kline).
_KLINE_RANGE_DAYS = 100
_RANGE_COUNT_DAYS = 10
_RANGE_TOP = 0.8
_RANGE_BOTTOM = 0.2
_SURFACE_WINDOW_DAYS = 60


def attach_cross_stats(reading: dict, as_of: date, board_type: str = "industry") -> dict:
    """Add cross counts, 10-day 顶/中/底, and validated MACD×surface signal labels."""
    codes = [
        row["board_code"]
        for section in reading.get("sections") or []
        for row in section.get("rows") or []
        if row.get("board_code")
    ]
    unique_codes = list(dict.fromkeys(codes))
    counts = recent_cross_counts(unique_codes, as_of, board_type=board_type)
    range_counts = recent_range_position_counts(
        unique_codes, as_of, board_type=board_type
    )
    surface = _surface_flags_by_code(board_type, as_of)
    sections = []
    for section in reading.get("sections") or []:
        rows = []
        for row in section.get("rows") or []:
            code = row.get("board_code") or ""
            cross = counts.get(code, _EMPTY)
            ranges = range_counts.get(code, _EMPTY_RANGE)
            rows.append(
                {
                    **row,
                    "cross_stats": cross,
                    "range_stats": ranges,
                    "signal_stats": _signal_stats(
                        cross, surface.get(code), ranges
                    ),
                }
            )
        sections.append({**section, "rows": rows})
    return {**reading, "sections": sections}


def _surface_flags_by_code(
    board_type: str, as_of: date
) -> dict[str, dict[str, object]]:
    window = fetch_heat_dates_ending(board_type, as_of, _SURFACE_WINDOW_DAYS)
    if len(window) < 20:
        return {}
    heat_rows = fetch_board_type_heat_window(board_type, window[0], window[-1])
    if board_type == "concept":
        payload = build_concept_top_heat_payload(
            window_dates=window, heat_rows=heat_rows
        )
    else:
        payload = build_industry_board_heat_payload(
            window_dates=window, heat_rows=heat_rows
        )
    flags = payload.get("surface_flags") or []
    return {
        str(item["board_code"]): item
        for item in flags
        if item.get("board_code")
    }


def _signal_stats(
    cross: dict[str, int],
    surface: dict[str, object] | None,
    range_stats: dict[str, int] | None = None,
) -> dict[str, object]:
    macd_up_recent = int(cross.get("macd_up") or 0) > 0
    range_high = _range_high_biased(range_stats)
    if surface is None:
        label = ""
        if macd_up_recent and range_high:
            label = "金叉·无水面·偏高位"
        elif macd_up_recent:
            label = "金叉·无水面"
        return {
            **_EMPTY_SIGNAL,
            "macd_up_recent": macd_up_recent,
            "range_high": range_high,
            "label": label,
        }
    near_warming = bool(surface.get("near_warming"))
    near_cooling = bool(surface.get("near_cooling"))
    crowded_top = bool(surface.get("crowded_top"))
    in_hot_cluster = bool(surface.get("in_hot_cluster"))
    # Step-3 validated filter for UP: near_warming AND NOT crowded_top
    surface_pass = near_warming and not crowded_top
    trusted = macd_up_recent and surface_pass and not range_high
    if trusted:
        label = "可信金叉"
    elif macd_up_recent and surface_pass and range_high:
        label = "金叉·水面过·偏高位"
    elif macd_up_recent and crowded_top:
        label = "金叉·拥挤顶"
    elif macd_up_recent and not near_warming:
        label = "金叉·未升温"
    elif macd_up_recent:
        label = "金叉·未过筛"
    else:
        label = ""
    return {
        "macd_up_recent": macd_up_recent,
        "near_warming": near_warming,
        "near_cooling": near_cooling,
        "crowded_top": crowded_top,
        "in_hot_cluster": in_hot_cluster,
        "surface_pass": surface_pass,
        "surface_known": True,
        "range_high": range_high,
        "trusted_macd_up": trusted,
        "label": label,
    }


def _range_high_biased(range_stats: dict[str, int] | None) -> bool:
    """True when recent closes sit mostly near the top of the kline range."""
    if not range_stats:
        return False
    top = int(range_stats.get("top") or 0)
    mid = int(range_stats.get("mid") or 0)
    bottom = int(range_stats.get("bottom") or 0)
    return top >= 5 or (top > mid and top > bottom)


def recent_cross_counts(
    board_codes: list[str],
    as_of: date,
    days: int = 3,
    board_type: str = "industry",
) -> dict[str, dict[str, int]]:
    recent = fetch_trading_dates_ending(board_type, as_of, days)
    if not board_codes or not recent:
        return {}
    history = fetch_trading_dates_ending(board_type, as_of, _HISTORY_DAYS)
    start = history[0] if history else recent[0]
    series = fetch_board_close_heat(
        board_type, list(dict.fromkeys(board_codes)), start, as_of
    )
    recent_set = set(recent)
    return {
        code: _count_one(rows, recent_set)
        for code, rows in series.items()
    }


def recent_range_position_counts(
    board_codes: list[str],
    as_of: date,
    count_days: int = _RANGE_COUNT_DAYS,
    range_days: int = _KLINE_RANGE_DAYS,
    board_type: str = "industry",
) -> dict[str, dict[str, int]]:
    """Count last `count_days` closes at 顶/中/底 of the `range_days` kline high-low."""
    if not board_codes:
        return {}
    range_dates = fetch_trading_dates_ending(board_type, as_of, range_days)
    if not range_dates:
        return {}
    recent = (
        range_dates[-count_days:]
        if len(range_dates) >= count_days
        else list(range_dates)
    )
    start, end = range_dates[0], range_dates[-1]
    bars_by_code = fetch_board_daily_bars_many(
        board_type, list(dict.fromkeys(board_codes)), start, end
    )
    recent_set = set(recent)
    return {
        code: _range_position_counts(bars_by_code.get(code) or [], recent_set)
        for code in board_codes
    }


def _range_position_counts(
    bars: list[dict[str, object]],
    recent: set[date],
) -> dict[str, int]:
    """Range from all `bars`; count only closes whose trade_date is in `recent`."""
    highs = [_number(bar.get("high")) for bar in bars]
    lows = [_number(bar.get("low")) for bar in bars]
    valid_highs = [v for v in highs if v is not None]
    valid_lows = [v for v in lows if v is not None]
    if not valid_highs or not valid_lows:
        return dict(_EMPTY_RANGE)
    range_high = max(valid_highs)
    range_low = min(valid_lows)
    span = range_high - range_low
    if span <= 0:
        return dict(_EMPTY_RANGE)

    top = mid = bottom = 0
    for bar in bars:
        if bar.get("trade_date") not in recent:
            continue
        close = _number(bar.get("close"))
        if close is None:
            continue
        pos = (close - range_low) / span
        if pos >= _RANGE_TOP:
            top += 1
        elif pos <= _RANGE_BOTTOM:
            bottom += 1
        else:
            mid += 1
    return {"top": top, "mid": mid, "bottom": bottom}


def list_cross_event_dates(
    rows: list[tuple[date, object, object, object]],
) -> dict[str, list[date]]:
    """All MACD/heat cross dates on `rows` (same rules as rotation table counts)."""
    if not rows:
        return {key: [] for key in _EMPTY}
    dates = [row[0] for row in rows]
    recent = set(dates)
    closes = [_number(row[1]) for row in rows]
    macd_up_dates, macd_down_dates = _macd_event_dates(dates, closes, recent)
    heat_left = [_negated(_number(row[2])) for row in rows]
    heat_right = [_negated(_number(row[3])) for row in rows]
    heat_up_dates, heat_down_dates = _event_dates(
        dates, heat_left, heat_right, recent
    )
    return {
        "macd_up": macd_up_dates,
        "macd_down": macd_down_dates,
        "heat_up": heat_up_dates,
        "heat_down": heat_down_dates,
    }


def _count_one(
    rows: list[tuple[date, object, object, object]],
    recent: set[date],
) -> dict[str, int]:
    dates = [row[0] for row in rows]
    closes = [_number(row[1]) for row in rows]
    macd_up, macd_down = _macd_directions(dates, closes, recent)
    heat_left = [_negated(_number(row[2])) for row in rows]
    heat_right = [_negated(_number(row[3])) for row in rows]
    heat_up, heat_down = _directions(dates, heat_left, heat_right, recent)
    return {
        "macd_up": macd_up,
        "macd_down": macd_down,
        "heat_up": heat_up,
        "heat_down": heat_down,
    }


def _macd_directions(
    dates: list[date],
    closes: list[float | None],
    recent: set[date],
) -> tuple[int, int]:
    up_dates, down_dates = _macd_event_dates(dates, closes, recent)
    return len(up_dates), len(down_dates)


def _macd_event_dates(
    dates: list[date],
    closes: list[float | None],
    recent: set[date],
) -> tuple[list[date], list[date]]:
    if not any(value is not None for value in closes):
        return [], []
    filled = pd.Series(
        [float("nan") if value is None else value for value in closes],
        dtype="float",
    )
    dif, dea, _hist = _macd(filled, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    left = [None if pd.isna(value) else float(value) for value in dif]
    right = [None if pd.isna(value) else float(value) for value in dea]
    return _event_dates(dates, left, right, recent)


def _directions(
    dates: list[date],
    left: list[float | None],
    right: list[float | None],
    recent: set[date],
) -> tuple[int, int]:
    """Count days in `recent` when left crosses above right (up) or below it (down)."""
    up_dates, down_dates = _event_dates(dates, left, right, recent)
    return len(up_dates), len(down_dates)


def _event_dates(
    dates: list[date],
    left: list[float | None],
    right: list[float | None],
    recent: set[date],
) -> tuple[list[date], list[date]]:
    """Days in `recent` when left crosses above right (up) or below it (down)."""
    up: list[date] = []
    down: list[date] = []
    previous: float | None = None
    for day, a, b in zip(dates, left, right, strict=False):
        if a is None or b is None:
            previous = None
            continue
        diff = a - b
        if previous is not None and day in recent and previous * diff < 0:
            if diff > 0:
                up.append(day)
            else:
                down.append(day)
        previous = diff
    return up, down


def _number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _negated(value: float | None) -> float | None:
    if value is None:
        return None
    return -value
