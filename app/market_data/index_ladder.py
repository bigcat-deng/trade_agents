"""Size-ladder indices: cumulative return, cross-section spread, range position.

Five baostock indices, last ``n`` trading days (default 100):

  上证50 sh.000016, 沪深300 sh.000300, 中证500 sh.000905,
  中证1000 sh.000852, 国证2000 sz.399303

``avg = (high + low + close) / 3`` is used only for the position series.
Cumulative return and the spread use close, rebased to the first day of the window.
"""

from __future__ import annotations

import statistics
import threading
import time
from datetime import date, timedelta

import baostock as bs
import numpy as np

from app.market_data.providers import baostock_kline

# Large to small. Color encodes size: blue = large, red = micro.
INDICES: tuple[tuple[str, str, str], ...] = (
    ("上证50", "sh.000016", "#1f4e79"),
    ("沪深300", "sh.000300", "#2e75b6"),
    ("中证500", "sh.000905", "#548235"),
    ("中证1000", "sh.000852", "#c65911"),
    ("国证2000", "sz.399303", "#c00000"),
)
LARGE_NAME = "上证50"
SMALL_NAME = "国证2000"

_CACHE: dict[tuple[int, str], dict] = {}
_LOCK = threading.Lock()
_CACHE_LIMIT = 8
# A day this far below the window's median traded count is a partial sync.
BREADTH_MIN_FRACTION = 0.8


def load_size_ladder(n: int, as_of: date) -> dict:
    """Cached baostock pull plus the window payload. Failures are not cached."""
    if n < 5:
        raise ValueError("n must be >= 5")
    key = (n, as_of.isoformat())
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        start = as_of - timedelta(days=n * 2 + 40)
        bars = fetch_index_bars(start, as_of)
        payload = build_payload(bars, n=n, as_of=as_of)
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = payload
        return payload


def build_payload(
    bars: dict[str, dict[date, tuple[float, float, float]]],
    *,
    n: int,
    as_of: date,
) -> dict:
    """Align on common sessions, keep the last ``n`` on or before ``as_of``."""
    common: set[date] | None = None
    for name, _code, _color in INDICES:
        days = {day for day in bars.get(name, {}) if day <= as_of}
        common = days if common is None else common & days
    if not common:
        raise ValueError(f"no common index sessions on or before {as_of}")
    dates = sorted(common)[-n:]
    if len(dates) < n:
        raise ValueError(f"only {len(dates)} common sessions before {as_of}, need {n}")

    closes = {
        name: np.array([bars[name][day][2] for day in dates], dtype=float)
        for name, _code, _color in INDICES
    }
    avgs = {
        name: np.array(
            [
                (bars[name][day][0] + bars[name][day][1] + bars[name][day][2]) / 3.0
                for day in dates
            ],
            dtype=float,
        )
        for name, _code, _color in INDICES
    }
    returns = {name: closes[name] / closes[name][0] - 1.0 for name in closes}
    stacked = np.vstack([returns[name] for name, _code, _color in INDICES])
    range_pp = (stacked.max(axis=0) - stacked.min(axis=0)) * 100.0
    spread = (returns[LARGE_NAME] - returns[SMALL_NAME]) * 100.0

    positions: dict[str, np.ndarray] = {}
    end_rows: dict[str, dict] = {}
    for name, _code, _color in INDICES:
        avg = avgs[name]
        lo = float(avg.min())
        hi = float(avg.max())
        if hi == lo:
            pos = np.full(len(avg), 0.5)
        else:
            pos = (avg - lo) / (hi - lo)
        positions[name] = pos
        high_i = int(avg.argmax())
        low_i = int(avg.argmin())
        end_rows[name] = {
            "return_pct": round(float(returns[name][-1]) * 100.0, 2),
            "position": round(float(pos[-1]), 3),
            "high_date": dates[high_i].isoformat(),
            "low_date": dates[low_i].isoformat(),
        }

    return {
        "source": "baostock",
        "n": len(dates),
        "start": dates[0].isoformat(),
        "end": dates[-1].isoformat(),
        "avg": "(high+low+close)/3",
        "dates": [day.isoformat() for day in dates],
        "returns_pct": {
            name: [round(float(v) * 100.0, 2) for v in returns[name]]
            for name, _code, _color in INDICES
        },
        "position": {
            name: [round(float(v), 3) for v in positions[name]]
            for name, _code, _color in INDICES
        },
        "range_pp": [round(float(v), 2) for v in range_pp],
        "spread_50_2000_pp": [round(float(v), 2) for v in spread],
        "snapshot": end_rows,
    }


def align_breadth(
    dates: list[date],
    counts: dict[date, tuple[int, int, int, int]],
    *,
    min_fraction: float = BREADTH_MIN_FRACTION,
) -> dict:
    """Map daily up/down/flat counts onto ``dates``.

    ``counts`` values are ``(up, down, flat, traded)``. Down is returned as a
    negative count so a diverging bar can share the zero line. Days below
    ``min_fraction`` of the median traded count, and days with no row, are
    left empty.
    """
    present = [counts[day][3] for day in dates if counts.get(day, (0, 0, 0, 0))[3] > 0]
    median = statistics.median(present) if present else 0.0
    floor = median * min_fraction
    up: list[int | None] = []
    down: list[int | None] = []
    flat: list[int | None] = []
    ratio: list[float | None] = []
    incomplete_y: list[int | None] = []
    traded: list[int] = []
    last_complete: dict | None = None
    for day in dates:
        row = counts.get(day)
        traded_n = 0 if row is None else row[3]
        traded.append(traded_n)
        if row is None or traded_n < floor:
            up.append(None)
            down.append(None)
            flat.append(None)
            ratio.append(None)
            incomplete_y.append(0)
            continue
        up_n, down_n, flat_n, _traded_n = row
        up.append(up_n)
        down.append(-down_n)
        flat.append(flat_n)
        denom = up_n + down_n
        ratio_n = None if denom == 0 else round(up_n / denom * 100.0, 1)
        ratio.append(ratio_n)
        incomplete_y.append(None)
        last_complete = {
            "date": day.isoformat(),
            "up": up_n,
            "down": down_n,
            "flat": flat_n,
            "ratio": ratio_n,
            "traded": traded_n,
        }
    return {
        "dates": [day.isoformat() for day in dates],
        "up": up,
        "down": down,
        "flat": flat,
        "up_ratio": ratio,
        "incomplete": incomplete_y,
        "traded": traded,
        "median_traded": median,
        "last_complete": last_complete,
    }


def fetch_index_bars(
    start: date, end: date
) -> dict[str, dict[date, tuple[float, float, float]]]:
    """High, low, close for each ladder index. Caller must not overlap logins."""
    login = None
    for attempt in range(1, 4):
        login = bs.login()
        if login.error_code == "0":
            break
        time.sleep(2 * attempt)
    if login is None or login.error_code != "0":
        message = login.error_msg if login is not None else "no response"
        raise RuntimeError(f"baostock login failed: {message}")
    try:
        out: dict[str, dict[date, tuple[float, float, float]]] = {}
        for name, code, _color in INDICES:
            rows = baostock_kline.fetch_daily_bars(code, start, end)
            series: dict[date, tuple[float, float, float]] = {}
            for bar in rows:
                if bar.high is None or bar.low is None or bar.close is None:
                    continue
                series[bar.trade_date] = (float(bar.high), float(bar.low), float(bar.close))
            if not series:
                raise RuntimeError(f"baostock returned no bars for {name} {code}")
            out[name] = series
        return out
    finally:
        bs.logout()
