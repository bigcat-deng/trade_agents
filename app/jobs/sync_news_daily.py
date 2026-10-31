"""Close-of-day news snapshot: comments, hot ranks, Weibo, notices, CCTV."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime

import psycopg

from app.db import DEFAULT_DATABASE_URL
from app.market_data.codes import to_baostock
from app.market_data.news_daily import (
    WEIBO_PERIOD,
    CctvRow,
    CommentRow,
    FeedOutcome,
    HotRankRow,
    NewsSources,
    NoticeRow,
    WeiboRow,
    collect_snapshot,
    hot_list_records,
    session_date,
    shanghai_now,
)

_RANK_URL = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
_SURGE_URL = "https://emappdata.eastmoney.com/stockrank/getAllHisRcList"
_QUOTE_HOSTS = (
    "push2.eastmoney.com",
    "82.push2.eastmoney.com",
    "79.push2.eastmoney.com",
)

UPSERT_SYNC_STATE_SQL = """
INSERT INTO news_sync_state (
    feed, snapshot_date, last_status, last_rows, last_error
) VALUES (
    %s, %s, %s, %s, %s
)
ON CONFLICT (feed) DO UPDATE SET
    snapshot_date = CASE
        WHEN EXCLUDED.last_status = 'ok' THEN EXCLUDED.snapshot_date
        ELSE news_sync_state.snapshot_date
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
        except KeyError:
            raise
        except Exception as exc:  # noqa: BLE001 - transient source failures
            last_error = exc
            if attempt + 1 == attempts:
                raise
            time.sleep(attempt + 1)
    raise last_error or RuntimeError("retry failed")


class AkshareNewsSources:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def comment(self) -> list[dict]:
        import akshare as ak

        return _records(_retry(ak.stock_comment_em))

    def hot_rank(self) -> list[dict]:
        return self._hot_list(_RANK_URL, surge=False)

    def hot_surge(self) -> list[dict]:
        return self._hot_list(_SURGE_URL, surge=True)

    def _hot_list(self, url: str, *, surge: bool) -> list[dict]:
        items = _retry(lambda: _rank_items(url))
        raw_codes = [str(item.get("sc") or "") for item in items]
        quotes = _quote_by_code(raw_codes)
        try:
            names = dict(self.universe_names())
        except Exception:  # noqa: BLE001 - quotes can still name the row
            names = {}
        codes: list[str] = []
        for raw in raw_codes:
            try:
                codes.append(to_baostock(raw))
            except ValueError:
                continue
        return hot_list_records(
            items,
            names=names,
            quotes=quotes,
            bars=self._session_bars(codes),
            surge=surge,
        )

    def _session_bars(self, codes: list[str]) -> dict[str, dict]:
        if not codes:
            return {}
        day = session_date(shanghai_now())
        try:
            with psycopg.connect(self.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT code, close, preclose, pct_chg
                        FROM stock_daily_bar
                        WHERE trade_date = %s AND code = ANY(%s)
                        """,
                        (day, codes),
                    )
                    return {
                        row[0]: {
                            "close": row[1],
                            "preclose": row[2],
                            "pct_chg": row[3],
                        }
                        for row in cur.fetchall()
                    }
        except Exception:  # noqa: BLE001 - rank still stores without a price
            return {}

    def weibo(self) -> list[dict]:
        import akshare as ak

        return _records(_retry(lambda: ak.stock_js_weibo_report(time_period=WEIBO_PERIOD)))

    def notices(self, notice_type: str, day: date) -> list[dict]:
        import akshare as ak

        def fetch():
            try:
                return ak.stock_notice_report(
                    symbol=notice_type, date=day.strftime("%Y%m%d")
                )
            except KeyError as exc:
                # akshare raises KeyError('代码') when that category has no rows.
                if exc.args == ("代码",):
                    return None
                raise

        return _records(_retry(fetch))

    def cctv(self, day: date) -> list[dict]:
        import akshare as ak

        return _records(_retry(lambda: ak.news_cctv(date=day.strftime("%Y%m%d"))))

    def universe_names(self) -> list[tuple[str, str]]:
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT code, code_name
                    FROM stock_universe_daily
                    WHERE trade_date = (
                        SELECT MAX(trade_date) FROM stock_universe_daily
                    )
                    """
                )
                return [(row[0], row[1]) for row in cur.fetchall()]


def _rank_items(url: str) -> list[dict]:
    import requests

    response = requests.post(
        url,
        json={
            "appId": "appId01",
            "globalId": "786e4c21-70dc-435a-93bb-38",
            "marketType": "",
            "pageNo": 1,
            "pageSize": 100,
        },
        timeout=12,
    )
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, list):
        raise RuntimeError("eastmoney rank list missing data")
    return data


def _quote_by_code(raw_codes: list[str]) -> dict[str, dict]:
    import requests

    pairs: list[tuple[str, str]] = []
    for raw in raw_codes:
        text = raw.strip().upper()
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) != 6:
            continue
        market = "0" if text.startswith(("SZ", "BJ")) else "1"
        pairs.append((text, f"{market}.{digits}"))
    if not pairs:
        return {}
    params = {
        "ut": "f057cbcbce2a86e2866ab8877db1d059",
        "fltt": "2",
        "invt": "2",
        "fields": "f12,f14,f2,f3",
        "secids": ",".join(secid for _raw, secid in pairs),
    }
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://guba.eastmoney.com/",
        }
    )
    diff = None
    for host in _QUOTE_HOSTS:
        try:
            response = session.get(
                f"https://{host}/api/qt/ulist.np/get",
                params=params,
                timeout=4,
            )
            response.raise_for_status()
            diff = (response.json().get("data") or {}).get("diff") or []
        except Exception:  # noqa: BLE001 - another host, then local bars
            diff = None
            continue
        if diff:
            break
    if not diff:
        return {}
    by_digits: dict[str, dict] = {}
    for item in diff:
        if not isinstance(item, dict):
            continue
        digits = "".join(ch for ch in str(item.get("f12") or "") if ch.isdigit())
        if len(digits) != 6:
            continue
        by_digits[digits] = item
    quotes: dict[str, dict] = {}
    for raw, _secid in pairs:
        digits = "".join(ch for ch in raw if ch.isdigit())
        item = by_digits.get(digits)
        if item is None:
            continue
        close = _quote_number(item.get("f2"))
        pct = _quote_number(item.get("f3"))
        change = None
        if close is not None and pct is not None:
            change = close * pct / 100
        quotes[raw] = {
            "name": item.get("f14"),
            "close": close,
            "pct": pct,
            "change": change,
        }
    return quotes


