"""ETF share outstanding (规模) from exchange fund lists."""

from __future__ import annotations

import io
import time
import warnings
from datetime import date, timedelta

import pandas as pd
import requests

_CACHE: tuple[float, dict[str, float]] | None = None
_CACHE_TTL_SEC = 6 * 3600


def fetch_etf_share_map(*, force: bool = False) -> dict[str, float]:
    """Six-digit code → 基金份额. Soft-fails to {} if a source is down."""
    global _CACHE
    now = time.monotonic()
    if not force and _CACHE is not None and now - _CACHE[0] < _CACHE_TTL_SEC:
        return _CACHE[1]
    shares: dict[str, float] = {}
    shares.update(_sse_shares())
    shares.update(_szse_shares())
    _CACHE = (now, shares)
    return shares


def format_share_scale(shares: float | None) -> str:
    """Legacy: share outstanding in 亿份."""
    if shares is None or shares <= 0:
        return "—"
    yi = shares / 1e8
    if yi >= 100:
        return f"{yi:.0f}亿份"
    if yi >= 10:
        return f"{yi:.1f}亿份"
    return f"{yi:.2f}亿份"


def format_aum_yi(shares: float | None, price: float | None) -> str:
    """Approx AUM in 亿元: 份额 × 市价 / 1e8."""
    if shares is None or shares <= 0 or price is None or price <= 0:
        return "—"
    yi = shares * price / 1e8
    if yi >= 100:
        return f"{yi:.0f}亿"
    if yi >= 10:
        return f"{yi:.1f}亿"
    if yi >= 1:
        return f"{yi:.2f}亿"
    return f"{yi:.3f}亿"


def _sse_shares() -> dict[str, float]:
    try:
        import akshare as ak
    except ImportError:
        return {}
    for day in _recent_weekdays(date.today(), 10):
        try:
            frame = ak.fund_etf_scale_sse(date=day.strftime("%Y%m%d"))
        except Exception:
            continue
        if frame is None or frame.empty:
            continue
        return _shares_from_frame(frame, code_col="基金代码", share_col="基金份额")
    return {}


def _szse_shares() -> dict[str, float]:
    """SZSE xlsx list; akshare's reader rejects raw bytes, so decode here."""
    url = "https://fund.szse.cn/api/report/ShowReport"
    params = {
        "SHOWTYPE": "xlsx",
        "CATALOGID": "1000_lf",
        "TABKEY": "tab1",
        "random": "0.07610353191740105",
    }
    headers = {
        "Referer": "https://fund.szse.cn/marketdata/fundslist/index.html",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            frame = pd.read_excel(
                io.BytesIO(response.content),
                engine="openpyxl",
                dtype={"基金代码": str},
            )
    except Exception:
        return {}
    if frame is None or frame.empty:
        return {}
    share_col = "基金份额" if "基金份额" in frame.columns else "当前规模(份)"
    if share_col not in frame.columns or "基金代码" not in frame.columns:
        return {}
    return _shares_from_frame(frame, code_col="基金代码", share_col=share_col)


def _shares_from_frame(
    frame: pd.DataFrame,
    *,
    code_col: str,
    share_col: str,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for _, row in frame.iterrows():
        raw_code = str(row.get(code_col) or "").strip()
        digits = "".join(ch for ch in raw_code if ch.isdigit())
        if len(digits) > 6:
            digits = digits[-6:]
        if len(digits) != 6:
            continue
        raw_share = row.get(share_col)
        try:
            if isinstance(raw_share, str):
                raw_share = raw_share.replace(",", "")
            value = float(raw_share)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[digits] = value
    return out


def _recent_weekdays(tip: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = tip
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return days
