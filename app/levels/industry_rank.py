"""Rank industry boards by the target/stop reward ratio of the latest bar.

The important lines are the same ones drawn on the board Chan chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from app.charts.chan_board import WINDOW, chan_fetch_start, drawn_key_levels
from app.db import fetch_board_daily_bars_many, fetch_latest_board_codes
from app.levels.target_stop import TargetStopPlan, target_stop_plan
from scripts.chan_fractal_probe import avg_return_threshold, prepare_chan_window

HOT = "hot"
COLD = "cold"
SIDEWAYS = "sideways"
BEARISH = "bearish"
BULLISH = "bullish"


@dataclass(frozen=True)
class IndustryPlanRow:
    code: str
    name: str
    trade_date: date | None
    close: float | None
    target: float | None
    buy: float | None
    stop: float | None
    value: str | None
    ratio: float | None
    note: str | None
    state: str | None
    position: str | None
    step: str | None


def rank_industry_plans(as_of: date) -> list[IndustryPlanRow]:
    """One row per industry board.

    Groups are bullish, then sideways, then bearish. Inside a group the
    higher reward:risk ratio comes first.
    """
    boards = fetch_latest_board_codes("industry")
    grouped = fetch_board_daily_bars_many(
        "industry",
        [item.board_code for item in boards],
        chan_fetch_start(as_of),
        as_of,
    )
    rows = [
        _plan_board(item.board_code, item.board_name, grouped.get(item.board_code, []))
        for item in boards
    ]
    return sorted(rows, key=_sort_key)


def _plan_board(
    code: str,
    name: str,
    bars: Sequence[Mapping[str, Any]],
) -> IndustryPlanRow:
    usable = [row for row in bars if _bar_ok(row)]
    if len(usable) < 2:
        return _blank(code, name, None, None, "无K线", None, None, None)
    window = prepare_chan_window(usable, n=WINDOW)
    state = window_state(window)
    step = window_step(window)
    position = window_position(window, state)
    try:
        keys = drawn_key_levels(window)
        plan = target_stop_plan(
            [level.price for level in keys],
            high=float(window.highs[-1]),
            low=float(window.lows[-1]),
            close=float(window.closes[-1]),
        )
    except ValueError:
        close = float(usable[-1]["close"])
        return _blank(
            code, name, usable[-1]["trade_date"], close, "重要线不足", state, position, step
        )
    return _from_plan(code, name, window.dates[-1], plan, state, position, step)


def window_state(window) -> str | None:
    """Current state from the last bar against the latest pivot.

    A bar still inside the pivot, or one that only pokes out by ``th/2`` or
    less, is sideways. Clearing the far side of the pivot by more than
    ``th/2`` is bearish below ZD and bullish above ZG.
    """
    if not window.pivots:
        return None
    avgs = (window.highs + window.lows + window.closes) / 3.0
    _sigma, _mean, threshold = avg_return_threshold(avgs)
    pivot = window.pivots[-1]
    return pivot_state(
        pivot.zd,
        pivot.zg,
        high=float(window.highs[-1]),
        low=float(window.lows[-1]),
        threshold=threshold,
    )


def pivot_state(zd: float, zg: float, *, high: float, low: float, threshold: float) -> str:
    """State of one bar against one pivot. Leaving must exceed ``th/2``."""
    allowance = threshold / 2.0
    if high < zd and zd - high > allowance:
        return BEARISH
    if low > zg and low - zg > allowance:
        return BULLISH
    return SIDEWAYS


def window_step(window) -> str | None:
    """Direction of the last pivot step. One pivot, or a touch, has none."""
    if len(window.pivots) < 2:
        return None
    previous = window.pivots[-2]
    current = window.pivots[-1]
    return pivot_step(previous.zd, previous.zg, current.zd, current.zg)


def pivot_step(prev_zd: float, prev_zg: float, zd: float, zg: float) -> str | None:
    """Last step: the later pivot sits wholly above or wholly below the earlier one.

    Touching the earlier band is not a step.
    """
    if zd > prev_zg:
        return "上移"
    if zg < prev_zd:
        return "下移"
    return None


def state_label(state: str | None, step: str | None) -> str:
    """``当前状态/最后一跳``. No pivot leaves the cell empty."""
    if not state:
        return "—"
    return f"{state}/{step or '—'}"


def window_position(window, state: str | None) -> str | None:
    """Close vs the latest pivot. Only sideways rows get a position."""
    if state != SIDEWAYS or not window.pivots:
        return None
    pivot = window.pivots[-1]
    return pivot_position(pivot.zd, pivot.zg, close=float(window.closes[-1]))


def pivot_position(zd: float, zg: float, *, close: float) -> str:
    """Place ``close`` against pivot ``[ZD, ZG]``.

    Outside the band is 外上 or 外下. Inside, the band is split into three
    equal parts. A close on a third boundary belongs to the upper part.
    Touching ZD is 内下; touching ZG is 内上.
    """
    if close > zg:
        return "外上"
    if close < zd:
        return "外下"
    height = zg - zd
    lower = zd + height / 3.0
    upper = zd + 2.0 * height / 3.0
    if close < lower:
        return "内下"
    if close < upper:
        return "内中"
    return "内上"


def _from_plan(
    code: str,
    name: str,
    trade_date: date,
    plan: TargetStopPlan,
    state: str | None,
    position: str | None,
    step: str | None,
) -> IndustryPlanRow:
    note = "区间外" if plan.mode == "outside" else None
    return IndustryPlanRow(
        code=code,
        name=name,
        trade_date=trade_date,
        close=plan.close,
        target=plan.target,
        buy=plan.buy,
        stop=plan.stop,
        value=plan.value,
        ratio=plan.ratio,
        note=note,
        state=state,
        position=position,
        step=step,
    )


def _blank(
    code: str,
    name: str,
    trade_date: date | None,
    close: float | None,
    note: str,
    state: str | None,
    position: str | None,
    step: str | None,
) -> IndustryPlanRow:
    return IndustryPlanRow(
        code=code,
        name=name,
        trade_date=trade_date,
        close=close,
        target=None,
        buy=None,
        stop=None,
        value=None,
        ratio=None,
        note=note,
        state=state,
        position=position,
        step=step,
    )


def short_heat_bands(rows: Sequence[tuple[str, Any]]) -> dict[str, str]:
    """Mark the hottest and coldest thirds by short heat.

    Smaller heat is hotter. Rows with no heat are left out of the count.
    Equal heats are ordered by code before the cut. Each colored third is
    ``count // 3``; a short list colors nothing.
    """
    ranked = [(heat, code) for code, heat in rows if heat is not None]
    ranked.sort(key=lambda item: (item[0], item[1]))
    band = len(ranked) // 3
    if band == 0:
        return {}
    marks = {code: HOT for _heat, code in ranked[:band]}
    marks.update({code: COLD for _heat, code in ranked[-band:]})
    return marks


_STATE_ORDER = {BULLISH: 0, SIDEWAYS: 1, BEARISH: 2}


def _sort_key(row: IndustryPlanRow) -> tuple:
    """Bullish, sideways, then bearish. Higher ratio first inside a group."""
    group = _STATE_ORDER.get(row.state, len(_STATE_ORDER))
    if row.ratio is None:
        return (group, 1, 0.0, row.code)
    return (group, 0, -row.ratio, row.code)


def _bar_ok(row: Mapping[str, Any]) -> bool:
    return all(row.get(name) is not None for name in ("open", "high", "low", "close"))
