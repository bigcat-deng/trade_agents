"""Rank a board's constituent stocks by short heat inside that set.

Each stock gets the same Chan key lines and target/stop plan used on the
board and analyze pages. Short heat is recomputed only among the members.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from app.charts.chan_board import WINDOW, chan_fetch_start, drawn_key_levels
from app.db import (
    fetch_board_constituents_named,
    fetch_stock_bars_for_codes,
)
from app.levels.target_stop import target_stop_plan
from app.market_data.board_heat import BoardReturn, compute_heat
from scripts.chan_fractal_probe import prepare_chan_window


@dataclass(frozen=True)
class MemberPlanRow:
    code: str
    name: str
    trade_date: date | None
    close: float | None
    yield_rate: float | None
    heat: float | None
    ratio: float | None
    note: str | None


def rank_board_members(
    board_type: str,
    board_code: str,
    as_of: date,
) -> list[MemberPlanRow]:
    """Constituents of one board, hottest short heat first."""
    named = fetch_board_constituents_named(board_type, [board_code], as_of=as_of)
    members = named.get(board_code) or []
    if not members:
        return []
    codes = [code for code, _name in members]
    names = {code: name or code for code, name in members}
    bars = fetch_stock_bars_for_codes(codes, chan_fetch_start(as_of), as_of)
    by_code: dict[str, list[dict[str, object]]] = {code: [] for code in codes}
    for row in bars:
        code = str(row["code"])
        by_code.setdefault(code, []).append(row)
    heat_by_code = _member_short_heat(by_code, as_of)
    rows = [
        _plan_stock(code, names.get(code, code), by_code.get(code, []), heat_by_code.get(code))
        for code in codes
    ]
    return sorted(rows, key=_sort_key)


def _member_short_heat(
    by_code: Mapping[str, Sequence[Mapping[str, Any]]],
    as_of: date,
) -> dict[str, float]:
    returns: list[BoardReturn] = []
    for code, rows in by_code.items():
        for row in rows:
            if not _bar_ok(row):
                continue
            pct = row.get("pct_chg")
            returns.append(
                BoardReturn(
                    trade_date=row["trade_date"],  # type: ignore[arg-type]
                    board_code=code,
                    pct_chg=None if pct is None else Decimal(str(pct)),
                    high=Decimal(str(row["high"])),
                    low=Decimal(str(row["low"])),
                    close=Decimal(str(row["close"])),
                )
            )
    if not returns:
        return {}
    heat: dict[str, tuple[date, float]] = {}
    for row in compute_heat(returns, board_type="member"):
        if row.heat_short is None or row.trade_date > as_of:
            continue
        previous = heat.get(row.board_code)
        if previous is None or row.trade_date > previous[0]:
            heat[row.board_code] = (row.trade_date, float(row.heat_short))
    return {code: value for code, (_day, value) in heat.items()}


def _plan_stock(
    code: str,
    name: str,
    bars: Sequence[Mapping[str, Any]],
    heat: float | None,
) -> MemberPlanRow:
    usable = [row for row in bars if _bar_ok(row)]
    if len(usable) < 2:
        close = float(usable[-1]["close"]) if usable else None
        day = usable[-1]["trade_date"] if usable else None
        return MemberPlanRow(
            code=code,
            name=name,
            trade_date=day,  # type: ignore[arg-type]
            close=close,
            yield_rate=None,
            heat=heat,
            ratio=None,
            note="无K线",
        )
    window = prepare_chan_window(usable, n=WINDOW)
    close = float(window.closes[-1])
    day = window.dates[-1]
    try:
        keys = drawn_key_levels(window)
        plan = target_stop_plan(
            [level.price for level in keys],
            high=float(window.highs[-1]),
            low=float(window.lows[-1]),
            close=close,
        )
    except ValueError:
        return MemberPlanRow(
            code=code,
            name=name,
            trade_date=day,
            close=close,
            yield_rate=None,
            heat=heat,
            ratio=None,
            note="重要线不足",
        )
    if plan.mode == "outside" or plan.target is None or plan.stop is None:
        return MemberPlanRow(
            code=code,
            name=name,
            trade_date=day,
            close=close,
            yield_rate=None,
            heat=heat,
            ratio=None,
            note="区间外" if plan.mode == "outside" else "重要线不足",
        )
    yield_rate = (plan.target - close) / close if close else None
    return MemberPlanRow(
        code=code,
        name=name,
        trade_date=day,
        close=close,
        yield_rate=yield_rate,
        heat=heat,
        ratio=plan.ratio,
        note=None,
    )


def _sort_key(row: MemberPlanRow) -> tuple:
    """Smaller short heat first. Missing heat goes last; tie-break by code."""
    if row.heat is None:
        return (1, 0.0, row.code)
    return (0, row.heat, row.code)


def _bar_ok(row: Mapping[str, Any]) -> bool:
    return all(row.get(name) is not None for name in ("open", "high", "low", "close"))
