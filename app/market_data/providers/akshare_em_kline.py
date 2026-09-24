"""Akshare Eastmoney daily K-line provider."""

from __future__ import annotations

from datetime import date

import akshare as ak

from app.market_data.codes import to_akshare_em
from app.market_data.normalize import DailyBar, from_akshare_em_row


def fetch_daily_bars(code: str, start: date, end: date) -> list[DailyBar]:
    symbol = to_akshare_em(code)
    frame = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="",
    )
    if frame is None or frame.empty:
        return []

    return [
        from_akshare_em_row(row.to_dict(), code=code)
        for _, row in frame.iterrows()
    ]
