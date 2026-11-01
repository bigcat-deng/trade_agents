"""Read-only view of stored news snapshots."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import psycopg

from app.db import database_url
from app.market_data.news_daily import NOTICE_TYPES, SHANGHAI, SNAPSHOT_FEEDS

FEED_TITLES = {
    "stock_comment": "千股千评",
    "em_rank": "人气榜",
    "em_surge": "飙升榜",
    "weibo": "微博",
    "stock_notice": "公告",
    "cctv": "联播",
    "cls": "财联社",
    "ths": "同花顺",
}

_COUNT_SQL = """
SELECT day, feed, rows
FROM (
    SELECT trade_date AS day, 'stock_comment' AS feed, COUNT(*) AS rows
    FROM stock_comment_daily
    GROUP BY trade_date
    UNION ALL
    SELECT trade_date, 'em_rank', COUNT(*)
    FROM stock_hot_rank_daily
    WHERE list_name = 'rank'
    GROUP BY trade_date
    UNION ALL
    SELECT trade_date, 'em_surge', COUNT(*)
    FROM stock_hot_rank_daily
    WHERE list_name = 'surge'
    GROUP BY trade_date
    UNION ALL
    SELECT trade_date, 'weibo', COUNT(*)
    FROM stock_weibo_daily
    GROUP BY trade_date
    UNION ALL
    SELECT notice_date, 'stock_notice', COUNT(*)
    FROM stock_notice_daily
    GROUP BY notice_date
    UNION ALL
    SELECT broadcast_date, 'cctv', COUNT(*)
    FROM news_cctv_item
    GROUP BY broadcast_date
) AS counts
"""


def fetch_news_board(day: date | None = None) -> dict[str, Any]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(_COUNT_SQL)
            counts = [(row[0], row[1], int(row[2])) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT feed, snapshot_date, last_status, last_rows, last_error, updated_at
                FROM news_sync_state
                """
            )
            state = {
                row[0]: {
                    "snapshot_date": row[1],
                    "status": row[2],
                    "reported_rows": row[3],
                    "error": row[4],
                    "updated_at": row[5],
                }
                for row in cur.fetchall()
            }
            cur.execute(
                """
                SELECT source, COUNT(*), MIN(published_at), MAX(published_at)
                FROM news_flash
                GROUP BY source
                """
            )
            flashes = {
                row[0]: {"rows": int(row[1]), "start": row[2], "end": row[3]}
                for row in cur.fetchall()
            }
            cur.execute(
                """
                SELECT source, published_at, title, content, url
                FROM news_flash
                ORDER BY published_at DESC, source, title
                LIMIT 5
                """
            )
            latest_flashes = format_flashes(list(cur.fetchall()))
            selected = select_day(day, counts)
            detail = _load_detail(cur, selected) if selected else _empty_detail()
    return assemble_board(
        requested=day,
        selected=selected,
        counts=counts,
        state=state,
        flashes=flashes,
        detail=detail,
        latest_flashes=latest_flashes,
    )


def select_day(
    requested: date | None,
    counts: list[tuple[date, str, int]],
) -> date | None:
    if requested is not None:
        return requested
    comment_days = [day for day, feed, _rows in counts if feed == "stock_comment"]
    if comment_days:
        return max(comment_days)
    if counts:
        return max(day for day, _feed, _rows in counts)
    return None


