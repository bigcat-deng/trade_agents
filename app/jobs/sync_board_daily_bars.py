"""Sync Eastmoney industry/concept board daily bars with resume support."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta

import baostock as bs

from app.db import (
    BoardListItem,
    fetch_completed_board_sync_keys,
    fetch_latest_board_universe_date,
    fetch_latest_board_codes,
    fetch_latest_universe_date,
    save_board_sync_state,
    upsert_board_daily_bars,
)
from app.market_data.providers import board_daily_bars


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
    resolved_end = end or fetch_latest_board_universe_date() or fetch_latest_universe_date()
    if resolved_end is None:
        raise RuntimeError(
            "no board_universe_daily or stock_universe_daily data found; "
            "sync board universe first or pass --end-date"
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

    probe_start = resolved_end - timedelta(days=max(lookback * 3, lookback + 30))
    days = trading_days_between(probe_start, resolved_end)
    if not days:
        raise RuntimeError("no trading days found in the requested window")
    if len(days) < lookback:
        return days[0], resolved_end
    return days[-lookback], resolved_end


def fetch_with_retry(
    board_type: str,
    board_code: str,
    board_name: str,
    start: date,
    end: date,
    *,
    retries: int,
):
    errors: list[str] = []
    for attempt in range(1, retries + 1):
        try:
            info = board_daily_bars.fetch_board_daily_bars(
                board_type,  # type: ignore[arg-type]
                board_code,
                start,
                end,
                board_name=board_name,
            )
            return info
        except Exception as exc:  # noqa: BLE001 - provider boundary
            errors.append(f"attempt {attempt}: {exc}")
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError("; ".join(errors))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync Tonghuashun industry/concept board daily bars into board_daily_bar. "
            "Primary: THS kline by THS board_code; fallback: local equal-weight synth "
            "from THS constituents + stock_daily_bar. No Eastmoney sources. "
            "Requires board_universe_daily (THS) to be synced first."
        )
    )
    parser.add_argument("--start-date", type=parse_day, help="Inclusive start date YYYY-MM-DD")
    parser.add_argument(
        "--end-date",
        type=parse_day,
        help=(
            "Inclusive end date YYYY-MM-DD "
            "(default: latest board_universe_daily date)"
        ),
    )
    parser.add_argument(
        "--trading-days",
        type=int,
        help="Look back N trading days ending at --end-date (default: 200 if no --start-date)",
    )
    parser.add_argument(
        "--board-type",
        choices=("industry", "concept"),
        help="Only sync one board type (default: both)",
    )
    parser.add_argument(
        "--board-code",
        help="Only sync one THS code, e.g. 881151 or 300084",
    )
    parser.add_argument("--limit", type=int, help="Only sync the first N boards")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip boards already marked ok for the same start/end window",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Per-board fetch attempts on failure (default: 3)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.3,
        help="Seconds to sleep between boards (default: 0.3)",
    )
    parser.add_argument(
        "--verbose-probe",
        action="store_true",
        help="Print per-board source probe attempts (noisy)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.retries < 1:
        print("error: --retries must be >= 1", file=sys.stderr)
        return 1

    login = bs.login()
    if login.error_code != "0":
        print(f"error: baostock login failed: {login.error_msg}", file=sys.stderr)
        return 1

    try:
        start, end = resolve_window(args.start_date, args.end_date, args.trading_days)
        print(f"window = {start.isoformat()} .. {end.isoformat()}", flush=True)

        if args.board_code:
            code = args.board_code.strip()
            matches = [
                item
                for item in fetch_latest_board_codes(args.board_type)
                if item.board_code == code
            ]
            if matches:
                boards = matches
            elif args.board_type:
                boards = [
                    BoardListItem(
                        board_type=args.board_type,
                        board_code=code,
                        board_name="",
                    )
                ]
            else:
                raise RuntimeError(
                    f"board code {code} not found in latest board_universe_daily; "
                    "pass --board-type or sync board universe first"
                )
        else:
            boards = fetch_latest_board_codes(args.board_type)
            if not boards:
                raise RuntimeError(
                    "no board_universe_daily rows found; run sync_board_universe first"
                )
            if args.limit is not None:
                boards = boards[: max(args.limit, 0)]

        if args.resume:
            done = fetch_completed_board_sync_keys(start, end)
            before = len(boards)
            boards = [
                item
                for item in boards
                if (item.board_type, item.board_code) not in done
            ]
            print(f"resume skipped {before - len(boards)} boards", flush=True)

        print(f"boards to sync = {len(boards)} retries={args.retries}", flush=True)
        ok = 0
        failed = 0
        total_rows = 0
        source_counts: dict[str, int] = {}

        for index, item in enumerate(boards, start=1):
            label = f"{item.board_type}:{item.board_code}"
            if item.board_name:
                label = f"{label}({item.board_name})"
            print(f"[{index}/{len(boards)}] {label} ...", flush=True)
            try:
                info = fetch_with_retry(
                    item.board_type,
                    item.board_code,
                    item.board_name,
                    start,
                    end,
                    retries=args.retries,
                )
                if args.verbose_probe:
                    for line in info.attempts:
                        print(f"  probe: {line}", flush=True)
                bars = [bar for bar in info.bars if start <= bar.trade_date <= end]
                written = upsert_board_daily_bars(bars)
                save_board_sync_state(
                    item.board_type,
                    item.board_code,
                    start,
                    end,
                    "ok",
                    info.source,
                    written,
                    None,
                )
                ok += 1
                total_rows += written
                source_counts[info.source] = source_counts.get(info.source, 0) + 1
                print(
                    f"[{index}/{len(boards)}] {label} ok source={info.source} rows={written}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - per-board boundary
                failed += 1
                save_board_sync_state(
                    item.board_type,
                    item.board_code,
                    start,
                    end,
                    "error",
                    None,
                    0,
                    str(exc),
                )
                print(
                    f"[{index}/{len(boards)}] {label} error: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            if args.sleep > 0:
                time.sleep(args.sleep)

        sources = " ".join(f"{name}={count}" for name, count in sorted(source_counts.items()))
        print(
            f"done ok={ok} failed={failed} rows={total_rows} "
            f"sources[{sources}] "
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
