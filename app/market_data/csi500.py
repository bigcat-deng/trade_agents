"""CSI 500 (中证500) daily closes for mini-chart benchmarks."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import baostock as bs

from app.db import fetch_daily_bars_from_db
from app.market_data.providers import baostock_kline

CSI500_CODE = "sh.000905"


@lru_cache(maxsize=16)
def fetch_csi500_closes(start: date, end: date) -> tuple[tuple[date, float], ...]:
    """Return oldest-first (trade_date, close) for CSI 500 in [start, end].

    Prefer local stock_daily_bar; fall back to baostock when the window is empty
    or clearly incomplete.
    """
    if end < start:
        return ()
    local = fetch_daily_bars_from_db(CSI500_CODE, start, end)
    closes = _closes_from_bars(local)
    if _window_looks_complete(closes, start, end):
        return closes
    online = _fetch_baostock_closes(start, end)
    return online if online else closes


def _closes_from_bars(bars: list[dict]) -> tuple[tuple[date, float], ...]:
    rows: list[tuple[date, float]] = []
    for bar in bars:
        close = bar.get("close")
        if close is None:
            continue
        day = bar["trade_date"]
        if not isinstance(day, date):
            day = date.fromisoformat(str(day)[:10])
        rows.append((day, float(close)))
    return tuple(rows)


def _window_looks_complete(
    closes: tuple[tuple[date, float], ...],
    start: date,
    end: date,
) -> bool:
    if not closes:
        return False
    # Rough guard: at least ~70% of calendar span in trading days, and ends near `end`.
    span_days = max((end - start).days, 1)
    min_points = max(int(span_days * 0.5), 10)
    return len(closes) >= min_points and closes[-1][0] >= end


def _fetch_baostock_closes(start: date, end: date) -> tuple[tuple[date, float], ...]:
    login = bs.login()
    if login.error_code != "0":
        return ()
    try:
        bars = baostock_kline.fetch_daily_bars(CSI500_CODE, start, end)
    except Exception:  # noqa: BLE001 - benchmark is optional for the page
        return ()
    finally:
        bs.logout()
    rows: list[tuple[date, float]] = []
    for bar in bars:
        if bar.close is None:
            continue
        rows.append((bar.trade_date, float(bar.close)))
    return tuple(rows)
