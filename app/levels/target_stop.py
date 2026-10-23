"""Target, buy, and stop from the important lines drawn on a chart.

Callers pass the line prices and the current bar. The instrument type does
not matter. Lines are the horizontal levels already drawn, low to high.

``delta_avg`` is the mean gap between adjacent lines. One extra line is placed
``delta_avg`` above the highest line and one ``delta_avg`` below the lowest.

A bar that does not cross an important line sits in one interval of that
extended grid. The interval's upper edge is the target and its lower edge is
the stop. A bar that crosses one or more important lines uses the midpoint of
the interval above the highest crossed line as the target, and the midpoint of
the interval below the lowest crossed line as the stop.

The buy point splits target and stop so the upper segment is twice the lower
segment: buy = (target + 2 * stop) / 3.

Reward is target − close, risk is close − stop, and the quoted ratio is
reward:risk = x:1. Close above the buy point is a poor trade (性价比低);
close below it is a good one (性价比高).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Sequence

OUTSIDE = "outside"
INTERVAL = "interval"
CROSS = "cross"

VALUE_HIGH = "高"
VALUE_LOW = "低"
VALUE_FLAT = "平"


@dataclass(frozen=True)
class TargetStopPlan:
    """One bar measured against an extended important-line grid."""

    levels: tuple[float, ...]
    delta_avg: float
    extended: tuple[float, ...]
    crossed: tuple[float, ...]
    mode: str
    target: float | None
    buy: float | None
    stop: float | None
    close: float
    reward: float | None
    risk: float | None
    ratio: float | None
    value: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def target_stop_plan(
    levels: Sequence[float],
    *,
    high: float,
    low: float,
    close: float,
) -> TargetStopPlan:
    """Plan the current bar. ``levels`` are the drawn important-line prices."""
    lines = _prepare_levels(levels)
    high_v, low_v, close_v = _prepare_bar(high, low, close)
    delta = (lines[-1] - lines[0]) / (len(lines) - 1)
    extended = (lines[0] - delta, *lines, lines[-1] + delta)
    crossed = tuple(price for price in lines if low_v < price < high_v)

    if crossed:
        target, stop = _cross_edges(extended, lines, crossed)
        mode = CROSS
    else:
        span = _containing_interval(extended, low_v, high_v)
        if span is None:
            return _outside(lines, delta, extended, close_v)
        stop, target = span
        mode = INTERVAL

    buy = (target + 2.0 * stop) / 3.0
    reward = target - close_v
    risk = close_v - stop
    ratio = None if risk == 0.0 else reward / risk
    if close_v > buy:
        value = VALUE_LOW
    elif close_v < buy:
        value = VALUE_HIGH
    else:
        value = VALUE_FLAT
    return TargetStopPlan(
        levels=lines,
        delta_avg=delta,
        extended=extended,
        crossed=crossed,
        mode=mode,
        target=target,
        buy=buy,
        stop=stop,
        close=close_v,
        reward=reward,
        risk=risk,
        ratio=ratio,
        value=value,
    )


def _prepare_levels(levels: Sequence[float]) -> tuple[float, ...]:
    if len(levels) < 2:
        raise ValueError("need at least two important lines")
    cleaned: list[float] = []
    for price in levels:
        value = float(price)
        if not math.isfinite(value):
            raise ValueError("important line prices must be finite")
        cleaned.append(value)
    ordered = tuple(sorted(set(cleaned)))
    if len(ordered) < 2:
        raise ValueError("need at least two distinct important lines")
    return ordered


def _prepare_bar(high: float, low: float, close: float) -> tuple[float, float, float]:
    high_v = float(high)
    low_v = float(low)
    close_v = float(close)
    if not all(math.isfinite(item) for item in (high_v, low_v, close_v)):
        raise ValueError("bar prices must be finite")
    if high_v < low_v:
        raise ValueError("high must be >= low")
    return high_v, low_v, close_v


def _containing_interval(
    extended: tuple[float, ...],
    low: float,
    high: float,
) -> tuple[float, float] | None:
    for left, right in zip(extended, extended[1:]):
        if low >= left and high <= right:
            return left, right
    return None


def _cross_edges(
    extended: tuple[float, ...],
    lines: tuple[float, ...],
    crossed: tuple[float, ...],
) -> tuple[float, float]:
    lowest = min(crossed)
    highest = max(crossed)
    low_at = lines.index(lowest) + 1
    high_at = lines.index(highest) + 1
    lower_left, lower_right = extended[low_at - 1], extended[low_at]
    upper_left, upper_right = extended[high_at], extended[high_at + 1]
    stop = (lower_left + lower_right) / 2.0
    target = (upper_left + upper_right) / 2.0
    return target, stop


def _outside(
    lines: tuple[float, ...],
    delta: float,
    extended: tuple[float, ...],
    close: float,
) -> TargetStopPlan:
    return TargetStopPlan(
        levels=lines,
        delta_avg=delta,
        extended=extended,
        crossed=(),
        mode=OUTSIDE,
        target=None,
        buy=None,
        stop=None,
        close=close,
        reward=None,
        risk=None,
        ratio=None,
        value=None,
    )