def _quote_number(value: object) -> float | None:
    if value is None or value == "-":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _records(frame) -> list[dict]:
    if frame is None or getattr(frame, "empty", True):
        return []
    return frame.to_dict("records")


def persist(database_url: str, outcome: FeedOutcome) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if outcome.replace:
                _replace(cur, outcome)
            cur.execute(
                UPSERT_SYNC_STATE_SQL,
                (
                    outcome.feed,
                    outcome.snapshot_date,
                    outcome.status,
                    outcome.reported_rows,
                    outcome.error,
                ),
            )
        conn.commit()


def _replace(cur: psycopg.Cursor, outcome: FeedOutcome) -> None:
    if outcome.feed == "stock_comment":
        cur.execute(
            "DELETE FROM stock_comment_daily WHERE trade_date = %s",
            (outcome.snapshot_date,),
        )
        if outcome.rows:
            cur.executemany(
                """
                INSERT INTO stock_comment_daily (
                    trade_date, code, name, close, pct_chg, turnover, pe,
                    main_cost, inst_participation, score, rank_change, rank_no,
                    focus, source
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [row.as_tuple() for row in outcome.rows if isinstance(row, CommentRow)],
            )
        return
    if outcome.feed in {"em_rank", "em_surge"}:
        list_name = outcome.rows[0].list_name if outcome.rows else (
            "rank" if outcome.feed == "em_rank" else "surge"
        )
        cur.execute(
            """
            DELETE FROM stock_hot_rank_daily
            WHERE trade_date = %s AND list_name = %s
            """,
            (outcome.snapshot_date, list_name),
        )
        if outcome.rows:
            cur.executemany(
                """
                INSERT INTO stock_hot_rank_daily (
                    trade_date, list_name, code, name, rank_no, rank_change,
                    close, change_amt, pct_chg, source
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [row.as_tuple() for row in outcome.rows if isinstance(row, HotRankRow)],
            )
        return
    if outcome.feed == "weibo":
        cur.execute(
            """
            DELETE FROM stock_weibo_daily
            WHERE trade_date = %s AND time_period = %s
            """,
            (outcome.snapshot_date, WEIBO_PERIOD),
        )
        if outcome.rows:
            cur.executemany(
                """
                INSERT INTO stock_weibo_daily (
                    trade_date, time_period, name, code, rate, source
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [row.as_tuple() for row in outcome.rows if isinstance(row, WeiboRow)],
            )
        return
    if outcome.feed == "stock_notice":
        for notice_type in outcome.notice_types:
            cur.execute(
                """
                DELETE FROM stock_notice_daily
                WHERE notice_date = %s AND notice_type = %s
                """,
                (outcome.snapshot_date, notice_type),
            )
        if outcome.rows:
            cur.executemany(
                """
                INSERT INTO stock_notice_daily (
                    notice_id, notice_date, code, name, notice_type, title, url, source
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (notice_id) DO UPDATE SET
                    notice_date = EXCLUDED.notice_date,
                    code = EXCLUDED.code,
                    name = EXCLUDED.name,
                    notice_type = EXCLUDED.notice_type,
                    title = EXCLUDED.title,
                    url = EXCLUDED.url,
                    source = EXCLUDED.source,
                    ingested_at = now()
                """,
                [row.as_tuple() for row in outcome.rows if isinstance(row, NoticeRow)],
            )
        return
    if outcome.feed == "cctv":
        cur.execute(
            "DELETE FROM news_cctv_item WHERE broadcast_date = %s",
            (outcome.snapshot_date,),
        )
        if outcome.rows:
            cur.executemany(
                """
                INSERT INTO news_cctv_item (
                    broadcast_date, title, content, source
                ) VALUES (%s, %s, %s, %s)
                """,
                [row.as_tuple() for row in outcome.rows if isinstance(row, CctvRow)],
            )
        return
    raise ValueError(f"unknown feed: {outcome.feed}")


def run(
    database_url: str,
    now: datetime | None = None,
    sources: NewsSources | None = None,
) -> int:
    current = shanghai_now(now)
    print(f"news daily snapshot at {current.isoformat()}")
    outcomes = collect_snapshot(sources or AkshareNewsSources(database_url), current)
    exit_code = 0
    for outcome in outcomes:
        detail = outcome.note
        if outcome.error:
            detail = f"{detail} {outcome.error}".strip()
        print(
            f"{outcome.feed} {outcome.status} rows={outcome.reported_rows} "
            f"date={outcome.snapshot_date or '-'} {detail}".rstrip()
        )
        try:
            persist(database_url, outcome)
        except Exception as exc:  # noqa: BLE001 - keep going so other feeds land
            print(f"error: persist {outcome.feed}: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        if outcome.status == "error" and outcome.feed != "cctv":
            exit_code = 1
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Store the close-of-day news snapshot (comments, ranks, Weibo, notices, CCTV)."
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
