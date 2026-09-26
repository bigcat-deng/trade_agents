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


@dataclass(frozen=True)
class BoardUniverseRow:
    trade_date: date
    board_type: str
    board_code: str
    board_name: str
    source: str


@dataclass(frozen=True)
class BoardDailyBar:
    trade_date: date
    board_type: str
    board_code: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None
    amount: Decimal | None
    pct_chg: Decimal | None
    turn: Decimal | None
    amplitude: Decimal | None
    adjustflag: int
    source: str


@dataclass(frozen=True)
class BoardConstituentRow:
    trade_date: date
    board_type: str
    board_code: str
    stock_code: str
    stock_name: str
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


def from_akshare_em_board_name_row(
    row: dict[str, Any],
    *,
    trade_date: date,
    board_type: str,
) -> BoardUniverseRow:
    board_code = str(row["板块代码"]).strip().upper()
    board_name = str(row["板块名称"]).strip()
    if not board_code or not board_name:
        raise ValueError("empty board code or name")
    if board_type not in {"industry", "concept"}:
        raise ValueError(f"invalid board_type: {board_type}")
    return BoardUniverseRow(
        trade_date=trade_date,
        board_type=board_type,
        board_code=board_code,
        board_name=board_name,
        source="akshare_em",
    )


def from_akshare_em_board_hist_row(
    row: dict[str, Any],
    *,
    board_type: str,
    board_code: str,
) -> BoardDailyBar:
    if board_type not in {"industry", "concept"}:
        raise ValueError(f"invalid board_type: {board_type}")
    return BoardDailyBar(
        trade_date=_to_date(row["日期"]),
        board_type=board_type,
        board_code=board_code.strip().upper(),
        open=_to_decimal(row.get("开盘")),
        high=_to_decimal(row.get("最高")),
        low=_to_decimal(row.get("最低")),
        close=_to_decimal(row.get("收盘")),
        volume=_to_int(row.get("成交量")),
        amount=_to_decimal(row.get("成交额")),
        pct_chg=_to_decimal(row.get("涨跌幅")),
        turn=_to_decimal(row.get("换手率")),
        amplitude=_to_decimal(row.get("振幅")),
        adjustflag=3,
        source="akshare_em",
    )


def from_akshare_ths_board_hist_row(
    row: dict[str, Any],
    *,
    board_type: str,
    board_code: str,
    prev_close: Decimal | None = None,
) -> BoardDailyBar:
    """Normalize THS board index row; board_code is the Tonghuashun board id."""
    if board_type not in {"industry", "concept"}:
        raise ValueError(f"invalid board_type: {board_type}")
    open_ = _to_decimal(row.get("开盘价") or row.get("开盘"))
    high = _to_decimal(row.get("最高价") or row.get("最高"))
    low = _to_decimal(row.get("最低价") or row.get("最低"))
    close = _to_decimal(row.get("收盘价") or row.get("收盘"))
    pct_chg = _to_decimal(row.get("涨跌幅"))
    if pct_chg is None and close is not None and prev_close not in (None, 0):
        pct_chg = (close - prev_close) / prev_close * Decimal("100")
    amplitude = _to_decimal(row.get("振幅"))
    if amplitude is None and high is not None and low is not None and prev_close not in (None, 0):
        amplitude = (high - low) / prev_close * Decimal("100")
    return BoardDailyBar(
        trade_date=_to_date(row["日期"]),
        board_type=board_type,
        board_code=str(board_code).strip(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=_to_int(row.get("成交量")),
        amount=_to_decimal(row.get("成交额")),
        pct_chg=pct_chg,
        turn=_to_decimal(row.get("换手率")),
        amplitude=amplitude,
        adjustflag=3,
        source="akshare_ths",
    )


def from_akshare_ths_board_name_row(
    row: dict[str, Any],
    *,
    trade_date: date,
    board_type: str,
) -> BoardUniverseRow:
    board_code = str(row.get("code") or row.get("板块代码") or "").strip()
    board_name = str(row.get("name") or row.get("板块名称") or "").strip()
    if not board_code or not board_name:
        raise ValueError("empty board code or name")
    if board_type not in {"industry", "concept"}:
        raise ValueError(f"invalid board_type: {board_type}")
    return BoardUniverseRow(
        trade_date=trade_date,
        board_type=board_type,
        board_code=board_code,
        board_name=board_name,
        source="akshare_ths",
    )


def from_akshare_ths_board_cons_row(
    row: dict[str, Any],
    *,
    trade_date: date,
    board_type: str,
    board_code: str,
) -> BoardConstituentRow:
    if board_type not in {"industry", "concept"}:
        raise ValueError(f"invalid board_type: {board_type}")
    raw_code = row.get("代码") or row.get("股票代码")
    raw_name = row.get("名称") or row.get("股票简称") or row.get("股票名称")
    stock_code = to_baostock(str(raw_code))
    stock_name = str(raw_name or "").strip()
    if not stock_name:
        raise ValueError("empty stock name")
    return BoardConstituentRow(
        trade_date=trade_date,
        board_type=board_type,
        board_code=str(board_code).strip(),
        stock_code=stock_code,
        stock_name=stock_name,
        source="akshare_ths",
    )


def from_akshare_em_board_cons_row(
    row: dict[str, Any],
    *,
    trade_date: date,
    board_type: str,
    board_code: str,
) -> BoardConstituentRow:
    if board_type not in {"industry", "concept"}:
        raise ValueError(f"invalid board_type: {board_type}")
    raw_code = row.get("代码") or row.get("f12")
    raw_name = row.get("名称") or row.get("f14")
    stock_code = to_baostock(str(raw_code))
    stock_name = str(raw_name or "").strip()
    if not stock_name:
        raise ValueError("empty stock name")
    return BoardConstituentRow(
        trade_date=trade_date,
        board_type=board_type,
        board_code=board_code.strip().upper(),
        stock_code=stock_code,
        stock_name=stock_name,
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
