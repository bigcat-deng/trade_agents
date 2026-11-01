"""Read-only coverage stats for the sync dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import psycopg

from app.db import A_SHARE_CODE_FILTER_SQL, database_url


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def previous_weekday(today: date | None = None) -> date:
    """Most recent Mon–Fri strictly before `today` (calendar weekends skipped)."""
    day = (today or date.today()) - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _suggested_day(existing: date | None) -> str:
    return _iso(existing) or previous_weekday().isoformat()


def fetch_sync_dashboard_status() -> list[dict[str, Any]]:
    """Return one status dict per syncable dataset."""
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            return [
                _stock_universe(cur),
                _stock_daily_bars(cur),
                _stock_heat(cur),
                _board_universe(cur),
                _board_daily_bars(cur),
                _board_heat(cur),
                _board_constituents(cur),
                _news_daily(cur),
                _news_flash(cur),
            ]


def _stock_universe(cur: psycopg.Cursor) -> dict[str, Any]:
    cur.execute(
        """
        SELECT MAX(trade_date), COUNT(*) FILTER (
            WHERE trade_date = (SELECT MAX(trade_date) FROM stock_universe_daily)
        ), MAX(ingested_at)
        FROM stock_universe_daily
        """
    )
    latest_day, rows, last_ingest = cur.fetchone()
    cur.execute(
        f"""
        SELECT COUNT(*)
        FROM stock_universe_daily AS s
        WHERE s.trade_date = %s
          AND s.trade_status = 1
          AND {A_SHARE_CODE_FILTER_SQL}
        """,
        (latest_day,),
    )
    trading_a = cur.fetchone()[0] if latest_day else 0
    return {
        "job_id": "stock_universe",
        "title": "个股名单",
        "table": "stock_universe_daily",
        "snapshot_date": _iso(latest_day),
        "covered": int(rows or 0),
        "target": int(rows or 0),
        "detail": f"最新日全市场 {int(rows or 0)}，其中交易中 A 股 {int(trading_a or 0)}",
        "data_start": _iso(latest_day),
        "data_end": _iso(latest_day),
        "last_synced_at": _iso(last_ingest),
        "supports_trading_days": False,
        "supports_resume": False,
        "supports_day": True,
        "suggested_day": _suggested_day(latest_day),
        "complete": bool(latest_day),
    }


def _stock_daily_bars(cur: psycopg.Cursor) -> dict[str, Any]:
    cur.execute("SELECT MAX(trade_date) FROM stock_universe_daily")
    uni_day = cur.fetchone()[0]
    target = 0
    if uni_day is not None:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM stock_universe_daily AS s
            WHERE s.trade_date = %s
              AND s.trade_status = 1
              AND {A_SHARE_CODE_FILTER_SQL}
            """,
            (uni_day,),
        )
        target = int(cur.fetchone()[0] or 0)

    cur.execute(
        """
        SELECT COUNT(DISTINCT code), MIN(trade_date), MAX(trade_date), MAX(ingested_at)
        FROM stock_daily_bar
        """
    )
    covered, data_start, data_end, last_ingest = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*) FILTER (WHERE last_status = 'ok'),
               COUNT(*) FILTER (WHERE last_status = 'error'),
               MAX(updated_at)
        FROM stock_daily_bar_sync_state
        """
    )
    ok_n, err_n, last_sync = cur.fetchone()

    covered_n = int(covered or 0)
    return {
        "job_id": "stock_daily_bars",
        "title": "个股日 K",
        "table": "stock_daily_bar",
        "snapshot_date": _iso(uni_day),
        "covered": covered_n,
        "target": target,
        "detail": f"有 K 线代码 {covered_n}/{target}；sync ok={int(ok_n or 0)} error={int(err_n or 0)}",
        "data_start": _iso(data_start),
        "data_end": _iso(data_end),
        "last_synced_at": _iso(last_sync or last_ingest),
        "supports_trading_days": True,
        "supports_resume": True,
        "supports_day": False,
        "suggested_day": None,
        "complete": target > 0 and covered_n >= target,
    }


def _stock_heat(cur: psycopg.Cursor) -> dict[str, Any]:
    cur.execute(
        """
        SELECT
            (SELECT MAX(trade_date) FROM stock_daily_bar),
            (SELECT MAX(trade_date) FROM stock_heat_daily),
            (SELECT MIN(trade_date) FROM stock_heat_daily),
            (SELECT COUNT(DISTINCT code) FROM stock_heat_daily
             WHERE trade_date = (SELECT MAX(trade_date) FROM stock_heat_daily)),
            (SELECT MAX(ingested_at) FROM stock_heat_daily)
        """
    )
    bars_end, heat_end, heat_start, codes_n, last_ingest = cur.fetchone()

    def _day(value: date | None) -> str:
        return value.isoformat() if value is not None else "—"

    aligned = bars_end is not None and heat_end == bars_end
    return {
        "job_id": "stock_heat",
        "title": "个股短热",
        "table": "stock_heat_daily",
        "snapshot_date": None,
        "covered": 1 if aligned else 0,
        "target": 1,
        "detail": (
            f"短热至 {_day(heat_end)}，日 K 至 {_day(bars_end)}；"
            f"最新日代码数 {int(codes_n or 0)}"
        ),
        "data_start": _iso(heat_start),
        "data_end": _iso(heat_end),
        "last_synced_at": _iso(last_ingest),
        "supports_trading_days": True,
        "supports_resume": False,
        "supports_day": False,
        "suggested_day": None,
        "action_label": "计算短热",
        "complete": aligned,
    }


def _board_universe(cur: psycopg.Cursor) -> dict[str, Any]:
    cur.execute(
        """
        SELECT MAX(trade_date),
               COUNT(*) FILTER (
                   WHERE trade_date = (SELECT MAX(trade_date) FROM board_universe_daily)
               ),
               COUNT(*) FILTER (
                   WHERE trade_date = (SELECT MAX(trade_date) FROM board_universe_daily)
                     AND board_type = 'industry'
               ),
               COUNT(*) FILTER (
                   WHERE trade_date = (SELECT MAX(trade_date) FROM board_universe_daily)
                     AND board_type = 'concept'
               ),
               MAX(ingested_at)
        FROM board_universe_daily
        """
    )
    latest_day, total, industry_n, concept_n, last_ingest = cur.fetchone()
    total_n = int(total or 0)
    return {
        "job_id": "board_universe",
        "title": "板块名单",
        "table": "board_universe_daily",
        "snapshot_date": _iso(latest_day),
        "covered": total_n,
        "target": total_n,
        "detail": f"行业 {int(industry_n or 0)} + 概念 {int(concept_n or 0)}",
        "data_start": _iso(latest_day),
        "data_end": _iso(latest_day),
        "last_synced_at": _iso(last_ingest),
        "supports_trading_days": False,
        "supports_resume": False,
        "supports_day": True,
        "suggested_day": _suggested_day(latest_day),
        "complete": total_n > 0,
    }


def _board_coverage_against_universe(
    cur: psycopg.Cursor, table: str
) -> tuple[int, int, int, int]:
    """Return universe, covered, industry_missing, concept_missing for board child table."""
    allowed = {"board_daily_bar", "board_constituent_daily"}
    if table not in allowed:
        raise ValueError(f"unsupported table: {table}")

    cur.execute("SELECT MAX(trade_date) FROM board_universe_daily")
    uni_day = cur.fetchone()[0]
    if uni_day is None:
        return 0, 0, 0, 0

    # Table name is whitelisted; keep placeholders as plain %s for psycopg.
    sql = (
        "WITH uni AS ("
        "  SELECT board_type, board_code"
        "  FROM board_universe_daily"
        "  WHERE trade_date = %s"
        "), have AS ("
        f"  SELECT DISTINCT board_type, board_code FROM {table}"
        ") "
        "SELECT"
        "  (SELECT COUNT(*) FROM uni),"
        "  (SELECT COUNT(*) FROM uni u"
        "   JOIN have h ON h.board_type = u.board_type AND h.board_code = u.board_code),"
        "  (SELECT COUNT(*) FROM uni u"
        "   WHERE u.board_type = 'industry'"
        "     AND NOT EXISTS ("
        "       SELECT 1 FROM have h"
        "       WHERE h.board_type = u.board_type AND h.board_code = u.board_code"
        "     )),"
        "  (SELECT COUNT(*) FROM uni u"
        "   WHERE u.board_type = 'concept'"
        "     AND NOT EXISTS ("
        "       SELECT 1 FROM have h"
        "       WHERE h.board_type = u.board_type AND h.board_code = u.board_code"
        "     ))"
    )
    cur.execute(sql, (uni_day,))
    universe, covered, ind_miss, con_miss = cur.fetchone()
    return int(universe or 0), int(covered or 0), int(ind_miss or 0), int(con_miss or 0)


def _board_daily_bars(cur: psycopg.Cursor) -> dict[str, Any]:
    universe, covered, ind_miss, con_miss = _board_coverage_against_universe(
        cur, "board_daily_bar"
    )
    cur.execute(
        """
        SELECT MIN(trade_date), MAX(trade_date), MAX(ingested_at)
        FROM board_daily_bar
        """
    )
    data_start, data_end, last_ingest = cur.fetchone()
    cur.execute(
        """
        SELECT COUNT(*) FILTER (WHERE last_status = 'ok'),
               COUNT(*) FILTER (WHERE last_status = 'error'),
               MAX(updated_at)
        FROM board_daily_bar_sync_state
        """
    )
    ok_n, err_n, last_sync = cur.fetchone()
    return {
        "job_id": "board_daily_bars",
        "title": "板块日 K",
        "table": "board_daily_bar",
        "snapshot_date": None,
        "covered": covered,
        "target": universe,
        "detail": (
            f"有 K 线板块 {covered}/{universe}；"
            f"缺行业 {ind_miss} 概念 {con_miss}；"
            f"sync ok={int(ok_n or 0)} error={int(err_n or 0)}"
        ),
        "data_start": _iso(data_start),
        "data_end": _iso(data_end),
        "last_synced_at": _iso(last_sync or last_ingest),
        "supports_trading_days": True,
        "supports_resume": True,
        "supports_day": False,
        "suggested_day": None,
        "complete": universe > 0 and covered >= universe,
    }


def _board_heat(cur: psycopg.Cursor) -> dict[str, Any]:
    cur.execute(
        """
        SELECT
            (SELECT MAX(trade_date) FROM board_daily_bar WHERE board_type = 'industry'),
            (SELECT MAX(trade_date) FROM board_heat_daily WHERE board_type = 'industry'),
            (SELECT MAX(trade_date) FROM board_daily_bar WHERE board_type = 'concept'),
            (SELECT MAX(trade_date) FROM board_heat_daily WHERE board_type = 'concept'),
            (SELECT MIN(trade_date) FROM board_heat_daily),
            (SELECT MAX(trade_date) FROM board_heat_daily),
            (SELECT MAX(ingested_at) FROM board_heat_daily)
        """
    )
    industry_bars, industry_heat, concept_bars, concept_heat, heat_start, heat_end, last_ingest = (
        cur.fetchone()
    )
    aligned = 0
    for bars_end, heat_day in (
        (industry_bars, industry_heat),
        (concept_bars, concept_heat),
    ):
        if bars_end is not None and heat_day == bars_end:
            aligned += 1

    def _day(value: date | None) -> str:
        return value.isoformat() if value is not None else "—"

    return {
        "job_id": "board_heat",
        "title": "板块热度",
        "table": "board_heat_daily",
        "snapshot_date": None,
        "covered": aligned,
        "target": 2,
        "detail": (
            f"行业热度至 {_day(industry_heat)}，日 K 至 {_day(industry_bars)}；"
            f"概念热度至 {_day(concept_heat)}，日 K 至 {_day(concept_bars)}"
        ),
        "data_start": _iso(heat_start),
        "data_end": _iso(heat_end),
        "last_synced_at": _iso(last_ingest),
        "supports_trading_days": False,
        "supports_resume": False,
        "supports_day": False,
        "suggested_day": None,
        "action_label": "计算热度",
        "complete": aligned == 2,
    }


def _board_constituents(cur: psycopg.Cursor) -> dict[str, Any]:
    universe, covered, ind_miss, con_miss = _board_coverage_against_universe(
        cur, "board_constituent_daily"
    )
    cur.execute("SELECT MAX(trade_date) FROM board_universe_daily")
    uni_day = cur.fetchone()[0]
    cur.execute(
        """
        SELECT COUNT(*), MIN(trade_date), MAX(trade_date), MAX(ingested_at)
        FROM board_constituent_daily
        """
    )
    rows, data_start, data_end, last_ingest = cur.fetchone()
    cur.execute(
        """
        SELECT COUNT(*) FILTER (WHERE last_status = 'ok'),
               COUNT(*) FILTER (WHERE last_status = 'error'),
               MAX(updated_at),
               MAX(snapshot_date)
        FROM board_constituent_sync_state
        """
    )
    ok_n, err_n, last_sync, snap = cur.fetchone()
    return {
        "job_id": "board_constituents",
        "title": "板块成分",
        "table": "board_constituent_daily",
        "snapshot_date": _iso(snap or data_end),
        "covered": covered,
        "target": universe,
        "detail": (
            f"有成分板块 {covered}/{universe}（{int(rows or 0)} 行）；"
            f"缺行业 {ind_miss} 概念 {con_miss}；"
            f"sync ok={int(ok_n or 0)} error={int(err_n or 0)}"
        ),
        "data_start": _iso(data_start),
        "data_end": _iso(data_end),
        "last_synced_at": _iso(last_sync or last_ingest),
        "supports_trading_days": False,
        "supports_resume": True,
        "supports_day": True,
        "suggested_day": _suggested_day(uni_day or snap or data_end),
        "complete": universe > 0 and covered >= universe,
    }


_NEWS_FEED_LABELS = (
    ("stock_comment", "千股千评"),
    ("em_rank", "人气榜"),
    ("em_surge", "飙升榜"),
    ("weibo", "微博"),
    ("stock_notice", "公告"),
    ("cctv", "联播"),
)


def _news_daily(cur: psycopg.Cursor) -> dict[str, Any]:
    feeds = [feed for feed, _label in _NEWS_FEED_LABELS]
    cur.execute(
        """
        SELECT feed, snapshot_date, last_status, last_rows, last_error, updated_at
        FROM news_sync_state
        WHERE feed = ANY(%s)
        """,
        (feeds,),
    )
    by_feed = {row[0]: row for row in cur.fetchall()}
    parts: list[str] = []
    ok_n = 0
    last_sync = None
    comment_day = None
    for feed, label in _NEWS_FEED_LABELS:
        row = by_feed.get(feed)
        status = row[2] if row else "pending"
        rows = int(row[3] or 0) if row else 0
        error = row[4] if row else None
        updated = row[5] if row else None
        if status == "ok":
            ok_n += 1
        if updated is not None and (last_sync is None or updated > last_sync):
            last_sync = updated
        if feed == "stock_comment" and row is not None:
            comment_day = row[1]
        text = f"{label} {status} {rows}"
        if error and status != "ok":
            text += f"（{error}）"
        parts.append(text)

    cur.execute(
        """
        SELECT MIN(trade_date), MAX(trade_date), MAX(ingested_at)
        FROM stock_comment_daily
        """
    )
    data_start, data_end, last_ingest = cur.fetchone()
    target = len(_NEWS_FEED_LABELS)
    return {
        "job_id": "news_daily",
        "title": "新闻快照",
        "table": "stock_comment_daily",
        "snapshot_date": _iso(comment_day or data_end),
        "covered": ok_n,
        "target": target,
        "detail": "；".join(parts),
        "data_start": _iso(data_start),
        "data_end": _iso(data_end),
        "last_synced_at": _iso(last_sync or last_ingest),
        "supports_trading_days": False,
        "supports_resume": False,
        "supports_day": False,
        "suggested_day": None,
        "action_label": "同步快照",
        "complete": ok_n == target,
    }


def _news_flash(cur: psycopg.Cursor) -> dict[str, Any]:
    cur.execute(
        """
        SELECT feed, last_status, last_rows, last_error, updated_at, cursor_at
        FROM news_sync_state
        WHERE feed = ANY(%s)
        """,
        (["cls", "ths"],),
    )
    by_feed = {row[0]: row for row in cur.fetchall()}
    cur.execute(
        """
        SELECT source, COUNT(*), MIN(published_at), MAX(published_at)
        FROM news_flash
        GROUP BY source
        """
    )
    stored = {row[0]: row for row in cur.fetchall()}
    labels = (("cls", "财联社"), ("ths", "同花顺"))
    parts: list[str] = []
    ok_n = 0
    last_sync = None
    range_start = None
    range_end = None
    for feed, label in labels:
        row = by_feed.get(feed)
        status = row[1] if row else "pending"
        inserted = int(row[2] or 0) if row else 0
        error = row[3] if row else None
        updated = row[4] if row else None
        have = stored.get(feed)
        total = int(have[1]) if have else 0
        if status == "ok":
            ok_n += 1
        if updated is not None and (last_sync is None or updated > last_sync):
            last_sync = updated
        if have is not None:
            if range_start is None or have[2] < range_start:
                range_start = have[2]
            if range_end is None or have[3] > range_end:
                range_end = have[3]
        text = f"{label} {status} 新增 {inserted}（库内 {total}）"
        if error and status != "ok":
            text += f"（{error}）"
        parts.append(text)
    return {
        "job_id": "news_flash",
        "title": "新闻快讯",
        "table": "news_flash",
        "snapshot_date": None,
        "covered": ok_n,
        "target": len(labels),
        "detail": "；".join(parts),
        "data_start": _iso(range_start),
        "data_end": _iso(range_end),
        "last_synced_at": _iso(last_sync),
        "supports_trading_days": False,
        "supports_resume": False,
        "supports_day": False,
        "suggested_day": None,
        "action_label": "同步快讯",
        "complete": ok_n == len(labels),
    }
