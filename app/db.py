"""Database helpers for the web app and sync jobs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import psycopg

from app.market_data.normalize import DailyBar

DEFAULT_DATABASE_URL = "postgresql:///analytics"

A_SHARE_CODE_FILTER_SQL = """
(
    s.code LIKE 'sh.60%%'
    OR s.code LIKE 'sh.68%%'
    OR s.code LIKE 'sz.00%%'
    OR s.code LIKE 'sz.30%%'
)
"""

LATEST_TRADING_STOCKS_SQL = f"""
WITH latest AS (
    SELECT MAX(trade_date) AS trade_date
    FROM stock_universe_daily
)
SELECT
    s.trade_date,
    s.code,
    s.code_name
FROM stock_universe_daily AS s
JOIN latest ON s.trade_date = latest.trade_date
WHERE s.trade_status = 1
  AND {A_SHARE_CODE_FILTER_SQL}
ORDER BY s.code
LIMIT %s
"""

ALL_LATEST_TRADING_STOCK_CODES_SQL = f"""
WITH latest AS (
    SELECT MAX(trade_date) AS trade_date
    FROM stock_universe_daily
)
SELECT s.code
FROM stock_universe_daily AS s
JOIN latest ON s.trade_date = latest.trade_date
WHERE s.trade_status = 1
  AND {A_SHARE_CODE_FILTER_SQL}
ORDER BY s.code
"""

UPSERT_DAILY_BAR_SQL = """
INSERT INTO stock_daily_bar (
    trade_date, code, open, high, low, close, preclose,
    volume, amount, adjustflag, turn, tradestatus, pct_chg, is_st, source
) VALUES (
    %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (trade_date, code) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    preclose = EXCLUDED.preclose,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    adjustflag = EXCLUDED.adjustflag,
    turn = EXCLUDED.turn,
    tradestatus = EXCLUDED.tradestatus,
    pct_chg = EXCLUDED.pct_chg,
    is_st = EXCLUDED.is_st,
    source = EXCLUDED.source,
    ingested_at = now()
WHERE stock_daily_bar.source IS DISTINCT FROM 'baostock'
   OR EXCLUDED.source = 'baostock'
"""

UPSERT_SYNC_STATE_SQL = """
INSERT INTO stock_daily_bar_sync_state (
    code, window_start, window_end, last_status, last_source, last_rows, last_error, updated_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, now()
)
ON CONFLICT (code) DO UPDATE SET
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    last_status = EXCLUDED.last_status,
    last_source = EXCLUDED.last_source,
    last_rows = EXCLUDED.last_rows,
    last_error = EXCLUDED.last_error,
    updated_at = now()
"""


@dataclass(frozen=True)
class StockListItem:
    trade_date: date
    code: str
    code_name: str


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def fetch_latest_trading_stocks(limit: int = 30) -> tuple[date | None, list[StockListItem]]:
    """Return (latest_sync_date, first `limit` trading A-share stocks by code)."""
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(LATEST_TRADING_STOCKS_SQL, (int(limit),))
            rows = cur.fetchall()

            if rows:
                items = [
                    StockListItem(trade_date=row[0], code=row[1], code_name=row[2])
                    for row in rows
                ]
                return items[0].trade_date, items

            cur.execute("SELECT MAX(trade_date) FROM stock_universe_daily")
            latest = cur.fetchone()[0]
            return latest, []


def fetch_latest_universe_date() -> date | None:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(trade_date) FROM stock_universe_daily")
            return cur.fetchone()[0]


def fetch_all_latest_trading_stock_codes() -> list[str]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            # No bind params: keep single '%' wildcards for LIKE.
            sql = ALL_LATEST_TRADING_STOCK_CODES_SQL.replace("%%", "%")
            cur.execute(sql)
            return [row[0] for row in cur.fetchall()]


def fetch_completed_sync_codes(window_start: date, window_end: date) -> set[str]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT code
                FROM stock_daily_bar_sync_state
                WHERE last_status = 'ok'
                  AND window_start = %s
                  AND window_end = %s
                """,
                (window_start, window_end),
            )
            return {row[0] for row in cur.fetchall()}


def upsert_daily_bars(bars: list[DailyBar]) -> int:
    if not bars:
        return 0
    payload = [
        (
            bar.trade_date,
            bar.code,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.preclose,
            bar.volume,
            bar.amount,
            bar.adjustflag,
            bar.turn,
            bar.tradestatus,
            bar.pct_chg,
            bar.is_st,
            bar.source,
        )
        for bar in bars
    ]
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_DAILY_BAR_SQL, payload)
        conn.commit()
    return len(payload)


def save_sync_state(
    code: str,
    window_start: date,
    window_end: date,
    status: str,
    source: str | None,
    rows: int,
    error: str | None,
) -> None:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                UPSERT_SYNC_STATE_SQL,
                (code, window_start, window_end, status, source, rows, error),
            )
        conn.commit()
