"""Per-stock slice of the stored news snapshots for the analyze page."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import psycopg

from app.db import database_url
from app.market_data.codes import to_baostock
from app.market_data.providers.ths_line import INDEX_NAMES
from app.news_board import _href, _num, _signed, _stamp, format_flashes

NOTICE_LIMIT = 8
FLASH_LIMIT = 5
_EXCERPT = 160


def safe_stock_news(ths_code: str) -> dict[str, Any]:
    """Never let a news read failure take down the chart page."""
    try:
        return load_stock_news(ths_code)
    except Exception:
        return {"kind": "error", "message": "个股资讯暂时读不出来。"}


def load_stock_news(ths_code: str) -> dict[str, Any]:
    """News for one analyze-page code. Indexes have no stock rows."""
    if ths_code in INDEX_NAMES:
        return {"kind": "index", "message": "指数没有个股资讯。"}
    try:
        code = to_baostock(ths_code)
    except ValueError:
        return {"kind": "index", "message": "这个代码没有对应的个股资讯。"}
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            queried = _query(cur, code)
    return assemble_stock_news(code=code, **queried)


def like_pattern(name: str) -> str:
    """Substring match that treats ``%`` and ``_`` in a name as literal."""
    escaped = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def focus_sparkline(points: list[tuple[date, float]]) -> dict[str, str] | None:
    """Polyline of daily focus. One observation has no line."""
    if len(points) < 2:
        return None
    values = [value for _day, value in points]
    low = min(values)
    high = max(values)
    span = high - low or 1.0
    last = len(points) - 1
    coords = []
    for index, (_day, value) in enumerate(points):
        x = 4 + (272 * index / last)
        y = 8 + (56 * (1 - (value - low) / span))
        coords.append(f"{x:.1f},{y:.1f}")
    return {
        "points": " ".join(coords),
        "start": points[0][0].isoformat(),
        "end": points[-1][0].isoformat(),
        "low": f"{low:.1f}",
        "high": f"{high:.1f}",
    }


def assemble_stock_news(
    *,
    code: str,
    name: str | None,
    as_of: date | None,
    comments: list[tuple[Any, ...]],
    rank_listed: bool,
    rank: tuple[Any, ...] | None,
    surge_listed: bool,
    surge: tuple[Any, ...] | None,
    weibo: list[tuple[Any, ...]],
    weibo_listed: bool = False,
    notices: list[tuple[Any, ...]],
    flashes: list[tuple[Any, ...]],
    cctv_listed: bool,
    cctv: list[tuple[Any, ...]],
) -> dict[str, Any]:
    """Shape already-fetched rows. ``comments`` are oldest first."""
    clean_name = name.strip() if name and name.strip() else None
    comment_rows = [_comment_row(row) for row in comments]
    on_day = next((row for row in comment_rows if row["day"] == _iso(as_of)), None)
    focus_points = [
        (date.fromisoformat(row["day"]), float(row["focus"]))
        for row in comment_rows
        if row["focus"] is not None
    ]
    return {
        "kind": "stock",
        "code": code,
        "name": clean_name,
        "as_of": _iso(as_of),
        "news_href": f"/news?day={as_of.isoformat()}" if as_of else "/news",
        "comment": on_day,
        "comment_missing": as_of is not None and on_day is None,
        "sparkline": focus_sparkline(focus_points),
        "rank": _list_card(rank_listed, rank, as_of),
        "surge": _list_card(surge_listed, surge, as_of),
        "weibo": [_weibo_row(row) for row in weibo],
        "weibo_note": _weibo_note(as_of, weibo_listed, weibo),
        "notices": [_notice_row(row) for row in notices],
        "flashes": _clip_flashes(format_flashes(flashes)),
        "flash_note": _name_note(clean_name, "没有提到"),
        "cctv": [_cctv_row(row) for row in cctv],
        "cctv_note": _cctv_note(clean_name, as_of, cctv_listed, cctv),
    }


def _query(cur: psycopg.Cursor, code: str) -> dict[str, Any]:
    cur.execute("SELECT MAX(trade_date) FROM stock_comment_daily")
    as_of = cur.fetchone()[0]
    cur.execute(
        """
        SELECT code_name
        FROM stock_universe_daily
        WHERE code = %s
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (code,),
    )
    name_row = cur.fetchone()
    name = name_row[0] if name_row else None
    cur.execute(
        """
        SELECT trade_date, name, focus, score, rank_no, rank_change
        FROM stock_comment_daily
        WHERE code = %s
        ORDER BY trade_date
        """,
        (code,),
    )
    comments = list(cur.fetchall())
    if not name and comments:
        name = comments[-1][1]
    rank_listed, rank = _hot_row(cur, as_of, code, "rank")
    surge_listed, surge = _hot_row(cur, as_of, code, "surge")
    weibo: list[tuple[Any, ...]] = []
    weibo_listed = False
    if as_of is not None:
        cur.execute(
            "SELECT 1 FROM stock_weibo_daily WHERE trade_date = %s LIMIT 1",
            (as_of,),
        )
        weibo_listed = cur.fetchone() is not None
        cur.execute(
            """
            SELECT time_period, rate
            FROM stock_weibo_daily
            WHERE trade_date = %s AND code = %s
            ORDER BY time_period
            """,
            (as_of, code),
        )
        weibo = list(cur.fetchall())
    cur.execute(
        """
        SELECT notice_date, notice_type, title, url
        FROM stock_notice_daily
        WHERE code = %s
        ORDER BY notice_date DESC, title
        LIMIT %s
        """,
        (code, NOTICE_LIMIT),
    )
    notices = list(cur.fetchall())
    flashes: list[tuple[Any, ...]] = []
    cctv_listed = False
    cctv: list[tuple[Any, ...]] = []
    if name and str(name).strip():
        pattern = like_pattern(str(name).strip())
        cur.execute(
            """
            SELECT source, published_at, title, content, url
            FROM news_flash
            WHERE title LIKE %s ESCAPE '\\'
               OR COALESCE(content, '') LIKE %s ESCAPE '\\'
            ORDER BY published_at DESC, source, title
            LIMIT %s
            """,
            (pattern, pattern, FLASH_LIMIT),
        )
        flashes = list(cur.fetchall())
        if as_of is not None:
            cur.execute(
                "SELECT 1 FROM news_cctv_item WHERE broadcast_date = %s LIMIT 1",
                (as_of,),
            )
            cctv_listed = cur.fetchone() is not None
            cur.execute(
                """
                SELECT title, content
                FROM news_cctv_item
                WHERE broadcast_date = %s
                  AND (
                    title LIKE %s ESCAPE '\\'
                    OR COALESCE(content, '') LIKE %s ESCAPE '\\'
                  )
                ORDER BY title
                """,
                (as_of, pattern, pattern),
            )
            cctv = list(cur.fetchall())
    return {
        "name": None if name is None else str(name),
        "as_of": as_of,
        "comments": comments,
        "rank_listed": rank_listed,
        "rank": rank,
        "surge_listed": surge_listed,
        "surge": surge,
        "weibo": weibo,
        "weibo_listed": weibo_listed,
        "notices": notices,
        "flashes": flashes,
        "cctv_listed": cctv_listed,
        "cctv": cctv,
    }


