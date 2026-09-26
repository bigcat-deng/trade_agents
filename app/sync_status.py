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
                _board_universe(cur),
                _board_daily_bars(cur),
                _board_heat(cur),
                _board_constituents(cur),
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
