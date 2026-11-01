"""Name and board membership for one analyze-page code."""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg

from app.db import database_url
from app.market_data.codes import to_baostock
from app.market_data.providers.ths_line import INDEX_NAMES


def safe_stock_identity(ths_code: str) -> dict[str, Any]:
    """Never let a membership lookup take down the chart page."""
    try:
        return load_stock_identity(ths_code)
    except Exception:
        return {
            "name": None,
            "title": ths_code,
            "show_boards": False,
            "industries": [],
            "concepts": [],
            "as_of": None,
        }


def load_stock_identity(ths_code: str) -> dict[str, Any]:
    """Latest stored name plus industry and concept membership."""
    index_name = INDEX_NAMES.get(ths_code)
    if index_name:
        return {
            "name": index_name,
            "title": f"{index_name} {ths_code}",
            "show_boards": False,
            "industries": [],
            "concepts": [],
            "as_of": None,
        }
    try:
        code = to_baostock(ths_code)
    except ValueError:
        return {
            "name": None,
            "title": ths_code,
            "show_boards": False,
            "industries": [],
            "concepts": [],
            "as_of": None,
        }
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
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
            cur.execute(
                """
                SELECT c.board_type, c.board_code, c.stock_name, c.trade_date,
                       (
                         SELECT u.board_name
                         FROM board_universe_daily AS u
                         WHERE u.board_type = c.board_type
                           AND u.board_code = c.board_code
                         ORDER BY u.trade_date DESC
                         LIMIT 1
                       ) AS board_name
                FROM board_constituent_daily AS c
                WHERE c.stock_code = %s
                  AND c.trade_date = (
                    SELECT MAX(trade_date)
                    FROM board_constituent_daily
                    WHERE stock_code = %s
                      AND board_type = c.board_type
                  )
                """,
                (code, code),
            )
            rows = list(cur.fetchall())
    name = name_row[0] if name_row and name_row[0] else None
    if not name and rows:
        name = rows[0][2]
    return build_stock_identity(ths_code=ths_code, name=name, rows=rows)


def build_stock_identity(
    *,
    ths_code: str,
    name: str | None,
    rows: list[tuple[Any, ...]],
) -> dict[str, Any]:
    """Shape one stock's name and its latest industry and concept boards."""
    industries: list[dict[str, str]] = []
    concepts: list[dict[str, str]] = []
    days: list[date] = []
    clean_name = name.strip() if name and str(name).strip() else None
    for board_type, board_code, _stock_name, trade_date, board_name in rows:
        label = str(board_name or board_code).strip() or str(board_code)
        item = {
            "code": str(board_code),
            "name": label,
            "href": f"/boards/{board_type}/{board_code}/kline",
        }
        if isinstance(trade_date, date):
            days.append(trade_date)
        if board_type == "industry":
            industries.append(item)
        elif board_type == "concept":
            concepts.append(item)
    industries.sort(key=lambda item: item["name"])
    concepts.sort(key=lambda item: item["name"])
    return {
        "name": clean_name,
        "title": f"{ths_code} {clean_name}" if clean_name else ths_code,
        "show_boards": True,
        "industries": industries,
        "concepts": concepts,
        "as_of": max(days).isoformat() if days else None,
    }
