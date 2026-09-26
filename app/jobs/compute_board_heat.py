"""Align industry-board heat with board_daily_bar and store it."""

from __future__ import annotations

import sys

from app.db import fetch_board_heat, fetch_board_returns, replace_board_heat
from app.market_data.board_heat import (
    INDUSTRY,
    BoardReturn,
    alignment_errors,
    compute_heat,
    find_dirty_start,
)


def main(argv: list[str] | None = None) -> int:
    del argv  # alignment is the only mode
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
            for trade_date, board_code, pct_chg, high, low, close in fetch_board_returns(INDUSTRY)
        ]
        computed = compute_heat(returns, INDUSTRY)
        problems = alignment_errors(returns, computed)
        if problems:
            print("error: computed heat is not aligned with board bars:", file=sys.stderr)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1

        stored = fetch_board_heat(INDUSTRY)
        dirty = find_dirty_start(computed, stored)
        if dirty is None:
            end = max((row.trade_date for row in computed), default=None)
            end_text = end.isoformat() if end is not None else "none"
            print(
                f"industry heat already aligned through {end_text} ({len(computed)} rows)",
                flush=True,
            )
            return 0

        to_write = [row for row in computed if row.trade_date >= dirty]
        written = replace_board_heat(INDUSTRY, dirty, to_write)
        stored_after = fetch_board_heat(INDUSTRY)
        problems = alignment_errors(returns, stored_after)
        if problems or find_dirty_start(computed, stored_after) is not None:
            print("error: stored heat is still not aligned:", file=sys.stderr)
            for problem in problems:
                print(f"error: {problem}", file=sys.stderr)
            return 1

        end = max(row.trade_date for row in computed).isoformat() if computed else "none"
        print(
            f"recomputed industry heat from {dirty.isoformat()} through {end}, "
            f"wrote {written} rows, total {len(stored_after)}",
            flush=True,
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI exit boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
