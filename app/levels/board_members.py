"""Rank a board's constituent stocks by short heat inside that set.

Each stock gets the same Chan key lines and target/stop plan used on the
board and analyze pages. Daily bars come from Tonghuashun (same as /analyze).
Short heat is recomputed only among the members.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from app.charts.chan_board import WINDOW, chan_fetch_start, drawn_key_levels
from app.db import fetch_board_constituents_named
from app.levels.target_stop import target_stop_plan
from app.market_data.board_heat import BoardReturn, compute_heat
from app.market_data.codes import to_akshare_em
from app.market_data.providers.ths_line import fetch_ths_daily_bars
from scripts.chan_fractal_probe import prepare_chan_window

_THS_FETCH_WORKERS = 8


@dataclass(frozen=True)
class MemberPlanRow:
    code: str
    name: str
    trade_date: date | None
    close: float | None
    day_return: float | None
    heat: float | None
    ratio: float | None
    target_yield: float | None
    target: float | None
    stop: float | None
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
    by_code = _fetch_ths_bars_by_code(codes, chan_fetch_start(as_of), as_of)
    heat_by_code = _member_short_heat(by_code, as_of)
    rows = [
        _plan_stock(code, names.get(code, code), by_code.get(code, []), heat_by_code.get(code))
        for code in codes
    ]
    return sorted(rows, key=_sort_key)


def _fetch_ths_bars_by_code(
    codes: Sequence[str],
    start: date,
    end: date,
) -> dict[str, list[dict[str, object]]]:
    """Same Tonghuashun daily bars /analyze uses, keyed by baostock code."""
    by_code: dict[str, list[dict[str, object]]] = {code: [] for code in codes}
    if not codes:
        return by_code

    def _one(code: str) -> tuple[str, list[dict[str, object]]]:
        try:
            ths = to_akshare_em(code)
            rows = fetch_ths_daily_bars(ths, start, end)
        except (ValueError, RuntimeError):
            return code, []
        out: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["code"] = code
            out.append(item)
        return code, out

    workers = min(_THS_FETCH_WORKERS, len(codes))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, code) for code in codes]
        for fut in as_completed(futures):
            code, rows = fut.result()
            by_code[code] = rows
    return by_code


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
        tip = usable[-1] if usable else None
        return MemberPlanRow(
            code=code,
            name=name,
            trade_date=None if tip is None else tip["trade_date"],  # type: ignore[arg-type]
            close=None if tip is None else float(tip["close"]),
            day_return=_day_return_at(usable, len(usable) - 1) if usable else None,
            heat=heat,
            ratio=None,
            target_yield=None,
            target=None,
            stop=None,
            note="无K线",
        )
    window = prepare_chan_window(usable, n=WINDOW)
    close = float(window.closes[-1])
    day = window.dates[-1]
    tip = next((row for row in reversed(usable) if row["trade_date"] == day), usable[-1])
    tip_index = usable.index(tip)
    day_return = _day_return_at(usable, tip_index)
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
            day_return=day_return,
            heat=heat,
            ratio=None,
            target_yield=None,
            target=None,
            stop=None,
            note="重要线不足",
        )
    if plan.mode == "outside" or plan.target is None or plan.stop is None:
        return MemberPlanRow(
            code=code,
            name=name,
            trade_date=day,
            close=close,
            day_return=day_return,
            heat=heat,
            ratio=None,
            target_yield=None,
            target=None,
            stop=None,
            note="区间外" if plan.mode == "outside" else "重要线不足",
        )
    target_yield = (plan.target - close) / close if close else None
    return MemberPlanRow(
        code=code,
        name=name,
        trade_date=day,
        close=close,
        day_return=day_return,
        heat=heat,
        ratio=plan.ratio,
        target_yield=target_yield,
        target=float(plan.target),
        stop=float(plan.stop),
        note=None,
    )


def _day_return_at(bars: Sequence[Mapping[str, Any]], index: int) -> float | None:
    """Session return on bars[index] as a fraction.

    Prefer ``pct_chg`` when present (baostock percent). Tonghuashun bars have
    no pct_chg, so fall back to close vs previous close.
    """
    if index < 0 or index >= len(bars):
        return None
    row = bars[index]
    raw = row.get("pct_chg")
    if raw is not None:
        return float(raw) / 100.0
    if index < 1:
        return None
    close = float(row["close"])
    prev = float(bars[index - 1]["close"])
    if prev == 0:
        return None
    return (close - prev) / prev


def _sort_key(row: MemberPlanRow) -> tuple:
    """Smaller short heat first. Missing heat goes last; tie-break by code."""
    if row.heat is None:
        return (1, 0.0, row.code)
    return (0, row.heat, row.code)


def ratio_highlight_codes(
    rows: Sequence[MemberPlanRow],
    *,
    limit: int = 3,
) -> tuple[set[str], set[str]]:
    """Codes with the best and worst yield∶loss among rows that have a ratio.

    Top names are the highest ratios; bottom names are the lowest, chosen from
    whatever remains after the top set so a short list does not paint both.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    scored = [(row.code, float(row.ratio)) for row in rows if row.ratio is not None]
    if not scored:
        return set(), set()
    ordered = sorted(scored, key=lambda item: (-item[1], item[0]))
    top_n = min(limit, len(ordered))
    top = {code for code, _ratio in ordered[:top_n]}
    remaining = [item for item in ordered if item[0] not in top]
    if not remaining:
        return top, set()
    bottom_n = min(limit, len(remaining))
    bottom = {code for code, _ratio in remaining[-bottom_n:]}
    return top, bottom


def _bar_ok(row: Mapping[str, Any]) -> bool:
    return all(row.get(name) is not None for name in ("open", "high", "low", "close"))
