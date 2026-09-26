"""Database helpers for the web app and sync jobs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import psycopg

from app.market_data.board_heat import BoardHeatRow
from app.market_data.normalize import (
    BoardConstituentRow,
    BoardDailyBar,
    BoardUniverseRow,
    DailyBar,
)

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

UPSERT_BOARD_UNIVERSE_SQL = """
INSERT INTO board_universe_daily (
    trade_date, board_type, board_code, board_name, source
) VALUES (
    %s, %s, %s, %s, %s
)
ON CONFLICT (trade_date, board_type, board_code) DO UPDATE SET
    board_name = EXCLUDED.board_name,
    source = EXCLUDED.source,
    ingested_at = now()
"""

DELETE_BOARD_UNIVERSE_DAY_SQL = """
DELETE FROM board_universe_daily
WHERE trade_date = %s
"""

DELETE_BOARD_UNIVERSE_DAY_TYPE_SQL = """
DELETE FROM board_universe_daily
WHERE trade_date = %s
  AND board_type = %s
"""

UPSERT_BOARD_DAILY_BAR_SQL = """
INSERT INTO board_daily_bar (
    trade_date, board_type, board_code,
    open, high, low, close, volume, amount,
    pct_chg, turn, amplitude, adjustflag, source
) VALUES (
    %s, %s, %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s
)
ON CONFLICT (trade_date, board_type, board_code) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    amount = EXCLUDED.amount,
    pct_chg = EXCLUDED.pct_chg,
    turn = EXCLUDED.turn,
    amplitude = EXCLUDED.amplitude,
    adjustflag = EXCLUDED.adjustflag,
    source = EXCLUDED.source,
    ingested_at = now()
"""

UPSERT_BOARD_SYNC_STATE_SQL = """
INSERT INTO board_daily_bar_sync_state (
    board_type, board_code, window_start, window_end,
    last_status, last_source, last_rows, last_error, updated_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, now()
)
ON CONFLICT (board_type, board_code) DO UPDATE SET
    window_start = EXCLUDED.window_start,
    window_end = EXCLUDED.window_end,
    last_status = EXCLUDED.last_status,
    last_source = EXCLUDED.last_source,
    last_rows = EXCLUDED.last_rows,
    last_error = EXCLUDED.last_error,
    updated_at = now()
"""

UPSERT_BOARD_CONSTITUENT_SQL = """
INSERT INTO board_constituent_daily (
    trade_date, board_type, board_code, stock_code, stock_name, source
) VALUES (
    %s, %s, %s, %s, %s, %s
)
ON CONFLICT (trade_date, board_type, board_code, stock_code) DO UPDATE SET
    stock_name = EXCLUDED.stock_name,
    source = EXCLUDED.source,
    ingested_at = now()
"""

DELETE_BOARD_CONSTITUENT_BOARD_SQL = """
DELETE FROM board_constituent_daily
WHERE trade_date = %s
  AND board_type = %s
  AND board_code = %s
"""

UPSERT_BOARD_CONSTITUENT_SYNC_STATE_SQL = """
INSERT INTO board_constituent_sync_state (
    board_type, board_code, snapshot_date,
    last_status, last_source, last_rows, last_error, updated_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, now()
)
ON CONFLICT (board_type, board_code) DO UPDATE SET
    snapshot_date = EXCLUDED.snapshot_date,
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


@dataclass(frozen=True)
class BoardListItem:
    board_type: str
    board_code: str
    board_name: str


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


def fetch_daily_bars_from_db(
    code: str, start: date, end: date
) -> list[dict[str, object]]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, open, high, low, close, volume
                FROM stock_daily_bar
                WHERE code = %s
                  AND trade_date >= %s
                  AND trade_date <= %s
                ORDER BY trade_date
                """,
                (code, start, end),
            )
            rows = cur.fetchall()
    return [
        {
            "trade_date": row[0],
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
        }
        for row in rows
    ]


def fetch_board_daily_bars_from_db(
    board_type: str,
    board_code: str,
    start: date,
    end: date,
) -> list[dict[str, object]]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, open, high, low, close, volume
                FROM board_daily_bar
                WHERE board_type = %s
                  AND board_code = %s
                  AND trade_date >= %s
                  AND trade_date <= %s
                ORDER BY trade_date
                """,
                (board_type, board_code, start, end),
            )
            rows = cur.fetchall()
    return [
        {
            "trade_date": row[0],
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
        }
        for row in rows
    ]


