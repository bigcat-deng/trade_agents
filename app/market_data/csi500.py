"""CSI 500 (中证500) daily closes for mini-chart benchmarks."""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import baostock as bs

from app.db import fetch_daily_bars_from_db
from app.market_data.providers import baostock_kline

CSI500_CODE = "sh.000905"


def csi500_overlay_for_dates(window_dates: list[date]) -> dict[str, list[float | None]]:
    """Returns, raw volume, and volume mapped onto return σ for the window."""
    if not window_dates:
        return {"returns": [], "volumes": [], "volumes_scaled": []}
    start = window_dates[0] - timedelta(days=14)
    closes, volumes = _split_csi500_bars(fetch_csi500_bars(start, window_dates[-1]))
    return csi500_overlay_series(window_dates, closes=closes, volumes=volumes)


def csi500_overlay_series(
    window_dates: list[date],
    *,
    closes: dict[date, float],
    volumes: dict[date, float],
) -> dict[str, list[float | None]]:
    returns = daily_returns_aligned(window_dates, closes)
    vol_raw: list[float | None] = [volumes.get(day) for day in window_dates]
    return {
        "returns": returns,
        "volumes": vol_raw,
        "volumes_scaled": scale_to_peer_volatility(vol_raw, returns),
    }


def scale_to_peer_volatility(
    source: list[float | None],
    peer: list[float | None],
) -> list[float | None]:
    """Map source onto peer's mean and σ: μ_p + (x-μ_s)/σ_s * σ_p."""
    pairs = [
        (s, p)
        for s, p in zip(source, peer)
        if s is not None and p is not None
    ]
    n = len(pairs)
    empty = [None] * len(source)
    if n < 2:
        return empty
    src_vals = [s for s, _ in pairs]
    peer_vals = [p for _, p in pairs]
    mu_s = sum(src_vals) / n
    mu_p = sum(peer_vals) / n
    var_s = sum((x - mu_s) ** 2 for x in src_vals) / (n - 1)
    var_p = sum((x - mu_p) ** 2 for x in peer_vals) / (n - 1)
    if var_s <= 1e-24 or var_p <= 1e-24:
        return empty
    sig_s = var_s ** 0.5
    sig_p = var_p ** 0.5
    out: list[float | None] = []
    for value in source:
        if value is None:
            out.append(None)
        else:
            out.append(mu_p + (value - mu_s) / sig_s * sig_p)
    return out


def csi500_daily_returns(window_dates: list[date]) -> list[float | None]:
    """Close-to-close CSI 500 returns aligned to ``window_dates`` (None if missing)."""
    return csi500_overlay_for_dates(window_dates)["returns"]


def daily_returns_aligned(
    window_dates: list[date],
    closes: dict[date, float],
) -> list[float | None]:
    """Map each window day to close/prev_close - 1 using the close calendar."""
    ordered = sorted(closes)
    prev_day = {ordered[i]: ordered[i - 1] for i in range(1, len(ordered))}
    out: list[float | None] = []
    for day in window_dates:
        prev = prev_day.get(day)
        c0 = closes.get(prev) if prev is not None else None
        c1 = closes.get(day)
        if c0 is None or c1 is None or c0 == 0.0:
            out.append(None)
        else:
            out.append(c1 / c0 - 1.0)
    return out


def _split_csi500_bars(
    bars: tuple[tuple[date, float, float | None], ...],
) -> tuple[dict[date, float], dict[date, float]]:
    closes: dict[date, float] = {}
    volumes: dict[date, float] = {}
    for day, close, volume in bars:
        closes[day] = close
        if volume is not None:
            volumes[day] = volume
    return closes, volumes


def csi500_close_volume_maps(
    start: date, end: date
) -> tuple[dict[date, float], dict[date, float]]:
    return _split_csi500_bars(fetch_csi500_bars(start, end))


@lru_cache(maxsize=16)
def fetch_csi500_bars(
    start: date, end: date
) -> tuple[tuple[date, float, float | None], ...]:
    """Oldest-first (trade_date, close, volume) for CSI 500 in [start, end]."""
    if end < start:
        return ()
    local = fetch_daily_bars_from_db(CSI500_CODE, start, end)
    bars = _bars_from_rows(local)
    closes = tuple((day, close) for day, close, _vol in bars)
    if _window_looks_complete(closes, start, end):
        return bars
    online = _fetch_baostock_bars(start, end)
    return online if online else bars


@lru_cache(maxsize=16)
def fetch_csi500_closes(start: date, end: date) -> tuple[tuple[date, float], ...]:
    """Return oldest-first (trade_date, close) for CSI 500 in [start, end]."""
    return tuple((day, close) for day, close, _vol in fetch_csi500_bars(start, end))


def _bars_from_rows(
    bars: list[dict],
) -> tuple[tuple[date, float, float | None], ...]:
    rows: list[tuple[date, float, float | None]] = []
    for bar in bars:
        close = bar.get("close")
        if close is None:
            continue
        day = bar["trade_date"]
        if not isinstance(day, date):
            day = date.fromisoformat(str(day)[:10])
        volume = bar.get("volume")
        vol_f: float | None
        try:
            vol_f = float(volume) if volume is not None else None
        except (TypeError, ValueError):
            vol_f = None
        if vol_f is not None and vol_f < 0:
            vol_f = None
        rows.append((day, float(close), vol_f))
    return tuple(rows)


def _window_looks_complete(
    closes: tuple[tuple[date, float], ...],
    start: date,
    end: date,
) -> bool:
    if not closes:
        return False
    span_days = max((end - start).days, 1)
    min_points = max(int(span_days * 0.5), 10)
    return len(closes) >= min_points and closes[-1][0] >= end


def _fetch_baostock_bars(
    start: date, end: date
) -> tuple[tuple[date, float, float | None], ...]:
    login = bs.login()
    if login.error_code != "0":
        return ()
    try:
        bars = baostock_kline.fetch_daily_bars(CSI500_CODE, start, end)
    except Exception:  # noqa: BLE001 - benchmark is optional for the page
        return ()
    finally:
        bs.logout()
    rows: list[tuple[date, float, float | None]] = []
    for bar in bars:
        if bar.close is None:
            continue
        vol = None if bar.volume is None else float(bar.volume)
        rows.append((bar.trade_date, float(bar.close), vol))
    return tuple(rows)
