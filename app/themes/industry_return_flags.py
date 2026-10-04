"""Industry board close-return volatility exceedance marks for the heat plane."""

from __future__ import annotations

from datetime import date

import numpy as np

RETURN_VOL_LOOKBACK = 100
RETURN_VOL_MULT = 2.0
_MIN_RETURNS_FOR_SIGMA = 40


def _closes_by_day(
    bars: list[dict[str, object]],
) -> dict[date, float]:
    out: dict[date, float] = {}
    for bar in bars:
        day = bar.get("trade_date")
        close = bar.get("close")
        if day is None or close is None:
            continue
        try:
            out[day if isinstance(day, date) else date.fromisoformat(str(day))] = float(
                close
            )
        except (TypeError, ValueError):
            continue
    return out


def _returns_on_calendar(
    closes: dict[date, float],
    calendar: list[date],
) -> dict[date, float]:
    """Close-to-close returns keyed by the later day, only on consecutive calendar pairs."""
    out: dict[date, float] = {}
    for i in range(1, len(calendar)):
        prev, cur = calendar[i - 1], calendar[i]
        c0, c1 = closes.get(prev), closes.get(cur)
        if c0 is None or c1 is None or c0 == 0.0:
            continue
        out[cur] = c1 / c0 - 1.0
    return out


def sigma_from_returns(
    returns: list[float],
    *,
    lookback: int = RETURN_VOL_LOOKBACK,
) -> float | None:
    """Sample σ of the last ``lookback`` returns; None if too short or degenerate."""
    if lookback < 2:
        return None
    tail = returns[-lookback:]
    if len(tail) < min(lookback, _MIN_RETURNS_FOR_SIGMA):
        return None
    arr = np.asarray(tail, dtype=float)
    if arr.size < 2:
        return None
    sig = float(np.std(arr, ddof=1))
    if not np.isfinite(sig) or sig <= 1e-12:
        return None
    return sig


def compute_return_exceedance_cells(
    *,
    ordered_codes: list[str],
    window_dates: list[date],
    bars_by_code: dict[str, list[dict[str, object]]],
    vol_calendar: list[date],
    lookback: int = RETURN_VOL_LOOKBACK,
    mult: float = RETURN_VOL_MULT,
) -> tuple[list[tuple[str, date]], list[tuple[str, date]]]:
    """Return (positive, negative) (board_code, day) cells exceeding ±mult·σ.

    σ is estimated from the last ``lookback`` close-to-close returns on
    ``vol_calendar`` ending at the window as-of (last vol_calendar day).
    """
    if not ordered_codes or not window_dates or not vol_calendar:
        return [], []
    window_set = set(window_dates)
    pos: list[tuple[str, date]] = []
    neg: list[tuple[str, date]] = []
    for code in ordered_codes:
        closes = _closes_by_day(bars_by_code.get(code) or [])
        if len(closes) < 2:
            continue
        rets_map = _returns_on_calendar(closes, vol_calendar)
        # Ordered returns along vol_calendar for σ.
        ordered_rets = [rets_map[d] for d in vol_calendar if d in rets_map]
        sig = sigma_from_returns(ordered_rets, lookback=lookback)
        if sig is None:
            continue
        thr = mult * sig
        for day in window_dates:
            if day not in window_set:
                continue
            r = rets_map.get(day)
            if r is None:
                continue
            if r > thr:
                pos.append((code, day))
            elif r < -thr:
                neg.append((code, day))
    return pos, neg


def exceedance_to_line_xy(
    *,
    cells: list[tuple[str, date]],
    ordered_codes: list[str],
    window_dates: list[date],
    half_width: float = 0.5,
) -> tuple[list[float | None], list[float | None]]:
    """Horizontal segments on the bottom edge of each (board, day) cell."""
    code_x = {code: float(i) for i, code in enumerate(ordered_codes)}
    day_y = {day: float(i) for i, day in enumerate(window_dates)}
    xs: list[float | None] = []
    ys: list[float | None] = []
    for code, day in cells:
        if code not in code_x or day not in day_y:
            continue
        x = code_x[code]
        y_bottom = day_y[day] - 0.5
        xs.extend([x - half_width, x + half_width, None])
        ys.extend([y_bottom, y_bottom, None])
    return xs, ys


def last_day_label_points(
    *,
    cells: list[tuple[str, date]],
    ordered_codes: list[str],
    names: dict[str, str] | None,
    window_dates: list[date],
) -> tuple[list[float], list[float], list[str]]:
    """Column-top labels for exceedances on the last displayed trading day."""
    if not window_dates:
        return [], [], []
    last_day = window_dates[-1]
    y_top = float(len(window_dates) - 1) + 0.5
    name_map = names or {}
    xs: list[float] = []
    ys: list[float] = []
    texts: list[str] = []
    for code, day in cells:
        if day != last_day:
            continue
        try:
            x = float(ordered_codes.index(code))
        except ValueError:
            continue
        xs.append(x)
        ys.append(y_top)
        texts.append(name_map.get(code) or code)
    return xs, ys, texts


def build_return_exceedance_overlay(
    *,
    ordered_codes: list[str],
    window_dates: list[date],
    bars_by_code: dict[str, list[dict[str, object]]],
    vol_calendar: list[date],
    names: dict[str, str] | None = None,
    lookback: int = RETURN_VOL_LOOKBACK,
    mult: float = RETURN_VOL_MULT,
) -> dict[str, object]:
    """Payload fragment: line coords + last-day names for ±mult·σ return marks."""
    pos_cells, neg_cells = compute_return_exceedance_cells(
        ordered_codes=ordered_codes,
        window_dates=window_dates,
        bars_by_code=bars_by_code,
        vol_calendar=vol_calendar,
        lookback=lookback,
        mult=mult,
    )
    pos_x, pos_y = exceedance_to_line_xy(
        cells=pos_cells, ordered_codes=ordered_codes, window_dates=window_dates
    )
    neg_x, neg_y = exceedance_to_line_xy(
        cells=neg_cells, ordered_codes=ordered_codes, window_dates=window_dates
    )
    last_pos_x, last_pos_y, last_pos_text = last_day_label_points(
        cells=pos_cells,
        ordered_codes=ordered_codes,
        names=names,
        window_dates=window_dates,
    )
    last_neg_x, last_neg_y, last_neg_text = last_day_label_points(
        cells=neg_cells,
        ordered_codes=ordered_codes,
        names=names,
        window_dates=window_dates,
    )
    return {
        "pos_x": pos_x,
        "pos_y": pos_y,
        "neg_x": neg_x,
        "neg_y": neg_y,
        "last_pos_x": last_pos_x,
        "last_pos_y": last_pos_y,
        "last_pos_text": last_pos_text,
        "last_neg_x": last_neg_x,
        "last_neg_y": last_neg_y,
        "last_neg_text": last_neg_text,
        "pos_count": len(pos_cells),
        "neg_count": len(neg_cells),
        "lookback": lookback,
        "mult": mult,
    }