def format_flashes(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    items = []
    for source, published_at, title, content, url in rows:
        headline = str(title).strip()
        text = str(content or "").strip()
        items.append(
            {
                "source": source,
                "source_label": FEED_TITLES.get(source, source),
                "published_at": _stamp(published_at),
                "title": headline,
                "content": text if text and text != headline else None,
                "url": _href(url),
            }
        )
    return items


def assemble_board(
    *,
    requested: date | None,
    selected: date | None,
    counts: list[tuple[date, str, int]],
    state: dict[str, dict[str, Any]],
    flashes: dict[str, dict[str, Any]],
    detail: dict[str, Any],
    latest_flashes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    by_day: dict[date, dict[str, int]] = {}
    span: dict[str, list[date]] = {feed: [] for feed in SNAPSHOT_FEEDS}
    for day, feed, rows in counts:
        by_day.setdefault(day, {})[feed] = rows
        if feed in span:
            span[feed].append(day)
    if selected is not None and selected not in by_day:
        by_day[selected] = {}

    cards = [_snapshot_card(feed, state.get(feed), span.get(feed, []), by_day) for feed in SNAPSHOT_FEEDS]
    cards.extend(
        _flash_card(source, flashes.get(source), state.get(source))
        for source in ("cls", "ths")
    )

    days = []
    for day in sorted(by_day, reverse=True):
        cells = by_day[day]
        days.append(
            {
                "day": day.isoformat(),
                "selected": day == selected,
                "counts": [cells.get(feed) for feed in SNAPSHOT_FEEDS],
            }
        )

    notes = _detail_notes(selected, state, by_day.get(selected, {}) if selected else {})
    return {
        "selected": selected.isoformat() if selected else None,
        "requested": requested.isoformat() if requested else None,
        "feeds": [FEED_TITLES[feed] for feed in SNAPSHOT_FEEDS],
        "cards": cards,
        "days": days,
        "detail": detail,
        "notes": notes,
        "latest_flashes": latest_flashes or [],
    }


def _snapshot_card(
    feed: str,
    state: dict[str, Any] | None,
    days: list[date],
    by_day: dict[date, dict[str, int]],
) -> dict[str, Any]:
    status = (state or {}).get("status") or "pending"
    snapshot = (state or {}).get("snapshot_date")
    reported = (state or {}).get("reported_rows")
    table_rows = by_day.get(snapshot, {}).get(feed) if snapshot else None
    mismatch = None
    if snapshot is not None and reported is not None and table_rows is not None and int(reported) != table_rows:
        mismatch = f"状态记录 {int(reported)}，表内 {table_rows}"
    error = (state or {}).get("error") if status != "ok" else None
    return {
        "feed": feed,
        "title": FEED_TITLES[feed],
        "status": status,
        "status_label": {"ok": "已入库", "pending": "待重试", "error": "失败"}.get(status, status),
        "snapshot_date": snapshot.isoformat() if snapshot else None,
        "snapshot_rows": table_rows,
        "range_start": min(days).isoformat() if days else None,
        "range_end": max(days).isoformat() if days else None,
        "updated_at": _stamp((state or {}).get("updated_at")),
        "error": error,
        "mismatch": mismatch,
        "idle": False,
    }


def _flash_card(
    source: str,
    flash: dict[str, Any] | None,
    sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = int((flash or {}).get("rows") or 0)
    start = (flash or {}).get("start")
    end = (flash or {}).get("end")
    status = (sync or {}).get("status")
    if status == "error":
        card_status = "error"
        label = "失败"
        idle = False
    elif rows == 0:
        card_status = "idle"
        label = "尚未同步"
        idle = True
    else:
        card_status = "ok"
        label = "已入库"
        idle = False
    return {
        "feed": source,
        "title": FEED_TITLES[source],
        "status": card_status,
        "status_label": label,
        "snapshot_date": None,
        "snapshot_rows": None if idle else rows,
        "range_start": _stamp(start) if start else None,
        "range_end": _stamp(end) if end else None,
        "updated_at": _stamp((sync or {}).get("updated_at")),
        "error": (sync or {}).get("error") if status == "error" else None,
        "mismatch": None,
        "idle": idle,
    }


def _detail_notes(
    selected: date | None,
    state: dict[str, dict[str, Any]],
    cells: dict[str, int],
) -> list[str]:
    if selected is None:
        return []
    notes = []
    for feed in SNAPSHOT_FEEDS:
        item = state.get(feed) or {}
        if item.get("snapshot_date") != selected or item.get("status") == "ok":
            continue
        if not cells.get(feed):
            continue
        reason = item.get("error") or item.get("status")
        notes.append(f"{FEED_TITLES[feed]}最近一次同步未成功（{reason}），下面仍是该日已入库的数据。")
    return notes


def _load_detail(cur: psycopg.Cursor, day: date) -> dict[str, Any]:
    cur.execute(
        """
        SELECT COUNT(*),
               MIN(focus), MAX(focus),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY focus),
               MIN(score), MAX(score),
               percentile_cont(0.5) WITHIN GROUP (ORDER BY score)
        FROM stock_comment_daily
        WHERE trade_date = %s
        """,
        (day,),
    )
    count, focus_min, focus_max, focus_mid, score_min, score_max, score_mid = cur.fetchone()
    cur.execute(
        """
        SELECT code, name, focus, score, rank_no
        FROM stock_comment_daily
        WHERE trade_date = %s AND focus IS NOT NULL
        ORDER BY focus DESC, code
        LIMIT 10
        """,
        (day,),
    )
    focus_top = [
        {
            "code": row[0],
            "name": row[1],
            "href": analyze_href(row[0]),
            "focus": _num(row[2], 1),
            "score": _num(row[3], 1),
            "rank_no": row[4],
        }
        for row in cur.fetchall()
    ]
    cur.execute(
        """
        SELECT code, name, rank_change, rank_no, focus
        FROM stock_comment_daily
        WHERE trade_date = %s AND rank_change IS NOT NULL
        ORDER BY rank_change DESC, code
        LIMIT 10
        """,
        (day,),
    )
    rise_top = [
        {
            "code": row[0],
            "name": row[1],
            "href": analyze_href(row[0]),
            "rank_change": _signed(row[2], 0),
            "rank_no": row[3],
            "focus": _num(row[4], 1),
        }
        for row in cur.fetchall()
    ]
    return {
        "comment": {
            "count": int(count or 0),
            "focus_min": _num(focus_min, 1),
            "focus_mid": _num(focus_mid, 1),
            "focus_max": _num(focus_max, 1),
            "score_min": _num(score_min, 1),
            "score_mid": _num(score_mid, 1),
            "score_max": _num(score_max, 1),
            "focus_top": focus_top,
            "rise_top": rise_top,
        },
        "rank": _hot_list(cur, day, "rank"),
        "surge": _hot_list(cur, day, "surge"),
        "weibo": _weibo(cur, day),
        "notices": _notices(cur, day),
        "cctv": _cctv(cur, day),
    }


def _empty_detail() -> dict[str, Any]:
    return {
        "comment": {
            "count": 0,
            "focus_min": None,
            "focus_mid": None,
            "focus_max": None,
            "score_min": None,
            "score_mid": None,
            "score_max": None,
            "focus_top": [],
            "rise_top": [],
        },
        "rank": [],
        "surge": [],
        "weibo": [],
        "notices": [{"type": name, "count": 0, "items": []} for name in NOTICE_TYPES],
        "cctv": [],
    }


def _hot_list(cur: psycopg.Cursor, day: date, list_name: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT rank_no, code, name, pct_chg, rank_change
        FROM stock_hot_rank_daily
        WHERE trade_date = %s AND list_name = %s
        ORDER BY rank_no NULLS LAST, code
        """,
        (day, list_name),
    )
    return [
        {
            "rank_no": row[0],
            "code": row[1],
            "name": row[2],
            "href": analyze_href(row[1]),
            "pct_chg": _signed(row[3], 2),
            "rank_change": _signed(row[4], 0) if row[4] is not None else None,
        }
        for row in cur.fetchall()
    ]


def _weibo(cur: psycopg.Cursor, day: date) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT name, code, rate
        FROM stock_weibo_daily
        WHERE trade_date = %s
        ORDER BY (code IS NULL) DESC, rate DESC NULLS LAST, name
        """,
        (day,),
    )
    return [
        {
            "name": row[0],
            "code": row[1],
            "href": analyze_href(row[1]),
            "rate": _num(row[2], 2),
        }
        for row in cur.fetchall()
    ]


def _notices(cur: psycopg.Cursor, day: date) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT notice_type, code, name, title, url
        FROM stock_notice_daily
        WHERE notice_date = %s
        ORDER BY notice_type, code, title
        """,
        (day,),
    )
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in NOTICE_TYPES}
    extras: dict[str, list[dict[str, Any]]] = {}
    for notice_type, code, name, title, url in cur.fetchall():
        item = {
            "code": code,
            "name": name,
            "href": analyze_href(code),
            "title": title,
            "url": _href(url),
        }
        if notice_type in grouped:
            grouped[notice_type].append(item)
        else:
            extras.setdefault(notice_type, []).append(item)
    groups = [
        {"type": name, "count": len(grouped[name]), "items": grouped[name]}
        for name in NOTICE_TYPES
    ]
    for name, items in extras.items():
        groups.append({"type": name, "count": len(items), "items": items})
    return groups


def _cctv(cur: psycopg.Cursor, day: date) -> list[dict[str, str]]:
    cur.execute(
        """
        SELECT title, content
        FROM news_cctv_item
        WHERE broadcast_date = %s
        ORDER BY title
        """,
        (day,),
    )
    return [{"title": row[0], "content": row[1] or ""} for row in cur.fetchall()]


def analyze_href(code: str | None) -> str | None:
    """Link a stored baostock code to the 6-character analyze page."""
    if not code:
        return None
    text = code.strip()
    if len(text) == 9 and text[2] == "." and text[:2].lower() in {"sh", "sz", "bj"}:
        symbol = text[3:]
    else:
        symbol = text
    symbol = symbol.upper()
    if len(symbol) != 6 or not symbol.isalnum():
        return None
    return f"/analyze?code={symbol}"


def _href(url: str | None) -> str | None:
    if url and url.startswith(("http://", "https://")):
        return url
    return None


def _num(value: Any, digits: int) -> str | None:
    if value is None:
        return None
    return f"{float(value):.{digits}f}"


def _signed(value: Any, digits: int) -> str | None:
    if value is None:
        return None
    number = float(value)
    text = f"{number:+.{digits}f}"
    return text


def _stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%d %H:%M")
    return value.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M")
