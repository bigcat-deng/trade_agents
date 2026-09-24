"""Database helpers for the web app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import psycopg

DEFAULT_DATABASE_URL = "postgresql:///analytics"

LATEST_TRADING_STOCKS_SQL = """
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
  AND (
      s.code LIKE 'sh.60%%'
      OR s.code LIKE 'sh.68%%'
      OR s.code LIKE 'sz.00%%'
      OR s.code LIKE 'sz.30%%'
  )
ORDER BY s.code
LIMIT %s
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
