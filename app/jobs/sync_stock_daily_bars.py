"""Sync unadjusted daily bars for A-share stocks from multiple sources."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta

import baostock as bs

from app.db import (
    fetch_all_latest_trading_stock_codes,
    fetch_completed_sync_codes,
    fetch_latest_universe_date,
    save_sync_state,
    upsert_daily_bars,
)
from app.market_data.normalize import DailyBar
from app.market_data.providers import (
    akshare_em_kline,
    akshare_tx_kline,
    baostock_kline,
)

PROVIDERS = (
    ("baostock", baostock_kline.fetch_daily_bars),
    ("akshare_em", akshare_em_kline.fetch_daily_bars),
    ("akshare_tx", akshare_tx_kline.fetch_daily_bars),
)


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        ) from exc


def trading_days_between(start: date, end: date) -> list[date]:
    result = bs.query_trade_dates(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )
    if result.error_code != "0":
        raise RuntimeError(
            f"query_trade_dates failed: {result.error_code} {result.error_msg}"
        )
    days: list[date] = []
    while result.error_code == "0" and result.next():
        day, flag = result.get_row_data()
        if flag == "1":
            days.append(datetime.strptime(day, "%Y-%m-%d").date())
    return days


def resolve_window(
    start: date | None,
    end: date | None,
    trading_days: int | None,
) -> tuple[date, date]:
    resolved_end = end or fetch_latest_universe_date()
    if resolved_end is None:
        raise RuntimeError(
            "no stock_universe_daily data found; sync universe first or pass --end-date"
        )

    if start is not None and trading_days is not None:
        raise RuntimeError("use either --start-date or --trading-days, not both")

    if start is not None:
        if start > resolved_end:
            raise RuntimeError("--start-date must be on or before --end-date")
        return start, resolved_end

    lookback = trading_days if trading_days is not None else 200
    if lookback < 1:
        raise RuntimeError("--trading-days must be >= 1")

    # Pull enough calendar days to cover the requested trading-day count.
    probe_start = resolved_end - timedelta(days=max(lookback * 3, lookback + 30))
    days = trading_days_between(probe_start, resolved_end)
    if not days:
        raise RuntimeError("no trading days found in the requested window")
    if len(days) < lookback:
        return days[0], resolved_end
    return days[-lookback], resolved_end


def fetch_with_fallback(code: str, start: date, end: date) -> tuple[str, list[DailyBar]]:
    errors: list[str] = []
    for name, fetch in PROVIDERS:
        try:
            bars = fetch(code, start, end)
            if bars:
                return name, bars
            errors.append(f"{name}: empty")
        except Exception as exc:  # noqa: BLE001 - provider boundary
            errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors) if errors else "all providers failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync unadjusted daily bars for all latest trading A-shares. "
            "Primary source baostock, then Eastmoney, then Tencent."
        )
    )
    parser.add_argument("--start-date", type=parse_day, help="Inclusive start date YYYY-MM-DD")
    parser.add_argument(
        "--end-date",
        type=parse_day,
        help="Inclusive end date YYYY-MM-DD (default: latest stock_universe_daily date)",
    )
    parser.add_argument(
        "--trading-days",
        type=int,
        help="Look back N trading days ending at --end-date (default: 200 if no --start-date)",
    )
    parser.add_argument("--code", help="Only sync one baostock code, e.g. sh.600000")
    parser.add_argument("--limit", type=int, help="Only sync the first N codes")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip codes already marked ok for the same start/end window",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.05,
        help="Seconds to sleep between stocks (default: 0.05)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    login = bs.login()
    if login.error_code != "0":
        print(f"error: baostock login failed: {login.error_msg}", file=sys.stderr)
        return 1

    try:
        start, end = resolve_window(args.start_date, args.end_date, args.trading_days)
        print(f"window = {start.isoformat()} .. {end.isoformat()}", flush=True)

        if args.code:
            codes = [args.code.strip().lower()]
        else:
            codes = fetch_all_latest_trading_stock_codes()
            if args.limit is not None:
                codes = codes[: max(args.limit, 0)]

        if args.resume:
            done = fetch_completed_sync_codes(start, end)
            before = len(codes)
            codes = [code for code in codes if code not in done]
            print(f"resume skipped {before - len(codes)} codes", flush=True)

        print(f"stocks to sync = {len(codes)}", flush=True)
        ok = 0
        failed = 0
        total_rows = 0

        for index, code in enumerate(codes, start=1):
            print(f"[{index}/{len(codes)}] {code} ...", flush=True)
            try:
                source, bars = fetch_with_fallback(code, start, end)
                # Keep only bars inside the requested window.
                bars = [bar for bar in bars if start <= bar.trade_date <= end]
                written = upsert_daily_bars(bars)
                save_sync_state(code, start, end, "ok", source, written, None)
                ok += 1
                total_rows += written
                print(
                    f"[{index}/{len(codes)}] {code} ok source={source} rows={written}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - per-stock boundary
                failed += 1
                save_sync_state(code, start, end, "error", None, 0, str(exc))
                print(
                    f"[{index}/{len(codes)}] {code} error: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            if args.sleep > 0:
                time.sleep(args.sleep)

        print(
            f"done ok={ok} failed={failed} rows={total_rows} "
            f"window={start.isoformat()}..{end.isoformat()}",
            flush=True,
        )
        return 1 if failed and ok == 0 else 0
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        bs.logout()


if __name__ == "__main__":
    raise SystemExit(main())
