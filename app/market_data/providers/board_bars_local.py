"""Synthesize board daily bars from local constituents + stock_daily_bar.

Equal-weight index built from member stocks' pct_chg (baostock stock bars).
Requires board_constituent_daily to already have rows for the board.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from app.db import fetch_board_constituent_codes, fetch_stock_bars_for_codes
from app.market_data.normalize import BoardDailyBar

BoardType = Literal["industry", "concept"]
SOURCE = "local_synth"
_BASE = Decimal("1000")


def fetch_board_daily_bars(
    board_type: BoardType,
    board_code: str,
    start: date,
    end: date,
) -> list[BoardDailyBar]:
    codes = fetch_board_constituent_codes(board_type, board_code, as_of=end)
    if not codes:
        raise RuntimeError(
            f"no board_constituent_daily rows for {board_type}:{board_code}; "
            "run sync_board_constituents first"
        )

    rows = fetch_stock_bars_for_codes(codes, start, end)
    if not rows:
        raise RuntimeError(
            f"no stock_daily_bar rows for constituents of {board_type}:{board_code}"
        )

    by_day: dict[date, list[dict]] = {}
    for row in rows:
        by_day.setdefault(row["trade_date"], []).append(row)

    bars: list[BoardDailyBar] = []
    prev_close = _BASE
    for trade_date in sorted(by_day):
        day_rows = by_day[trade_date]
        pcts: list[Decimal] = []
        volume = 0
        amount = Decimal("0")
        for item in day_rows:
            pct = item.get("pct_chg")
            if pct is None and item.get("close") is not None and item.get("preclose"):
                pre = item["preclose"]
                if pre:
                    pct = (item["close"] - pre) / pre * Decimal("100")
            if pct is not None:
                pcts.append(Decimal(str(pct)))
            if item.get("volume") is not None:
                volume += int(item["volume"])
            if item.get("amount") is not None:
                amount += Decimal(str(item["amount"]))
        if not pcts:
            continue
        avg_pct = sum(pcts, Decimal("0")) / Decimal(len(pcts))
        close = prev_close * (Decimal("1") + avg_pct / Decimal("100"))
        open_ = prev_close
        # Approximate high/low from same-day extreme member moves.
        high = prev_close * (
            Decimal("1") + max(pcts) / Decimal("100")
        )
        low = prev_close * (
            Decimal("1") + min(pcts) / Decimal("100")
        )
        if high < max(open_, close):
            high = max(open_, close)
        if low > min(open_, close):
            low = min(open_, close)
        amplitude = (
            (high - low) / prev_close * Decimal("100") if prev_close else None
        )
        bars.append(
            BoardDailyBar(
                trade_date=trade_date,
                board_type=board_type,
                board_code=board_code.strip().upper(),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume or None,
                amount=amount if amount else None,
                pct_chg=avg_pct,
                turn=None,
                amplitude=amplitude,
                adjustflag=3,
                source=SOURCE,
            )
        )
        prev_close = close

    if not bars:
        raise RuntimeError(
            f"local_synth produced no bars for {board_type}:{board_code}"
        )
    return bars
