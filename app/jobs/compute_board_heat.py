"""Align board heat with board_daily_bar and store it.

Default board type is industry, so an existing run keeps ranking industries only.
Pass ``--board-type concept`` to rank concepts among themselves.
Pass ``--board-type all`` to rank industry first, then concept.
"""

from __future__ import annotations

import argparse
import sys

from app.db import fetch_board_heat, fetch_board_returns, replace_board_heat
from app.market_data.board_heat import (
    BoardReturn,
    alignment_errors,
    compute_heat,
    find_dirty_start,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rank one board type from board_daily_bar and store heat in board_heat_daily. "
            "Industry and concept are ranked separately."
        )
    )
    parser.add_argument(
        "--board-type",
        choices=("industry", "concept", "all"),
        default="industry",
        help="Which boards to rank. Default: industry. all ranks both.",
    )
    return parser


def _align(board_type: str) -> int:
    try:
        returns = [
            BoardReturn(
                trade_date=trade_date,
                board_code=board_code,
                pct_chg=pct_chg,
                high=high,
                low=low,
                close=close,
            )
            for trade_date, board_code, pct_chg, high, low, close in fetch_board_returns(board_type)
        ]
        computed = compute_heat(returns, board_type)
        problems = alignment_errors(returns, computed)
        if problems:
            print("error: computed heat is not aligned with board bars:", file=sys.stderr)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1

        stored = fetch_board_heat(board_type)
        dirty = find_dirty_start(computed, stored)
        if dirty is None:
            end = max((row.trade_date for row in computed), default=None)
            end_text = end.isoformat() if end is not None else "none"
            print(
                f"{board_type} heat already aligned through {end_text} ({len(computed)} rows)",
                flush=True,
            )
            return 0

        to_write = [row for row in computed if row.trade_date >= dirty]
        written = replace_board_heat(board_type, dirty, to_write)
        stored_after = fetch_board_heat(board_type)
        problems = alignment_errors(returns, stored_after)
        if problems or find_dirty_start(computed, stored_after) is not None:
            print("error: stored heat is still not aligned:", file=sys.stderr)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1

        end = max(row.trade_date for row in computed).isoformat() if computed else "none"
        print(
            f"recomputed {board_type} heat from {dirty.isoformat()} through {end}, "
            f"wrote {written} rows, total {len(stored_after)}",
            flush=True,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    board_types = ("industry", "concept") if args.board_type == "all" else (args.board_type,)
    for board_type in board_types:
        code = _align(board_type)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
