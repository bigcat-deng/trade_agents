"""Normalize provider rows into baostock-shaped daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.market_data.codes import to_baostock


@dataclass(frozen=True)
class DailyBar:
    trade_date: date
    code: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    preclose: Decimal | None
    volume: int | None
    amount: Decimal | None
    adjustflag: int
    turn: Decimal | None
    tradestatus: int | None
    pct_chg: Decimal | None
    is_st: int | None
    source: str


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("empty date")
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"none", "nan", "null"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_decimal(value)
    if number is None:
        return None
    return int(number)


def from_baostock_row(row: dict[str, Any], source: str = "baostock") -> DailyBar:
    return DailyBar(
        trade_date=_to_date(row["date"]),
        code=to_baostock(str(row["code"])),
        open=_to_decimal(row.get("open")),
        high=_to_decimal(row.get("high")),
        low=_to_decimal(row.get("low")),
        close=_to_decimal(row.get("close")),
        preclose=_to_decimal(row.get("preclose")),
        volume=_to_int(row.get("volume")),
        amount=_to_decimal(row.get("amount")),
        adjustflag=_to_int(row.get("adjustflag")) or 3,
        turn=_to_decimal(row.get("turn")),
        tradestatus=_to_int(row.get("tradestatus")),
        pct_chg=_to_decimal(row.get("pctChg")),
        is_st=_to_int(row.get("isST")),
        source=source,
    )


def from_akshare_em_row(row: dict[str, Any], code: str) -> DailyBar:
    # Eastmoney volume is in lots (手); convert to shares to match baostock.
    volume_lots = _to_int(row.get("成交量"))
    volume = None if volume_lots is None else volume_lots * 100
    return DailyBar(
        trade_date=_to_date(row["日期"]),
        code=to_baostock(code),
        open=_to_decimal(row.get("开盘")),
        high=_to_decimal(row.get("最高")),
        low=_to_decimal(row.get("最低")),
        close=_to_decimal(row.get("收盘")),
        preclose=None,
        volume=volume,
        amount=_to_decimal(row.get("成交额")),
        adjustflag=3,
        turn=_to_decimal(row.get("换手率")),
        tradestatus=1,
        pct_chg=_to_decimal(row.get("涨跌幅")),
        is_st=None,
        source="akshare_em",
    )


def from_akshare_tx_row(row: dict[str, Any], code: str) -> DailyBar:
    # Tencent provider documents volume in shares and amount in CNY.
    date_value = row.get("date") or row.get("日期")
    return DailyBar(
        trade_date=_to_date(date_value),
        code=to_baostock(code),
        open=_to_decimal(row.get("open") or row.get("开盘")),
        high=_to_decimal(row.get("high") or row.get("最高")),
        low=_to_decimal(row.get("low") or row.get("最低")),
        close=_to_decimal(row.get("close") or row.get("收盘")),
        preclose=None,
        volume=_to_int(row.get("volume") or row.get("成交量")),
        amount=_to_decimal(row.get("amount") or row.get("成交额")),
        adjustflag=3,
        turn=None,
        tradestatus=1,
        pct_chg=None,
        is_st=None,
        source="akshare_tx",
    )
