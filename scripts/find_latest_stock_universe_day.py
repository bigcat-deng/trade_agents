#!/usr/bin/env python3
"""Find the latest day where baostock query_all_stock returns data."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import baostock as bs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find the latest day with baostock query_all_stock data."
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=60,
        help="How many calendar days to look back from today (default: 60)",
    )
    return parser.parse_args(argv)


def log(message: str) -> None:
    print(message, flush=True)


def trading_days(start: date, end: date) -> list[str]:
    result = bs.query_trade_dates(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )
    if result.error_code != "0":
        raise RuntimeError(
            f"query_trade_dates failed: {result.error_code} {result.error_msg}"
        )

    days: list[str] = []
    while result.error_code == "0" and result.next():
        day, flag = result.get_row_data()
        if flag == "1":
            days.append(day)
    return days


def probe_all_stock(day: str) -> tuple[bool, int]:
    """Return (has_data, first_page_row_count) without scanning every page."""
    result = bs.query_all_stock(day=day)
    if result.error_code != "0":
        raise RuntimeError(
            f"query_all_stock failed for {day}: {result.error_code} {result.error_msg}"
        )

    first_page = len(getattr(result, "data", []) or [])
    return first_page > 0, first_page


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.lookback_days < 1:
        print("error: --lookback-days must be >= 1", file=sys.stderr)
        return 1

    today = date.today()
    start = today - timedelta(days=args.lookback_days)
    log(f"today = {today.isoformat()}")
    log(
        f"lookback = {args.lookback_days} days "
        f"({start.isoformat()} .. {today.isoformat()})"
    )

    login = bs.login()
    if login.error_code != "0":
        print(f"error: baostock login failed: {login.error_msg}", file=sys.stderr)
        return 1

    try:
        days = trading_days(start, today)
        log(f"trading days found = {len(days)}")
        if days:
            log(f"latest trading day in calendar = {days[-1]}")

        total = len(days)
        for index, day in enumerate(reversed(days), start=1):
            log(f"checking {day} ({index}/{total}) ...")
            has_data, first_page = probe_all_stock(day)
            if not has_data:
                log(f"{day} 0")
                continue

            log(f"{day} has data (first page rows = {first_page})")
            log(f"latest day with data = {day}")
            log(
                "sync with:\n"
                f"  .venv/bin/python -m app.jobs.sync_stock_universe --day {day}"
            )
            return 0

        log("latest day with data = none")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        bs.logout()


if __name__ == "__main__":
    raise SystemExit(main())