def _hot_row(
    cur: psycopg.Cursor,
    day: date | None,
    code: str,
    list_name: str,
) -> tuple[bool, tuple[Any, ...] | None]:
    if day is None:
        return False, None
    cur.execute(
        """
        SELECT 1
        FROM stock_hot_rank_daily
        WHERE trade_date = %s AND list_name = %s
        LIMIT 1
        """,
        (day, list_name),
    )
    listed = cur.fetchone() is not None
    if not listed:
        return False, None
    cur.execute(
        """
        SELECT rank_no, rank_change, pct_chg
        FROM stock_hot_rank_daily
        WHERE trade_date = %s AND list_name = %s AND code = %s
        """,
        (day, list_name, code),
    )
    return True, cur.fetchone()


def _comment_row(row: tuple[Any, ...]) -> dict[str, Any]:
    trade_date, _name, focus, score, rank_no, rank_change = row
    return {
        "day": _iso(trade_date),
        "focus": _num(focus, 1),
        "score": _num(score, 1),
        "rank_no": rank_no,
        "rank_change": _signed(rank_change, 0) if rank_change is not None else None,
    }


def _list_card(
    listed: bool,
    row: tuple[Any, ...] | None,
    as_of: date | None,
) -> dict[str, Any]:
    if as_of is None:
        return {"state": "missing", "label": "还没有榜单日期"}
    if not listed:
        return {"state": "missing", "label": "该日尚未入库"}
    if row is None:
        return {"state": "off", "label": "未上榜"}
    rank_no, rank_change, pct_chg = row
    return {
        "state": "on",
        "label": None,
        "rank_no": rank_no,
        "rank_change": _signed(rank_change, 0) if rank_change is not None else None,
        "pct_chg": _signed(pct_chg, 2) if pct_chg is not None else None,
    }


_WEIBO_PERIODS = {
    "CNHOUR2": "近 2 小时",
    "CNHOUR6": "近 6 小时",
    "CNHOUR12": "近 12 小时",
    "CNHOUR24": "近 24 小时",
    "CNDAY7": "近 1 周",
    "CNDAY30": "近 1 月",
}


def _weibo_note(
    as_of: date | None,
    listed: bool,
    rows: list[tuple[Any, ...]],
) -> str | None:
    if rows:
        return None
    if as_of is None:
        return "还没有榜单日期"
    if not listed:
        return "该日尚未入库"
    return "未上榜"


def _weibo_row(row: tuple[Any, ...]) -> dict[str, Any]:
    period, rate = row
    return {"period": _WEIBO_PERIODS.get(str(period), str(period)), "rate": _num(rate, 2)}


def _notice_row(row: tuple[Any, ...]) -> dict[str, Any]:
    notice_date, notice_type, title, url = row
    return {
        "day": _iso(notice_date),
        "type": notice_type,
        "title": title,
        "url": _href(url),
    }


def _cctv_row(row: tuple[Any, ...]) -> dict[str, str]:
    title, content = row
    text = " ".join(str(content or "").split())
    if len(text) > _EXCERPT:
        text = text[:_EXCERPT] + "…"
    return {"title": str(title), "content": text}


def _clip_flashes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clipped = []
    for item in items:
        content = item.get("content")
        if content and len(content) > _EXCERPT:
            content = content[:_EXCERPT] + "…"
        clipped.append({**item, "content": content})
    return clipped


def _name_note(name: str | None, empty: str) -> str:
    if not name:
        return "没有证券简称，未按名称检索"
    return f"{empty}「{name}」"


def _cctv_note(
    name: str | None,
    as_of: date | None,
    listed: bool,
    hits: list[tuple[Any, ...]],
) -> str | None:
    if hits:
        return None
    if not name:
        return "没有证券简称，未检索联播"
    if as_of is None:
        return "还没有联播日期"
    if not listed:
        return "该日联播尚未入库"
    return "当日联播未提及"


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()
