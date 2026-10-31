"""Append the latest CLS and Tonghuashun flashes."""

from __future__ import annotations

import argparse
import os
import sys
import time

import psycopg

from app.db import DEFAULT_DATABASE_URL
from app.market_data.news_daily import _short_error
from app.market_data.news_flash import FlashRow, normalize_cls, normalize_ths

INSERT_SQL = """
INSERT INTO news_flash (
    source, published_at, title, content, url, level
) VALUES (
    %s, %s, %s, %s, %s, %s
)
ON CONFLICT (source, published_at, title) DO NOTHING
"""

UPSERT_STATE_SQL = """
INSERT INTO news_sync_state (
    feed, cursor_at, last_status, last_rows, last_error
) VALUES (
    %s, %s, %s, %s, %s
)
ON CONFLICT (feed) DO UPDATE SET
    cursor_at = CASE
        WHEN EXCLUDED.last_status = 'ok' THEN COALESCE(EXCLUDED.cursor_at, news_sync_state.cursor_at)
        ELSE news_sync_state.cursor_at
    END,
    last_status = EXCLUDED.last_status,
    last_rows = EXCLUDED.last_rows,
    last_error = EXCLUDED.last_error,
    updated_at = now()
"""


def _retry(fetch, attempts: int = 3):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001 - transient source failures
            last_error = exc
            if attempt + 1 == attempts:
                raise
            time.sleep(attempt + 1)
    raise last_error or RuntimeError("retry failed")


def _records(frame) -> list[dict]:
    if frame is None or getattr(frame, "empty", True):
        return []
    return frame.to_dict("records")


def fetch_cls() -> list[dict]:
    import akshare as ak

    return _records(_retry(lambda: ak.stock_info_global_cls(symbol="重点")))


def fetch_ths() -> list[dict]:
    import akshare as ak

    return _records(_retry(ak.stock_info_global_ths))


def store_flash(
    database_url: str,
    *,
    feed: str,
    rows: list[FlashRow],
    status: str,
    error: str | None,
) -> int:
    cursor_at = max((row.published_at for row in rows), default=None)
    inserted = 0
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if status == "ok":
                for row in rows:
                    cur.execute(INSERT_SQL, row.as_tuple())
                    inserted += int(cur.rowcount or 0)
            cur.execute(
                UPSERT_STATE_SQL,
                (
                    feed,
                    cursor_at if status == "ok" else None,
                    status,
                    inserted if status == "ok" else 0,
                    error,
                ),
            )
        conn.commit()
    return inserted


def run(
    database_url: str,
    *,
    cls_records: list[dict] | None = None,
    ths_records: list[dict] | None = None,
    cls_error: str | None = None,
    ths_error: str | None = None,
    fetch: bool = True,
) -> int:
    print("news flash append")
    exit_code = 0
    if fetch and cls_records is None and cls_error is None:
        try:
            cls_records = fetch_cls()
        except Exception as exc:  # noqa: BLE001 - one source must not block the other
            cls_error = _short_error(exc)
    if fetch and ths_records is None and ths_error is None:
        try:
            ths_records = fetch_ths()
        except Exception as exc:  # noqa: BLE001
            ths_error = _short_error(exc)
    exit_code = _save_source(
        database_url,
        feed="cls",
        records=cls_records,
        error=cls_error,
        normalize=normalize_cls,
    )
    ths_code = _save_source(
        database_url,
        feed="ths",
        records=ths_records,
        error=ths_error,
        normalize=normalize_ths,
    )
    return 1 if exit_code or ths_code else 0


def _save_source(
    database_url: str,
    *,
    feed: str,
    records: list[dict] | None,
    error: str | None,
    normalize,
) -> int:
    if error:
        print(f"{feed} error fetched=0 inserted=0 {error}")
        store_flash(database_url, feed=feed, rows=[], status="error", error=error)
        return 1
    rows, skipped = normalize(records or [])
    if not rows:
        message = "empty"
        print(f"{feed} error fetched=0 inserted=0 skipped={skipped} {message}")
        store_flash(database_url, feed=feed, rows=[], status="error", error=message)
        return 1
    inserted = store_flash(database_url, feed=feed, rows=rows, status="ok", error=None)
    cursor = max(row.published_at for row in rows)
    note = f"skipped={skipped}" if skipped else ""
    print(
        f"{feed} ok fetched={len(rows)} inserted={inserted} "
        f"cursor={cursor.isoformat()} {note}".rstrip()
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append the latest CLS and Tonghuashun flashes."
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
        return run(args.database_url)
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