def fetch_board_name(board_type: str, board_code: str) -> str | None:
    """Latest known name for one board."""
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT board_name
                FROM board_universe_daily
                WHERE board_type = %s
                  AND board_code = %s
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (board_type, board_code),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return row[0]


def fetch_trading_dates_ending(
    board_type: str,
    on_or_before: date,
    limit: int,
) -> list[date]:
    """Up to `limit` distinct bar dates on or before the day, oldest first."""
    if limit < 1:
        raise ValueError("limit must be >= 1")
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date
                FROM (
                    SELECT DISTINCT trade_date
                    FROM board_daily_bar
                    WHERE board_type = %s
                      AND trade_date <= %s
                    ORDER BY trade_date DESC
                    LIMIT %s
                ) AS recent
                ORDER BY trade_date
                """,
                (board_type, on_or_before, limit),
            )
            return [row[0] for row in cur.fetchall()]


def fetch_industry_board_close_heat(
    board_codes: list[str],
    start: date,
    end: date,
) -> dict[str, list[tuple[date, object, object, object]]]:
    """Daily close and heats for the given industry boards, oldest first."""
    if not board_codes:
        return {}
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    b.board_code,
                    b.trade_date,
                    b.close,
                    h.heat_short,
                    h.heat_long
                FROM board_daily_bar AS b
                LEFT JOIN board_heat_daily AS h
                  ON h.board_type = b.board_type
                 AND h.board_code = b.board_code
                 AND h.trade_date = b.trade_date
                WHERE b.board_type = 'industry'
                  AND b.board_code = ANY(%s)
                  AND b.trade_date >= %s
                  AND b.trade_date <= %s
                ORDER BY b.board_code, b.trade_date
                """,
                (board_codes, start, end),
            )
            rows = cur.fetchall()
    grouped: dict[str, list[tuple[date, object, object, object]]] = {}
    for board_code, trade_date, close, heat_short, heat_long in rows:
        grouped.setdefault(board_code, []).append(
            (trade_date, close, heat_short, heat_long)
        )
    return grouped


def fetch_board_heat_series(
    board_type: str,
    board_code: str,
    start: date,
    end: date,
) -> list[dict[str, object]]:
    """Short and long heat for one board. Null heats stay null."""
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, heat_short, heat_long
                FROM board_heat_daily
                WHERE board_type = %s
                  AND board_code = %s
                  AND trade_date >= %s
                  AND trade_date <= %s
                ORDER BY trade_date
                """,
                (board_type, board_code, start, end),
            )
            rows = cur.fetchall()
    return [
        {"trade_date": row[0], "heat_short": row[1], "heat_long": row[2]}
        for row in rows
    ]


def replace_board_universe(
    rows: list[BoardUniverseRow],
    *,
    trade_date: date,
    board_type: str | None = None,
) -> int:
    """Replace one day's board universe snapshot, then upsert rows."""
    payload = [
        (row.trade_date, row.board_type, row.board_code, row.board_name, row.source)
        for row in rows
    ]
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            if board_type is None:
                cur.execute(DELETE_BOARD_UNIVERSE_DAY_SQL, (trade_date,))
            else:
                cur.execute(
                    DELETE_BOARD_UNIVERSE_DAY_TYPE_SQL, (trade_date, board_type)
                )
            if payload:
                cur.executemany(UPSERT_BOARD_UNIVERSE_SQL, payload)
        conn.commit()
    return len(payload)


