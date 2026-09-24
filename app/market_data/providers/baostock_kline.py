"""Baostock daily K-line provider."""

from __future__ import annotations

from datetime import date

import baostock as bs

from app.market_data.normalize import DailyBar, from_baostock_row

FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,isST"
)


def fetch_daily_bars(code: str, start: date, end: date) -> list[DailyBar]:
    result = bs.query_history_k_data_plus(
        code,
        FIELDS,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        frequency="d",
        adjustflag="3",
    )
    if result.error_code != "0":
        raise RuntimeError(
            f"baostock query_history_k_data_plus failed for {code}: "
            f"{result.error_code} {result.error_msg}"
        )

    rows: list[DailyBar] = []
    while result.error_code == "0" and result.next():
        values = result.get_row_data()
        record = dict(zip(result.fields, values, strict=False))
        rows.append(from_baostock_row(record, source="baostock"))
    return rows
