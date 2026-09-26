"""Board daily-bar probe chain: Tonghuashun → optional local synth.

Eastmoney is intentionally not used: THS and EM board taxonomies differ.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Literal

from app.market_data.normalize import BoardDailyBar
from app.market_data.providers import akshare_ths_board, board_bars_local

BoardType = Literal["industry", "concept"]

_last_good_source: str | None = None


class BoardDailyBarsFetchInfo:
    def __init__(
        self,
        bars: list[BoardDailyBar],
        source: str,
        attempts: list[str] | None = None,
    ):
        self.bars = bars
        self.source = source
        self.attempts = attempts or []


def fetch_board_daily_bars(
    board_type: BoardType,
    board_code: str,
    start: date,
    end: date,
    *,
    board_name: str = "",
) -> BoardDailyBarsFetchInfo:
    """Probe Tonghuashun kline, then local equal-weight synth if constituents exist."""
    global _last_good_source
    code = board_code.strip()

    methods: list[tuple[str, Callable[[], list[BoardDailyBar]]]] = [
        (
            "akshare_ths",
            lambda: akshare_ths_board.fetch_board_daily_bars(
                board_type, code, start, end, board_name=board_name
            ),
        ),
        (
            "local_synth",
            lambda: board_bars_local.fetch_board_daily_bars(
                board_type, code, start, end
            ),
        ),
    ]

    if _last_good_source:
        methods.sort(key=lambda item: 0 if item[0] == _last_good_source else 1)

    attempts: list[str] = []
    for source_name, fetch in methods:
        try:
            bars = fetch()
        except Exception as exc:  # noqa: BLE001 - source boundary
            attempts.append(f"{source_name}: fail ({exc})")
            continue
        if not bars:
            attempts.append(f"{source_name}: empty")
            continue
        _last_good_source = source_name
        attempts.append(f"{source_name}: ok ({len(bars)} rows)")
        return BoardDailyBarsFetchInfo(bars, source=source_name, attempts=attempts)

    raise RuntimeError(
        f"all board daily-bar sources failed for {board_type}:{code}; "
        + " | ".join(attempts)
    )
