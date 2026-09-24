"""Sync one day of baostock query_all_stock into stock_universe_daily."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from typing import Iterable

import baostock as bs
import psycopg

DEFAULT_DATABASE_URL = "postgresql:///analytics"
SOURCE = "baostock"

UPSERT_SQL = """
INSERT INTO stock_universe_daily (
    trade_date, code, code_name, trade_status, source
) VALUES (
    %s, %s, %s, %s, %s
)
ON CONFLICT (trade_date, code) DO UPDATE SET
    code_name = EXCLUDED.code_name,
    trade_status = EXCLUDED.trade_status,
    ingested_at = now()
"""


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid day {value!r}; expected YYYY-MM-DD"
        ) from exc


def fetch_all_stock(trade_date: date) -> list[tuple[date, str, str, int, str]]:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"baostock login failed: {login.error_msg}")

    try:
        result = bs.query_all_stock(day=trade_date.isoformat())
        if result.error_code != "0":
            raise RuntimeError(
                f"query_all_stock failed: {result.error_code} {result.error_msg}"
            )

        rows: list[tuple[date, str, str, int, str]] = []
        skipped = 0
        while result.error_code == "0" and result.next():
            code, trade_status, code_name = result.get_row_data()
            code = (code or "").strip()
            code_name = (code_name or "").strip()
            if not code or not code_name:
                skipped += 1
                continue
            try:
                status = int(trade_status)
            except (TypeError, ValueError):
                skipped += 1
                continue
            rows.append((trade_date, code, code_name, status, SOURCE))

        if skipped:
            print(f"skipped {skipped} invalid rows")
        return rows
    finally:
        bs.logout()


def upsert_rows(
    database_url: str, rows: Iterable[tuple[date, str, str, int, str]]
) -> int:
    materialised = list(rows)
    if not materialised:
        return 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, materialised)
        conn.commit()
    return len(materialised)


def run(trade_date: date, database_url: str) -> int:
    print(f"syncing stock universe for {trade_date.isoformat()}")
    rows = fetch_all_stock(trade_date)
    print(f"fetched {len(rows)} rows from baostock")
    written = upsert_rows(database_url, rows)
    print(f"upserted {written} rows into stock_universe_daily")
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync baostock query_all_stock for one day into stock_universe_daily."
    )
    parser.add_argument(
        "--day",
        type=parse_day,
        default=date.today(),
        help="Trade date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL URL (default: DATABASE_URL or postgresql:///analytics)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args.day, args.database_url)
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
