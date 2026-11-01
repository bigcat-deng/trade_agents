"""Align stock short/long heat with stock_daily_bar and store it.

Uses the same ranking pipeline as board heat (avg→MA2 return→MA5→rank→
heat_short MA5 / heat_long MA20), with board_type fixed to ``stock``.

Default is a full dirty-start align. Pass ``--trading-days N`` to recompute
with a warm-up lookback and rewrite only the tip N trading days (daily sync).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from app.db import (
    fetch_max_stock_bar_date,
    fetch_stock_bar_dates_ending,
    fetch_stock_heat,
    fetch_stock_returns,
    replace_stock_heat,
)
from app.market_data.board_heat import (
    AVG_MA,
    LONG_WINDOW,
    SHORT_WINDOW,
    BoardReturn,
    alignment_errors,
    compute_heat,
    find_dirty_start,
)

STOCK_HEAT_TYPE = "stock"
# Bars needed before the write tip so MA2 return + MA5 rank + MA20 heat fill.
WARMUP_EXTRA = LONG_WINDOW + SHORT_WINDOW + AVG_MA


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rank A-share stocks from stock_daily_bar and store heat in "
            "stock_heat_daily. Default: full history. --trading-days N: tip N days."
        )
    )
    parser.add_argument(
        "--trading-days",
        type=int,
        default=None,
        help="Rewrite only the last N trading days (warm-up fetch included).",
    )
    return parser


def _returns_from_rows(rows: list[tuple]) -> list[BoardReturn]:
    return [
        BoardReturn(
            trade_date=trade_date,
            board_code=code,
            pct_chg=pct_chg,
            high=high,
            low=low,
            close=close,
        )
        for trade_date, code, pct_chg, high, low, close in rows
    ]


def tip_write_window(
    bar_dates_oldest_first: list[date],
    trading_days: int,
) -> tuple[date, date] | None:
    """Map fetched bar dates to (fetch_start, write_start).

    ``bar_dates_oldest_first`` should already be the tip window including warm-up.
    Returns None when fewer than ``trading_days`` dates are available.
    """
    if trading_days < 1:
        raise ValueError("trading_days must be >= 1")
    if len(bar_dates_oldest_first) < trading_days:
        return None
    write_start = bar_dates_oldest_first[-trading_days]
    fetch_start = bar_dates_oldest_first[0]
    return fetch_start, write_start


def _align_full() -> int:
    try:
        returns = _returns_from_rows(fetch_stock_returns())
        computed = compute_heat(returns, STOCK_HEAT_TYPE)
        problems = alignment_errors(returns, computed)
        if problems:
            print("error: computed heat is not aligned with stock bars:", file=sys.stderr)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1

        stored = fetch_stock_heat()
        dirty = find_dirty_start(computed, stored)
        if dirty is None:
            end = max((row.trade_date for row in computed), default=None)
            end_text = end.isoformat() if end is not None else "none"
            print(
                f"stock heat already aligned through {end_text} ({len(computed)} rows)",
                flush=True,
            )
            return 0

        to_write = [row for row in computed if row.trade_date >= dirty]
        written = replace_stock_heat(dirty, to_write)
        stored_after = fetch_stock_heat()
        problems = alignment_errors(returns, stored_after)
        if problems or find_dirty_start(computed, stored_after) is not None:
            print("error: stored heat is still not aligned:", file=sys.stderr)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1

        end = max(row.trade_date for row in computed).isoformat() if computed else "none"
        print(
            f"recomputed stock heat from {dirty.isoformat()} through {end}, "
            f"wrote {written} rows, total {len(stored_after)}",
            flush=True,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _align_tip(trading_days: int) -> int:
    try:
        tip = fetch_max_stock_bar_date()
        if tip is None:
            print("stock heat: no stock_daily_bar rows", flush=True)
            return 0

        need = trading_days + WARMUP_EXTRA
        bar_dates = fetch_stock_bar_dates_ending(tip, need)
        window = tip_write_window(bar_dates, trading_days)
        if window is None:
            print(
                f"error: need at least {trading_days} bar dates, got {len(bar_dates)}",
                file=sys.stderr,
            )
            return 1
        fetch_start, write_start = window

        returns = _returns_from_rows(fetch_stock_returns(start=fetch_start))
        computed = compute_heat(returns, STOCK_HEAT_TYPE)
        problems = alignment_errors(returns, computed)
        if problems:
            print("error: computed tip heat is not aligned with stock bars:", file=sys.stderr)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1

        to_write = [row for row in computed if row.trade_date >= write_start]
        written = replace_stock_heat(write_start, to_write)
        end = max((row.trade_date for row in to_write), default=write_start)
        print(
            f"recomputed stock heat tip {write_start.isoformat()}..{end.isoformat()} "
            f"(fetch from {fetch_start.isoformat()}), wrote {written} rows",
            flush=True,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.trading_days is not None:
        if args.trading_days < 1:
            print("error: --trading-days must be >= 1", file=sys.stderr)
            return 1
        return _align_tip(args.trading_days)
    return _align_full()


if __name__ == "__main__":
    raise SystemExit(main())
