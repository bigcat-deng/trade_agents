"""Akshare Tencent daily K-line provider."""

from __future__ import annotations

from datetime import date

import akshare as ak

from app.market_data.codes import to_akshare_tx
from app.market_data.normalize import DailyBar, from_akshare_tx_row


def fetch_daily_bars(code: str, start: date, end: date) -> list[DailyBar]:
    symbol = to_akshare_tx(code)
    frame = ak.stock_zh_a_hist_tx(
        symbol=symbol,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        adjust="",
    )
    if frame is None or frame.empty:
        return []

    return [
        from_akshare_tx_row(row.to_dict(), code=code)
        for _, row in frame.iterrows()
    ]