def upsert_board_universe(rows: list[BoardUniverseRow]) -> int:
    if not rows:
        return 0
    payload = [
        (row.trade_date, row.board_type, row.board_code, row.board_name, row.source)
        for row in rows
    ]
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_BOARD_UNIVERSE_SQL, payload)
        conn.commit()
    return len(payload)


def fetch_latest_board_universe_date() -> date | None:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(trade_date) FROM board_universe_daily")
            return cur.fetchone()[0]


def fetch_latest_board_type_map() -> dict[str, str]:
    """Latest board_code -> board_type map.

    If the latest snapshot looks poisoned (almost no industries), only keep
    industry labels so a bad bk_changes run cannot lock everything as concept.
    """
    latest = fetch_latest_board_universe_date()
    if latest is None:
        return {}
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT board_code, board_type
                FROM board_universe_daily
                WHERE trade_date = %s
                """,
                (latest,),
            )
            mapping = {row[0]: row[1] for row in cur.fetchall()}
    industry_n = sum(1 for value in mapping.values() if value == "industry")
    if industry_n < 20:
        return {
            code: board_type
            for code, board_type in mapping.items()
            if board_type == "industry"
        }
    return mapping


def fetch_latest_board_codes(
    board_type: str | None = None,
) -> list[BoardListItem]:
    latest = fetch_latest_board_universe_date()
    if latest is None:
        return []

    sql = """
        SELECT board_type, board_code, board_name
        FROM board_universe_daily
        WHERE trade_date = %s
    """
    params: list[object] = [latest]
    if board_type is not None:
        sql += " AND board_type = %s"
        params.append(board_type)
    sql += " ORDER BY board_type, board_code"

    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [
                BoardListItem(board_type=row[0], board_code=row[1], board_name=row[2])
                for row in cur.fetchall()
            ]


def fetch_completed_board_sync_keys(
    window_start: date, window_end: date
) -> set[tuple[str, str]]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT board_type, board_code
                FROM board_daily_bar_sync_state
                WHERE last_status = 'ok'
                  AND window_start = %s
                  AND window_end = %s
                """,
                (window_start, window_end),
            )
            return {(row[0], row[1]) for row in cur.fetchall()}


def upsert_board_daily_bars(bars: list[BoardDailyBar]) -> int:
    if not bars:
        return 0
    payload = [
        (
            bar.trade_date,
            bar.board_type,
            bar.board_code,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.amount,
            bar.pct_chg,
            bar.turn,
            bar.amplitude,
            bar.adjustflag,
            bar.source,
        )
        for bar in bars
    ]
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_BOARD_DAILY_BAR_SQL, payload)
        conn.commit()
    return len(payload)


def save_board_sync_state(
    board_type: str,
    board_code: str,
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
                UPSERT_BOARD_SYNC_STATE_SQL,
                (
                    board_type,
                    board_code,
                    window_start,
                    window_end,
                    status,
                    source,
                    rows,
                    error,
                ),
            )
        conn.commit()


def replace_board_constituents(
    rows: list[BoardConstituentRow],
    *,
    trade_date: date,
    board_type: str,
    board_code: str,
) -> int:
    payload = [
        (
            row.trade_date,
            row.board_type,
            row.board_code,
            row.stock_code,
            row.stock_name,
            row.source,
        )
        for row in rows
    ]
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                DELETE_BOARD_CONSTITUENT_BOARD_SQL,
                (trade_date, board_type, board_code),
            )
            if payload:
                cur.executemany(UPSERT_BOARD_CONSTITUENT_SQL, payload)
        conn.commit()
    return len(payload)


