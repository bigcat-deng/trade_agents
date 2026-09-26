"""Sync Tonghuashun industry/concept board lists into board_universe_daily."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime

import psycopg

from app.db import database_url, replace_board_universe
from app.market_data.providers import akshare_ths_board


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid day {value!r}; expected YYYY-MM-DD"
        ) from exc


def fetch_best_prior_counts(before: date) -> tuple[int, int]:
    """Largest healthy THS snapshot before `before` (industry>=50)."""
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT trade_date,
                       COUNT(*) FILTER (WHERE board_type = 'industry') AS industry_n,
                       COUNT(*) FILTER (WHERE board_type = 'concept') AS concept_n
                FROM board_universe_daily
                WHERE trade_date < %s
                  AND source = 'akshare_ths'
                GROUP BY trade_date
                HAVING COUNT(*) FILTER (WHERE board_type = 'industry') >= 50
                ORDER BY industry_n DESC, concept_n DESC, trade_date DESC
                LIMIT 1
                """,
                (before,),
            )
            row = cur.fetchone()
            if not row:
                return 0, 0
            return int(row[1] or 0), int(row[2] or 0)


def quality_ok(
    industry: int,
    concept: int,
    *,
    min_industry: int,
    min_concept: int,
    prior_industry: int,
    prior_concept: int,
) -> tuple[bool, str]:
    if industry < min_industry:
        return False, f"industry={industry} < min_industry={min_industry}"
    if concept < min_concept:
        return False, f"concept={concept} < min_concept={min_concept}"
    if prior_industry >= 50 and industry < int(prior_industry * 0.7):
        return (
            False,
            f"industry={industry} much worse than prior={prior_industry}",
        )
    if prior_concept >= 100 and concept < int(prior_concept * 0.5):
        return (
            False,
            f"concept={concept} much worse than prior={prior_concept}",
        )
    return True, "ok"


def run(
    trade_date: date,
    board_type: str | None,
    *,
    retries: int,
    min_industry: int,
    min_concept: int,
) -> int:
    print(f"syncing THS board universe for {trade_date.isoformat()}", flush=True)
    prior_industry, prior_concept = fetch_best_prior_counts(trade_date)
    if prior_industry or prior_concept:
        print(
            f"quality baseline prior industry={prior_industry} concept={prior_concept}",
            flush=True,
        )

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        print(f"attempt {attempt}/{retries}", flush=True)
        try:
            info = akshare_ths_board.fetch_all_board_universe(
                trade_date,
                board_type=board_type,  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001 - retry boundary
            last_error = exc
            print(f"attempt {attempt} fetch error: {exc}", file=sys.stderr, flush=True)
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
            continue

        for line in info.attempts:
            print(f"probe: {line}", flush=True)
        if info.note:
            print(f"note: {info.note}", flush=True)
        print(f"source={info.source}", flush=True)

        rows = info.rows
        industry = sum(1 for row in rows if row.board_type == "industry")
        concept = sum(1 for row in rows if row.board_type == "concept")
        print(
            f"fetched industry={industry} concept={concept} total={len(rows)}",
            flush=True,
        )

        if board_type is None:
            ok, reason = quality_ok(
                industry,
                concept,
                min_industry=min_industry,
                min_concept=min_concept,
                prior_industry=prior_industry,
                prior_concept=prior_concept,
            )
            if not ok:
                last_error = RuntimeError(f"quality gate failed: {reason}")
                print(f"attempt {attempt} {last_error}", file=sys.stderr, flush=True)
                if attempt < retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
                continue

        written = replace_board_universe(
            rows, trade_date=trade_date, board_type=board_type
        )
        print(
            f"replaced snapshot with {written} rows in board_universe_daily",
            flush=True,
        )
        return written

    raise RuntimeError(last_error or "board universe sync failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync Tonghuashun industry/concept board names into board_universe_daily. "
            "Board codes are THS ids (industry 881xxx, concept 30xxxx). "
            "Retries on failure; refuses to replace a healthy THS snapshot with a worse download."
        )
    )
    parser.add_argument(
        "--day",
        type=parse_day,
        default=date.today(),
        help="Snapshot date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--board-type",
        choices=("industry", "concept"),
        help="Only sync one board type (default: both)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Full sync attempts on fetch/quality failure (default: 3)",
    )
    parser.add_argument(
        "--min-industry",
        type=int,
        default=80,
        help="Minimum industry boards required when syncing both (default: 80)",
    )
    parser.add_argument(
        "--min-concept",
        type=int,
        default=200,
        help="Minimum concept boards required when syncing both (default: 200)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.retries < 1:
        print("error: --retries must be >= 1", file=sys.stderr)
        return 1
    try:
        written = run(
            args.day,
            args.board_type,
            retries=args.retries,
            min_industry=args.min_industry,
            min_concept=args.min_concept,
        )
        print(f"done rows={written}", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
