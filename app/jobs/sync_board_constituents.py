"""Sync Tonghuashun board/concept constituents into board_constituent_daily."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime

from app.db import (
    BoardListItem,
    fetch_completed_constituent_sync_keys,
    fetch_latest_board_codes,
    fetch_latest_board_universe_date,
    replace_board_constituents,
    save_board_constituent_sync_state,
)
from app.market_data.providers import akshare_ths_board


def parse_day(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid day {value!r}; expected YYYY-MM-DD"
        ) from exc


def fetch_with_retry(
    trade_date: date,
    board_type: str,
    board_code: str,
    *,
    retries: int,
):
    errors: list[str] = []
    for attempt in range(1, retries + 1):
        try:
            return akshare_ths_board.fetch_board_constituents(
                trade_date,
                board_type,  # type: ignore[arg-type]
                board_code,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"attempt {attempt}: {exc}")
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError("; ".join(errors))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync Tonghuashun industry/concept board constituents into "
            "board_constituent_daily. Board codes are THS ids; stock codes are "
            "stored in baostock format. Supports --resume / --retries."
        )
    )
    parser.add_argument(
        "--day",
        type=parse_day,
        help="Snapshot date YYYY-MM-DD (default: latest board_universe_daily date)",
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
        help="Skip boards already marked ok for the same snapshot date",
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

    try:
        trade_date = args.day or fetch_latest_board_universe_date()
        if trade_date is None:
            raise RuntimeError(
                "no board_universe_daily data; run sync_board_universe first or pass --day"
            )
        print(f"snapshot_date = {trade_date.isoformat()}", flush=True)

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
            done = fetch_completed_constituent_sync_keys(trade_date)
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
                    trade_date,
                    item.board_type,
                    item.board_code,
                    retries=args.retries,
                )
                if args.verbose_probe:
                    for line in info.attempts:
                        print(f"  probe: {line}", flush=True)
                written = replace_board_constituents(
                    info.rows,
                    trade_date=trade_date,
                    board_type=item.board_type,
                    board_code=item.board_code,
                )
                save_board_constituent_sync_state(
                    item.board_type,
                    item.board_code,
                    trade_date,
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
            except Exception as exc:  # noqa: BLE001
                failed += 1
                save_board_constituent_sync_state(
                    item.board_type,
                    item.board_code,
                    trade_date,
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

        sources = " ".join(
            f"{name}={count}" for name, count in sorted(source_counts.items())
        )
        print(
            f"done ok={ok} failed={failed} rows={total_rows} "
            f"sources[{sources}] snapshot={trade_date.isoformat()}",
            flush=True,
        )
        return 1 if failed and ok == 0 else 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