def fetch_completed_constituent_sync_keys(snapshot_date: date) -> set[tuple[str, str]]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT board_type, board_code
                FROM board_constituent_sync_state
                WHERE last_status = 'ok'
                  AND snapshot_date = %s
                """,
                (snapshot_date,),
            )
            return {(row[0], row[1]) for row in cur.fetchall()}


def save_board_constituent_sync_state(
    board_type: str,
    board_code: str,
    snapshot_date: date,
    status: str,
    source: str | None,
    rows: int,
    error: str | None,
) -> None:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                UPSERT_BOARD_CONSTITUENT_SYNC_STATE_SQL,
                (
                    board_type,
                    board_code,
                    snapshot_date,
                    status,
                    source,
                    rows,
                    error,
                ),
            )
        conn.commit()


def fetch_board_constituent_codes(
    board_type: str,
    board_code: str,
    *,
    as_of: date | None = None,
) -> list[str]:
    """Latest constituent snapshot on/before as_of (or absolute latest)."""
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            if as_of is None:
                cur.execute(
                    """
                    SELECT stock_code
                    FROM board_constituent_daily
                    WHERE board_type = %s
                      AND board_code = %s
                      AND trade_date = (
                          SELECT MAX(trade_date)
                          FROM board_constituent_daily
                          WHERE board_type = %s
                            AND board_code = %s
                      )
                    ORDER BY stock_code
                    """,
                    (board_type, board_code, board_type, board_code),
                )
            else:
                cur.execute(
                    """
                    SELECT stock_code
                    FROM board_constituent_daily
                    WHERE board_type = %s
                      AND board_code = %s
                      AND trade_date = (
                          SELECT MAX(trade_date)
                          FROM board_constituent_daily
                          WHERE board_type = %s
                            AND board_code = %s
                            AND trade_date <= %s
                      )
                    ORDER BY stock_code
                    """,
                    (board_type, board_code, board_type, board_code, as_of),
                )
            return [row[0] for row in cur.fetchall()]


def fetch_stock_bars_for_codes(
    codes: list[str],
    start: date,
    end: date,
) -> list[dict[str, object]]:
    if not codes:
        return []
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, code, open, high, low, close, preclose,
                       volume, amount, pct_chg
                FROM stock_daily_bar
                WHERE code = ANY(%s)
                  AND trade_date >= %s
                  AND trade_date <= %s
                ORDER BY trade_date, code
                """,
                (codes, start, end),
            )
            rows = cur.fetchall()
    return [
        {
            "trade_date": row[0],
            "code": row[1],
            "open": row[2],
            "high": row[3],
            "low": row[4],
            "close": row[5],
            "preclose": row[6],
            "volume": row[7],
            "amount": row[8],
            "pct_chg": row[9],
        }
        for row in rows
    ]


@dataclass(frozen=True)
class BoardRotationRow:
    board_code: str
    board_name: str
    pct_chg: object
    vol: object | None
    heat_short: object | None
    prev_heat_short: object | None
    heat_long: object | None
    prev_heat_long: object | None


