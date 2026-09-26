"""Count recent MACD and heat crosses for the rotation tables."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.charts.kline import MACD_FAST, MACD_SIGNAL, MACD_SLOW, _macd
from app.db import fetch_board_close_heat, fetch_trading_dates_ending

_EMPTY = {"macd_up": 0, "macd_down": 0, "heat_up": 0, "heat_down": 0}
_HISTORY_DAYS = 120


def attach_cross_stats(reading: dict, as_of: date, board_type: str = "industry") -> dict:
    """Add a cross count for each table row, covering the last three trading days."""
    codes = [
        row["board_code"]
        for section in reading.get("sections") or []
        for row in section.get("rows") or []
        if row.get("board_code")
    ]
    counts = recent_cross_counts(codes, as_of, board_type=board_type)
    sections = []
    for section in reading.get("sections") or []:
        rows = []
        for row in section.get("rows") or []:
            stats = counts.get(row.get("board_code") or "", _EMPTY)
            rows.append({**row, "cross_stats": stats})
        sections.append({**section, "rows": rows})
    return {**reading, "sections": sections}


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
    series = fetch_board_close_heat(board_type, list(dict.fromkeys(board_codes)), start, as_of)
    recent_set = set(recent)
    return {
        code: _count_one(rows, recent_set)
        for code, rows in series.items()
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
    if not any(value is not None for value in closes):
        return 0, 0
    filled = pd.Series(
        [float("nan") if value is None else value for value in closes],
        dtype="float",
    )
    dif, dea, _hist = _macd(filled, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    left = [None if pd.isna(value) else float(value) for value in dif]
    right = [None if pd.isna(value) else float(value) for value in dea]
    return _directions(dates, left, right, recent)


def _directions(
    dates: list[date],
    left: list[float | None],
    right: list[float | None],
    recent: set[date],
) -> tuple[int, int]:
    """Count days in `recent` when left crosses above right (up) or below it (down)."""
    up = 0
    down = 0
    previous: float | None = None
    for day, a, b in zip(dates, left, right, strict=False):
        if a is None or b is None:
            previous = None
            continue
        diff = a - b
        if previous is not None and day in recent and previous * diff < 0:
            if diff > 0:
                up += 1
            else:
                down += 1
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
