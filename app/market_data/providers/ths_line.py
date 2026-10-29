"""Daily bars from Tonghuashun's line service, looked up by code.

Stocks and ETFs are six digits, such as ``600519``. Tonghuashun's own index
codes, such as ``1A0001``, are sent unchanged. The request uses the same
``d.10jqka.com.cn`` yearly line that akshare uses for board indices.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date

import py_mini_racer
import requests
from akshare.datasets import get_ths_js
from akshare.utils import demjson

_CODE = re.compile(r"^[0-9A-Z]{6}$")
_COOKIE_LOCK = threading.Lock()
_COOKIE: tuple[float, str] | None = None
_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "http://q.10jqka.com.cn",
    "Host": "d.10jqka.com.cn",
}

# Tonghuashun index codes. Six-digit stock and ETF codes are not listed here.
INDEX_NAMES = {
    "1A0001": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "1B0016": "上证50",
    "1B0300": "沪深300",
    "1B0905": "中证500",
    "1B0852": "中证1000",
    "1B0688": "科创50",
    "399303": "国证2000",
}


def normalize_ths_code(raw: str) -> str:
    """Accept a 6-character stock, ETF, or Tonghuashun code."""
    text = raw.strip().upper()
    if not _CODE.fullmatch(text):
        raise ValueError("请输入 6 位代码，例如 600519 或 1A0001")
    return text


def line_symbol(code: str) -> str:
    return f"hs_{normalize_ths_code(code)}"


def fetch_ths_daily_bars(
    code: str,
    start: date,
    end: date,
    *,
    attempts: int = 3,
) -> list[dict]:
    """Unadjusted daily bars from ``start`` through ``end``, ordered by date.

    Tonghuashun occasionally returns an empty body on a cold cookie; retry a
    few times before treating the code as missing.
    """
    global _COOKIE
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")
    last_error: RuntimeError | None = None
    for attempt in range(max(1, attempts)):
        symbol = line_symbol(code)
        cookie = _ths_cookie()
        rows: list[dict] = []
        for year in range(start.year, end.year + 1):
            rows.extend(_fetch_year(symbol, year, cookie))
        kept = [row for row in rows if start <= row["trade_date"] <= end]
        kept.sort(key=lambda row: row["trade_date"])
        deduped: list[dict] = []
        seen: set[date] = set()
        for row in kept:
            if row["trade_date"] in seen:
                continue
            seen.add(row["trade_date"])
            deduped.append(row)
        if deduped:
            return deduped
        last_error = RuntimeError("同花顺没有这个代码的日K")
        if attempt + 1 < max(1, attempts):
            time.sleep(0.2 * (attempt + 1))
            # Force a fresh cookie on the next try.
            with _COOKIE_LOCK:
                _COOKIE = None
    raise last_error or RuntimeError("同花顺没有这个代码的日K")


def _ths_cookie() -> str:
    """One V8 isolate at a time. Concurrent MiniRacer startups abort the process."""
    global _COOKIE
    now = time.monotonic()
    with _COOKIE_LOCK:
        if _COOKIE is not None and now - _COOKIE[0] < 30:
            return _COOKIE[1]
        js = py_mini_racer.MiniRacer()
        with open(get_ths_js("ths.js"), encoding="utf-8") as handle:
            js.eval(handle.read())
        value = f"v={js.call('v')}"
        _COOKIE = (now, value)
        return value


def _fetch_year(symbol: str, year: int, cookie: str) -> list[dict]:
    url = f"https://d.10jqka.com.cn/v4/line/{symbol}/01/{year}.js"
    headers = {**_HEADERS, "Cookie": cookie}
    response = None
    for _attempt in range(2):
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 502:
            break
    if response is None or response.status_code == 404 or not response.text:
        return []
    if response.status_code != 200 or "data" not in response.text:
        return []
    return _bars_from_body(response.text)


def _bars_from_body(body: str) -> list[dict]:
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end <= start:
        return []
    payload = demjson.decode(body[start : end + 1])
    raw = payload.get("data") if isinstance(payload, dict) else None
    if not raw:
        return []
    rows: list[dict] = []
    for piece in str(raw).split(";"):
        fields = piece.split(",")
        if len(fields) < 6 or len(fields[0]) != 8:
            continue
        try:
            trade_date = date(int(fields[0][:4]), int(fields[0][4:6]), int(fields[0][6:8]))
            rows.append(
                {
                    "trade_date": trade_date,
                    "open": float(fields[1]),
                    "high": float(fields[2]),
                    "low": float(fields[3]),
                    "close": float(fields[4]),
                    "volume": float(fields[5]),
                }
            )
        except ValueError:
            continue
    return rows