def fetch_industry_rotation_dates(lookback: int = 10) -> list[date]:
    """Oldest-first industry heat dates from the latest day back `lookback` days."""
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date
                FROM (
                    SELECT DISTINCT trade_date
                    FROM board_heat_daily
                    WHERE board_type = 'industry'
                    ORDER BY trade_date DESC
                    LIMIT %s
                ) AS recent
                ORDER BY trade_date
                """,
                (lookback + 1,),
            )
            return [row[0] for row in cur.fetchall()]


def fetch_industry_board_rotation(
    as_of: date | None = None,
) -> tuple[date | None, date | None, list[BoardRotationRow]]:
    """Industry rotation for one heat day and the prior heat day.

    `as_of` defaults to the latest industry heat date.
    """
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH days AS (
                    SELECT trade_date,
                           ROW_NUMBER() OVER (ORDER BY trade_date DESC) AS rn
                    FROM (
                        SELECT DISTINCT trade_date
                        FROM board_heat_daily
                        WHERE board_type = 'industry'
                    ) AS distinct_days
                ),
                chosen AS (
                    SELECT trade_date AS as_of
                    FROM days
                    WHERE (%s::date IS NULL AND rn = 1)
                       OR trade_date = %s::date
                    LIMIT 1
                ),
                pair AS (
                    SELECT
                        c.as_of,
                        (
                            SELECT MAX(d.trade_date)
                            FROM days AS d
                            WHERE d.trade_date < c.as_of
                        ) AS prev_date
                    FROM chosen AS c
                ),
                names AS (
                    SELECT DISTINCT ON (u.board_code)
                        u.board_code,
                        u.board_name
                    FROM board_universe_daily AS u
                    WHERE u.board_type = 'industry'
                    ORDER BY u.board_code, u.trade_date DESC
                ),
                vol AS (
                    SELECT board_code, STDDEV_SAMP(pct_chg) AS vol
                    FROM (
                        SELECT
                            b.board_code,
                            b.pct_chg,
                            ROW_NUMBER() OVER (
                                PARTITION BY b.board_code
                                ORDER BY b.trade_date DESC
                            ) AS rn
                        FROM board_daily_bar AS b
                        JOIN pair AS p ON b.trade_date <= p.as_of
                        WHERE b.board_type = 'industry'
                          AND b.pct_chg IS NOT NULL
                    ) AS recent
                    WHERE rn <= 20
                    GROUP BY board_code
                    HAVING COUNT(*) = 20
                )
                SELECT
                    p.as_of,
                    p.prev_date,
                    c.board_code,
                    COALESCE(n.board_name, c.board_code) AS board_name,
                    c.pct_chg,
                    v.vol,
                    c.heat_short,
                    prev.heat_short AS prev_heat_short,
                    c.heat_long,
                    prev.heat_long AS prev_heat_long
                FROM pair AS p
                JOIN board_heat_daily AS c
                  ON c.board_type = 'industry'
                 AND c.trade_date = p.as_of
                LEFT JOIN board_heat_daily AS prev
                  ON prev.board_type = 'industry'
                 AND prev.trade_date = p.prev_date
                 AND prev.board_code = c.board_code
                LEFT JOIN names AS n ON n.board_code = c.board_code
                LEFT JOIN vol AS v ON v.board_code = c.board_code
                ORDER BY c.board_code
                """,
                (as_of, as_of),
            )
            fetched = cur.fetchall()
    if not fetched:
        return None, None, []
    as_of = fetched[0][0]
    prev_date = fetched[0][1]
    rows = [
        BoardRotationRow(
            board_code=row[2],
            board_name=row[3],
            pct_chg=row[4],
            vol=row[5],
            heat_short=row[6],
            prev_heat_short=row[7],
            heat_long=row[8],
            prev_heat_long=row[9],
        )
        for row in fetched
    ]
    return as_of, prev_date, rows


@dataclass(frozen=True)
class IndustryHeatPoint:
    trade_date: date
    board_name: str
    board_code: str
    heat_short: object | None
    heat_long: object | None
    heat_short_change: object | None
    heat_long_change: object | None
    pct_chg: object | None


