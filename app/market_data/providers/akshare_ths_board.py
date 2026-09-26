"""Tonghuashun (THS) industry/concept board provider.

Canonical board identity is Tonghuashun codes:
- industry: 881xxx (also used as kline line code)
- concept: 30xxxx detail code (kline uses cached clid / 88xxxx)

No Eastmoney BK codes or EM fallbacks in this module.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Any, Callable, Literal

import pandas as pd
import requests
from bs4 import BeautifulSoup
from py_mini_racer import MiniRacer

from akshare.stock_feature.stock_board_industry_ths import _get_file_content_ths
from akshare.utils import demjson

from app.market_data.board_cache import load_json, save_json
from app.market_data.normalize import (
    BoardConstituentRow,
    BoardDailyBar,
    BoardUniverseRow,
    from_akshare_ths_board_cons_row,
    from_akshare_ths_board_hist_row,
    from_akshare_ths_board_name_row,
)

BoardType = Literal["industry", "concept"]
SOURCE = "akshare_ths"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_CACHE_INDUSTRY = "ths_industry_name_map.json"
_CACHE_CONCEPT = "ths_concept_name_map.json"
_CACHE_CONCEPT_LINE = "ths_concept_line_codes.json"

NETWORK_RETRIES = 3


def _retry(label: str, fn: Callable[[], Any], *, retries: int = NETWORK_RETRIES) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - network boundary
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"{label} failed after {retries} tries: {last_error}")


def _cookie_v() -> str:
    js_code = MiniRacer()
    js_code.eval(_get_file_content_ths("ths.js"))
    return str(js_code.call("v"))


def _headers(v_code: str | None = None) -> dict[str, str]:
    token = v_code or _cookie_v()
    return {
        "User-Agent": _UA,
        "Cookie": f"v={token}",
        "hexin-v": token,
    }


def _http_get(url: str, *, headers: dict[str, str], timeout: float = 20.0) -> str:
    def _once() -> str:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    return _retry(f"GET {url}", _once)


def _fetch_industry_name_map(*, force: bool = False) -> dict[str, str]:
    if not force:
        cached = load_json(_CACHE_INDUSTRY)
        if isinstance(cached, dict) and cached:
            return {str(k): str(v) for k, v in cached.items()}

    html = _http_get(
        "http://q.10jqka.com.cn/thshy/detail/code/881272/",
        headers=_headers(),
    )
    soup = BeautifulSoup(html, features="lxml")
    box = soup.find(name="div", attrs={"class": "cate_inner"})
    if box is None:
        raise RuntimeError("THS industry cate_inner not found")
    name_map = {
        item.text.strip(): item["href"].split("/")[-2]
        for item in box.find_all("a")
        if item.text.strip() and item.get("href")
    }
    if len(name_map) < 50:
        raise RuntimeError(f"THS industry map too small: {len(name_map)}")
    save_json(_CACHE_INDUSTRY, name_map)
    return name_map


def _fetch_concept_name_map(*, force: bool = False) -> dict[str, str]:
    if not force:
        cached = load_json(_CACHE_CONCEPT)
        if isinstance(cached, dict) and cached:
            return {str(k): str(v) for k, v in cached.items()}

    html = _http_get(
        "http://q.10jqka.com.cn/gn/detail/code/307822/",
        headers=_headers(),
    )
    soup = BeautifulSoup(html, features="lxml")
    box = soup.find(name="div", attrs={"class": "cate_inner"})
    if box is None:
        raise RuntimeError("THS concept cate_inner not found")
    name_map = {
        item.text.strip(): item["href"].split("/")[-2]
        for item in box.find_all("a")
        if item.text.strip() and item.get("href")
    }
    if len(name_map) < 100:
        raise RuntimeError(f"THS concept map too small: {len(name_map)}")
    save_json(_CACHE_CONCEPT, name_map)
    return name_map


def _concept_line_code(url_code: str) -> str:
    cached = load_json(_CACHE_CONCEPT_LINE)
    line_map: dict[str, str] = {}
    if isinstance(cached, dict):
        line_map = {str(k): str(v) for k, v in cached.items()}
    if url_code in line_map:
        return line_map[url_code]

    html = _http_get(
        f"http://q.10jqka.com.cn/gn/detail/code/{url_code}/",
        headers=_headers(),
    )
    soup = BeautifulSoup(html, features="lxml")
    node = soup.find(name="input", attrs={"id": "clid"})
    if node is None or not node.get("value"):
        raise RuntimeError(f"THS concept clid missing for {url_code}")
    line_code = str(node["value"]).strip()
    line_map[url_code] = line_code
    save_json(_CACHE_CONCEPT_LINE, line_map)
    return line_code


def _line_code_for_board(board_type: BoardType, board_code: str) -> str:
    code = board_code.strip()
    if board_type == "industry":
        return code
    return _concept_line_code(code)


def _detail_kind(board_type: BoardType) -> str:
    return "thshy" if board_type == "industry" else "gn"


class BoardUniverseFetchInfo:
    def __init__(
        self,
        rows: list[BoardUniverseRow],
        source: str,
        note: str = "",
        attempts: list[str] | None = None,
    ):
        self.rows = rows
        self.source = source
        self.note = note
        self.attempts = attempts or []


def fetch_board_universe(
    trade_date: date,
    board_type: BoardType | None = None,
) -> BoardUniverseFetchInfo:
    """Fetch Tonghuashun industry/concept board list for one snapshot day."""
    attempts: list[str] = []
    rows: list[BoardUniverseRow] = []

    want_industry = board_type in (None, "industry")
    want_concept = board_type in (None, "concept")

    if want_industry:
        try:
            name_map = _fetch_industry_name_map(force=True)
            for name, code in sorted(name_map.items(), key=lambda item: item[1]):
                rows.append(
                    from_akshare_ths_board_name_row(
                        {"name": name, "code": code},
                        trade_date=trade_date,
                        board_type="industry",
                    )
                )
            attempts.append(f"industry_name_ths: ok ({len(name_map)})")
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"industry_name_ths: fail ({exc})")
            if board_type == "industry":
                raise

    if want_concept:
        try:
            name_map = _fetch_concept_name_map(force=True)
            for name, code in sorted(name_map.items(), key=lambda item: item[1]):
                rows.append(
                    from_akshare_ths_board_name_row(
                        {"name": name, "code": code},
                        trade_date=trade_date,
                        board_type="concept",
                    )
                )
            attempts.append(f"concept_name_ths: ok ({len(name_map)})")
        except Exception as exc:  # noqa: BLE001
            attempts.append(f"concept_name_ths: fail ({exc})")
            if board_type == "concept":
                raise

    if not rows:
        raise RuntimeError("THS board universe empty; " + " | ".join(attempts))

    return BoardUniverseFetchInfo(
        rows,
        source=SOURCE,
        note="tonghuashun name maps",
        attempts=attempts,
    )


def fetch_all_board_universe(
    trade_date: date,
    board_type: BoardType | None = None,
    prior_types: dict[str, str] | None = None,
) -> BoardUniverseFetchInfo:
    """Compatibility wrapper used by sync_board_universe."""
    del prior_types  # THS taxonomy; no EM prior-type carry-over.
    return fetch_board_universe(trade_date, board_type=board_type)


def _fetch_year_lines(line_code: str, year: int, v_code: str) -> list[str]:
    headers = {
        **_headers(v_code),
        "Referer": "http://q.10jqka.com.cn",
        "Host": "d.10jqka.com.cn",
    }
    errors: list[str] = []
    for scheme in ("http", "https"):
        url = f"{scheme}://d.10jqka.com.cn/v4/line/bk_{line_code}/01/{year}.js"

        def _once(url: str = url) -> list[str]:
            text = _http_get(url, headers=headers, timeout=25.0)
            start = text.find("{")
            if start < 0:
                raise RuntimeError("no JSON object in THS year JS")
            payload = demjson.decode(
                text[start:-1] if text.endswith(")") else text[start:]
            )
            data = payload.get("data") if isinstance(payload, dict) else None
            if not data:
                raise RuntimeError("empty THS year data")
            return [part for part in str(data).split(";") if part.strip()]

        try:
            return _retry(f"ths year {year} {scheme}", _once, retries=2)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{scheme}: {exc}")
    raise RuntimeError("; ".join(errors))


def fetch_board_daily_bars(
    board_type: BoardType,
    board_code: str,
    start: date,
    end: date,
    *,
    board_name: str = "",
) -> list[BoardDailyBar]:
    """Fetch THS board index bars keyed by Tonghuashun board_code."""
    del board_name  # identity is board_code; name is display-only
    code = board_code.strip()
    line_code = _line_code_for_board(board_type, code)
    v_code = _cookie_v()
    raw_lines: list[str] = []
    for year in range(start.year, end.year + 1):
        try:
            raw_lines.extend(_fetch_year_lines(line_code, year, v_code))
        except Exception:
            continue
    if not raw_lines:
        raise RuntimeError(
            f"THS returned no year lines for {board_type}:{code} line={line_code}"
        )

    bars: list[BoardDailyBar] = []
    prev_close: Decimal | None = None
    for line in raw_lines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        raw = {
            "日期": parts[0],
            "开盘价": parts[1],
            "最高价": parts[2],
            "最低价": parts[3],
            "收盘价": parts[4],
            "成交量": parts[5],
            "成交额": parts[6] if len(parts) > 6 else None,
        }
        try:
            trade_date = date(
                int(parts[0][:4]),
                int(parts[0][4:6]),
                int(parts[0][6:8]),
            )
        except ValueError:
            continue
        if trade_date < start or trade_date > end:
            try:
                close_val = Decimal(parts[4])
            except Exception:  # noqa: BLE001
                close_val = None
            if trade_date < start and close_val is not None:
                prev_close = close_val
            continue
        bar = from_akshare_ths_board_hist_row(
            raw,
            board_type=board_type,
            board_code=code,
            prev_close=prev_close,
        )
        bars.append(bar)
        if bar.close is not None:
            prev_close = bar.close

    if not bars:
        raise RuntimeError(
            f"THS produced no bars in window for {board_type}:{code}"
        )
    return bars


class BoardConstituentsFetchInfo:
    def __init__(
        self,
        rows: list[BoardConstituentRow],
        source: str,
        attempts: list[str] | None = None,
    ):
        self.rows = rows
        self.source = source
        self.attempts = attempts or []


def _parse_cons_table(html: str) -> tuple[pd.DataFrame, int]:
    soup = BeautifulSoup(html, features="lxml")
    pager = soup.find("span", class_="page_info")
    total_pages = 1
    if pager and "/" in pager.text:
        try:
            total_pages = int(pager.text.strip().split("/")[1])
        except ValueError:
            total_pages = 1
    table = soup.select_one("table.m-table")
    if table is None:
        return pd.DataFrame(), total_pages
    frame = pd.read_html(StringIO(str(table)))[0]
    return frame, total_pages


def fetch_board_constituents(
    trade_date: date,
    board_type: BoardType,
    board_code: str,
) -> BoardConstituentsFetchInfo:
    """Paginate Tonghuashun board detail pages for member stocks."""
    code = board_code.strip()
    kind = _detail_kind(board_type)
    prefix = f"http://q.10jqka.com.cn/{kind}/detail/code/{code}"
    frames: list[pd.DataFrame] = []
    total_pages = 1
    page = 1
    while page <= max(total_pages, 1) and page <= 100:
        url = prefix + "/" if page == 1 else f"{prefix}/page/{page}/"
        html = _http_get(url, headers=_headers(), timeout=25.0)
        frame, detected = _parse_cons_table(html)
        if page == 1:
            total_pages = max(detected, 1)
        if frame.empty:
            break
        frames.append(frame)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.15)

    if not frames:
        raise RuntimeError(f"THS cons empty for {board_type}:{code}")

    big = pd.concat(frames, ignore_index=True)
    rows: list[BoardConstituentRow] = []
    for _, raw in big.iterrows():
        try:
            rows.append(
                from_akshare_ths_board_cons_row(
                    raw.to_dict(),
                    trade_date=trade_date,
                    board_type=board_type,
                    board_code=code,
                )
            )
        except (KeyError, ValueError):
            continue

    dedup: dict[str, BoardConstituentRow] = {}
    for row in rows:
        dedup.setdefault(row.stock_code, row)
    result = list(dedup.values())
    if not result:
        raise RuntimeError(f"THS cons produced no valid rows for {board_type}:{code}")
    return BoardConstituentsFetchInfo(
        result,
        source=SOURCE,
        attempts=[f"ths_detail_pages: ok ({len(result)} rows, pages={total_pages})"],
    )