def fetch_industry_heat_window(
    trading_days: int,
    as_of: date | None = None,
) -> tuple[date | None, date | None, list[IndustryHeatPoint]]:
    """Industry heats ending on as_of (default latest), plus the prior day changes."""
    if trading_days < 1:
        raise ValueError("trading_days must be >= 1")
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH all_days AS (
                    SELECT trade_date,
                           LAG(trade_date) OVER (ORDER BY trade_date) AS prev_date
                    FROM (
                        SELECT DISTINCT trade_date
                        FROM board_heat_daily
                        WHERE board_type = 'industry'
                    ) AS distinct_days
                ),
                window_days AS (
                    SELECT trade_date, prev_date
                    FROM all_days
                    WHERE %s::date IS NULL OR trade_date <= %s::date
                    ORDER BY trade_date DESC
                    LIMIT %s
                ),
                names AS (
                    SELECT DISTINCT ON (board_code)
                        board_code,
                        board_name
                    FROM board_universe_daily
                    WHERE board_type = 'industry'
                    ORDER BY board_code, trade_date DESC
                )
                SELECT
                    h.trade_date,
                    COALESCE(n.board_name, h.board_code) AS board_name,
                    h.board_code,
                    h.heat_short,
                    h.heat_long,
                    CASE
                        WHEN h.heat_short IS NULL OR prev.heat_short IS NULL THEN NULL
                        ELSE prev.heat_short - h.heat_short
                    END AS heat_short_change,
                    CASE
                        WHEN h.heat_long IS NULL OR prev.heat_long IS NULL THEN NULL
                        ELSE prev.heat_long - h.heat_long
                    END AS heat_long_change,
                    h.pct_chg,
                    bounds.prev_date
                FROM window_days AS bounds
                JOIN board_heat_daily AS h
                  ON h.board_type = 'industry'
                 AND h.trade_date = bounds.trade_date
                LEFT JOIN board_heat_daily AS prev
                  ON prev.board_type = 'industry'
                 AND prev.board_code = h.board_code
                 AND prev.trade_date = bounds.prev_date
                LEFT JOIN names AS n ON n.board_code = h.board_code
                ORDER BY h.trade_date, board_name
                """,
                (as_of, as_of, trading_days),
            )
            fetched = cur.fetchall()
    if not fetched:
        return None, None, []
    as_of = max(row[0] for row in fetched)
    prev_date = next(row[8] for row in fetched if row[0] == as_of)
    points = [
        IndustryHeatPoint(
            trade_date=row[0],
            board_name=row[1],
            board_code=row[2],
            heat_short=row[3],
            heat_long=row[4],
            heat_short_change=row[5],
            heat_long_change=row[6],
            pct_chg=row[7],
        )
        for row in fetched
    ]
    return as_of, prev_date, points


@dataclass(frozen=True)
class IndustryPriceSummary:
    board_name: str
    ret_20: object | None
    range_pos: object | None
    amount_ratio: object | None


def fetch_industry_price_summary(
    trading_days: int,
    as_of: date,
) -> list[IndustryPriceSummary]:
    """One row per industry board on as_of.

    ret_20 is the close-to-close percent change versus the close 20 trading days earlier.
    range_pos is where that close sits between the low and high of the heat window
    (0 at the low, 1 at the high). amount_ratio is that day's amount divided by the
    window's average amount.
    """
    if trading_days < 1:
        raise ValueError("trading_days must be >= 1")
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH heat_days AS (
                    SELECT trade_date,
                           LAG(trade_date, 20) OVER (ORDER BY trade_date) AS ret_base_date
                    FROM (
                        SELECT DISTINCT trade_date
                        FROM board_heat_daily
                        WHERE board_type = 'industry'
                    ) AS distinct_days
                ),
                end_day AS (
                    SELECT trade_date, ret_base_date
                    FROM heat_days
                    WHERE trade_date <= %s::date
                    ORDER BY trade_date DESC
                    LIMIT 1
                ),
                window_days AS (
                    SELECT trade_date
                    FROM heat_days
                    WHERE trade_date <= (SELECT trade_date FROM end_day)
                    ORDER BY trade_date DESC
                    LIMIT %s
                ),
                names AS (
                    SELECT DISTINCT ON (board_code)
                        board_code,
                        board_name
                    FROM board_universe_daily
                    WHERE board_type = 'industry'
                    ORDER BY board_code, trade_date DESC
                ),
                window_stats AS (
                    SELECT
                        b.board_code,
                        MIN(b.low) AS range_low,
                        MAX(b.high) AS range_high,
                        AVG(b.amount) AS amount_avg
                    FROM board_daily_bar AS b
                    JOIN window_days AS w ON w.trade_date = b.trade_date
                    WHERE b.board_type = 'industry'
                    GROUP BY b.board_code
                )
                SELECT
                    COALESCE(n.board_name, h.board_code) AS board_name,
                    CASE
                        WHEN base.close IS NULL OR base.close = 0 OR today.close IS NULL THEN NULL
                        ELSE ROUND((today.close - base.close) / base.close * 100, 2)
                    END AS ret_20,
                    CASE
                        WHEN stats.range_high IS NULL
                          OR stats.range_low IS NULL
                          OR today.close IS NULL
                          OR stats.range_high = stats.range_low THEN NULL
                        ELSE ROUND(
                            (today.close - stats.range_low)
                            / (stats.range_high - stats.range_low),
                            2
                        )
                    END AS range_pos,
                    CASE
                        WHEN stats.amount_avg IS NULL
                          OR stats.amount_avg = 0
                          OR today.amount IS NULL THEN NULL
                        ELSE ROUND(today.amount / stats.amount_avg, 2)
                    END AS amount_ratio
                FROM board_heat_daily AS h
                JOIN end_day AS ending ON h.trade_date = ending.trade_date
                LEFT JOIN names AS n ON n.board_code = h.board_code
                LEFT JOIN window_stats AS stats ON stats.board_code = h.board_code
                LEFT JOIN board_daily_bar AS today
                  ON today.board_type = 'industry'
                 AND today.board_code = h.board_code
                 AND today.trade_date = ending.trade_date
                LEFT JOIN board_daily_bar AS base
                  ON base.board_type = 'industry'
                 AND base.board_code = h.board_code
                 AND base.trade_date = ending.ret_base_date
                WHERE h.board_type = 'industry'
                ORDER BY board_name
                """,
                (as_of, trading_days),
            )
            fetched = cur.fetchall()
    return [
        IndustryPriceSummary(
            board_name=row[0],
            ret_20=row[1],
            range_pos=row[2],
            amount_ratio=row[3],
        )
        for row in fetched
    ]


def fetch_interpret_result(
    template_name: str,
    as_of: date,
    request_model: str,
) -> tuple[str, str] | None:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT response_model, content
                FROM interpret_result
                WHERE template_name = %s
                  AND as_of = %s
                  AND request_model = %s
                """,
                (template_name, as_of, request_model),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return row[0], row[1]


def save_interpret_result(
    template_name: str,
    as_of: date,
    request_model: str,
    response_model: str,
    content: str,
) -> None:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interpret_result (
                    template_name, as_of, request_model, response_model, content
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (template_name, as_of, request_model) DO UPDATE SET
                    response_model = EXCLUDED.response_model,
                    content = EXCLUDED.content,
                    created_at = now()
                """,
                (template_name, as_of, request_model, response_model, content),
            )
        conn.commit()


def fetch_board_returns(board_type: str) -> list[tuple[date, str, object]]:
    """Industry or concept bars that have a return, ordered by date and code."""
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, board_code, pct_chg, high, low, close
                FROM board_daily_bar
                WHERE board_type = %s
                  AND high IS NOT NULL
                  AND low IS NOT NULL
                  AND close IS NOT NULL
                ORDER BY trade_date, board_code
                """,
                (board_type,),
            )
            return [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in cur.fetchall()]


def fetch_board_heat(board_type: str) -> list[BoardHeatRow]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date, board_type, board_code, pct_chg,
                       rank_no, universe_n, heat_short, heat_long
                FROM board_heat_daily
                WHERE board_type = %s
                ORDER BY trade_date, board_code
                """,
                (board_type,),
            )
            return [
                BoardHeatRow(
                    trade_date=row[0],
                    board_type=row[1],
                    board_code=row[2],
                    pct_chg=row[3],
                    rank_no=row[4],
                    universe_n=row[5],
                    heat_short=row[6],
                    heat_long=row[7],
                )
                for row in cur.fetchall()
            ]


def replace_board_heat(board_type: str, start: date, rows: list[BoardHeatRow]) -> int:
    """Replace heat rows of one board type from start through the written set."""
    payload = [
        (
            row.trade_date,
            row.board_type,
            row.board_code,
            row.pct_chg,
            row.rank_no,
            row.universe_n,
            row.heat_short,
            row.heat_long,
        )
        for row in rows
        if row.board_type == board_type and row.trade_date >= start
    ]
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM board_heat_daily
                WHERE board_type = %s
                  AND trade_date >= %s
                """,
                (board_type, start),
            )
            if payload:
                cur.executemany(
                    """
                    INSERT INTO board_heat_daily (
                        trade_date, board_type, board_code, pct_chg,
                        rank_no, universe_n, heat_short, heat_long
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    payload,
                )
        conn.commit()
    return len(payload)

