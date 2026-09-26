"""Cross-sectional board heat from the return of a 2-day average price.

avg is (high + low + close) / 3. Its 2-day mean replaces the raw pct_chg:
the ranking return is that mean's change versus the previous mean. The return
is then smoothed with a 5-day mean before ranking. Rank is within one board
type and one trade date. The highest smoothed return is rank 1. Equal values
share a rank and the next rank skips. Short heat is the 5-day mean of that
board's own ranks; long heat is the 20-day mean. Windows that are not full
stay empty, and the raw daily pct_chg is kept on the row.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

INDUSTRY = "industry"
SHORT_WINDOW = 5
LONG_WINDOW = 20
SHORT_HEAT_RERANK_LIMIT = 100


AVG_MA = 2


@dataclass(frozen=True)
class BoardReturn:
    trade_date: date
    board_code: str
    pct_chg: Decimal | None
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class BoardHeatRow:
    trade_date: date
    board_type: str
    board_code: str
    pct_chg: Decimal
    rank_no: int | None
    universe_n: int | None
    heat_short: Decimal | None
    heat_long: Decimal | None


def top_short_heat_keys(
    rows: list[tuple[str, Decimal | None]],
    limit: int = SHORT_HEAT_RERANK_LIMIT,
) -> set[str]:
    """Re-rank by smoothed short heat. The smallest heat is rank 1.

    Equal heats share a rank and the next rank skips. Keys with an empty
    short heat are left out. The returned set is everyone whose new rank is
    within `limit`.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")
    ranked: list[tuple[Decimal, str]] = []
    for key, heat in rows:
        if not key or heat is None:
            continue
        ranked.append((heat, key))
    ranked.sort(key=lambda item: (item[0], item[1]))
    kept: set[str] = set()
    rank_no = 0
    previous: Decimal | None = None
    for index, (heat, key) in enumerate(ranked, start=1):
        if previous is None or heat != previous:
            rank_no = index
            previous = heat
        if rank_no > limit:
            break
        kept.add(key)
    return kept


def compute_heat(returns: list[BoardReturn], board_type: str = INDUSTRY) -> list[BoardHeatRow]:
    """Smooth each return with MA5, rank that value, then smooth the ranks."""
    _require_unique(returns)
    by_code: dict[str, list[BoardReturn]] = defaultdict(list)
    for item in returns:
        by_code[item.board_code].append(item)
    for series in by_code.values():
        series.sort(key=lambda item: item.trade_date)

    smoothed: list[_RankInput] = []
    for board_code, series in by_code.items():
        ma2_returns = _ma2_returns(series)
        values = [value for value in ma2_returns if value is not None]
        seen = 0
        for item, value in zip(series, ma2_returns):
            if value is None:
                continue
            smoothed_return = _window_mean(values, seen, SHORT_WINDOW)
            seen += 1
            if smoothed_return is None:
                continue
            smoothed.append(
                _RankInput(
                    trade_date=item.trade_date,
                    board_code=board_code,
                    pct_chg=smoothed_return,
                )
            )
    ranked = _rank_by_day(smoothed)

    rows: list[BoardHeatRow] = []
    for board_code, series in by_code.items():
        ranked_days = [item.trade_date for item in series if (item.trade_date, board_code) in ranked]
        ranks = [ranked[(day, board_code)][1] for day in ranked_days]
        rank_index = {day: index for index, day in enumerate(ranked_days)}
        for item in series:
            key = (item.trade_date, board_code)
            if key not in ranked:
                rows.append(
                    BoardHeatRow(
                        trade_date=item.trade_date,
                        board_type=board_type,
                        board_code=board_code,
                        pct_chg=item.pct_chg,
                        rank_no=None,
                        universe_n=None,
                        heat_short=None,
                        heat_long=None,
                    )
                )
                continue
            index = rank_index[item.trade_date]
            _smoothed, rank_no, universe_n = ranked[key]
            rows.append(
                BoardHeatRow(
                    trade_date=item.trade_date,
                    board_type=board_type,
                    board_code=board_code,
                    pct_chg=item.pct_chg,
                    rank_no=rank_no,
                    universe_n=universe_n,
                    heat_short=_window_mean(ranks, index, SHORT_WINDOW),
                    heat_long=_window_mean(ranks, index, LONG_WINDOW),
                )
            )
    rows.sort(key=lambda row: (row.trade_date, row.board_code))
    return rows


def find_dirty_start(
    computed: list[BoardHeatRow],
    stored: list[BoardHeatRow],
) -> date | None:
    """Earliest day whose stored rows differ from the computed rows.

    None means the stored heat already matches, including an empty pair.
    """
    computed_by_day = _by_day(computed)
    stored_by_day = _by_day(stored)
    if computed_by_day == stored_by_day:
        return None
    for day in sorted(set(computed_by_day) | set(stored_by_day)):
        if computed_by_day.get(day) != stored_by_day.get(day):
            return day
    return None


def alignment_errors(
    returns: list[BoardReturn],
    rows: list[BoardHeatRow],
) -> list[str]:
    """Date coverage plus the leading empty MA windows."""
    errors: list[str] = []
    source = {(item.trade_date, item.board_code) for item in returns}
    heat = {(row.trade_date, row.board_code) for row in rows}
    missing = len(source - heat)
    extra = len(heat - source)
    if missing or extra:
        errors.append(f"date keys differ: missing={missing} extra={extra}")

    if returns or rows:
        source_end = max((item.trade_date for item in returns), default=None)
        heat_end = max((row.trade_date for row in rows), default=None)
        if source_end != heat_end:
            errors.append(f"end date differs: bars={source_end} heat={heat_end}")

    by_code: dict[str, list[BoardHeatRow]] = defaultdict(list)
    source_by_code: dict[str, list[BoardReturn]] = defaultdict(list)
    for item in returns:
        source_by_code[item.board_code].append(item)
    for series in source_by_code.values():
        series.sort(key=lambda item: item.trade_date)
    for row in rows:
        by_code[row.board_code].append(row)
    for board_code, series in by_code.items():
        series.sort(key=lambda row: row.trade_date)
        errors.extend(_rank_presence_errors(board_code, source_by_code[board_code], series))
        ranked_rows = [row for row in series if row.rank_no is not None]
        errors.extend(_null_window_errors(board_code, ranked_rows, "heat_short", SHORT_WINDOW))
        errors.extend(_null_window_errors(board_code, ranked_rows, "heat_long", LONG_WINDOW))
    return errors


def _require_unique(returns: list[BoardReturn]) -> None:
    seen: set[tuple[date, str]] = set()
    for item in returns:
        key = (item.trade_date, item.board_code)
        if key in seen:
            raise ValueError(f"duplicate board return: {item.trade_date} {item.board_code}")
        seen.add(key)


@dataclass(frozen=True)
class _RankInput:
    trade_date: date
    board_code: str
    pct_chg: Decimal


def _rank_by_day(
    returns: list[_RankInput],
) -> dict[tuple[date, str], tuple[Decimal, int, int]]:
    by_date: dict[date, list[_RankInput]] = defaultdict(list)
    for item in returns:
        by_date[item.trade_date].append(item)

    ranked: dict[tuple[date, str], tuple[Decimal, int, int]] = {}
    for trade_date, items in by_date.items():
        ordered = sorted(items, key=lambda item: (-item.pct_chg, item.board_code))
        universe_n = len(ordered)
        rank_no = 0
        previous: Decimal | None = None
        for index, item in enumerate(ordered, start=1):
            if previous is None or item.pct_chg != previous:
                rank_no = index
                previous = item.pct_chg
            ranked[(trade_date, item.board_code)] = (item.pct_chg, rank_no, universe_n)
    return ranked


def _window_mean(values: list[int] | list[Decimal], index: int, window: int) -> Decimal | None:
    if index + 1 < window:
        return None
    chunk = values[index + 1 - window : index + 1]
    return sum(chunk, Decimal(0)) / Decimal(window)


def _ma2_returns(series: list[BoardReturn]) -> list[Decimal | None]:
    """Return of avg's MA2. The first two bars have no return."""
    avgs = [(item.high + item.low + item.close) / Decimal(3) for item in series]
    out: list[Decimal | None] = [None] * len(avgs)
    if len(avgs) < AVG_MA + 1:
        return out
    previous = (avgs[0] + avgs[1]) / Decimal(AVG_MA)
    for index in range(AVG_MA, len(avgs)):
        current = (avgs[index - 1] + avgs[index]) / Decimal(AVG_MA)
        if previous != 0:
            out[index] = (current - previous) / previous * Decimal(100)
        previous = current
    return out


def _ranked_days(series: list[BoardReturn]) -> dict[date, bool]:
    values = _ma2_returns(series)
    present = [value for value in values if value is not None]
    seen = 0
    flags: dict[date, bool] = {}
    for item, value in zip(series, values):
        if value is None:
            flags[item.trade_date] = False
            continue
        flags[item.trade_date] = _window_mean(present, seen, SHORT_WINDOW) is not None
        seen += 1
    return flags


def _rank_presence_errors(
    board_code: str,
    bars: list[BoardReturn],
    series: list[BoardHeatRow],
) -> list[str]:
    flags = _ranked_days(bars)
    errors: list[str] = []
    for row in series:
        ranked = flags.get(row.trade_date, False)
        if ranked and row.rank_no is None:
            errors.append(f"{board_code} {row.trade_date} should have a rank")
        if not ranked and row.rank_no is not None:
            errors.append(f"{board_code} {row.trade_date} rank should be empty")
    return errors


def _signature(
    row: BoardHeatRow,
) -> tuple[str, Decimal, int | None, int | None, Decimal | None, Decimal | None]:
    return (
        row.board_code,
        row.pct_chg,
        row.rank_no,
        row.universe_n,
        row.heat_short,
        row.heat_long,
    )


def _by_day(rows: list[BoardHeatRow]) -> dict[date, tuple[tuple, ...]]:
    grouped: dict[date, list[tuple]] = defaultdict(list)
    for row in rows:
        grouped[row.trade_date].append(_signature(row))
    return {day: tuple(sorted(items)) for day, items in grouped.items()}


def _null_window_errors(
    board_code: str,
    series: list[BoardHeatRow],
    field: str,
    window: int,
) -> list[str]:
    values = [getattr(row, field) for row in series]
    lead = window - 1
    if len(series) < window:
        if any(value is not None for value in values):
            return [f"{board_code} {field} should be empty when the series is shorter than {window}"]
        return []
    errors: list[str] = []
    if any(value is not None for value in values[:lead]):
        errors.append(f"{board_code} {field} should be empty on the first {lead} days")
    if any(value is None for value in values[lead:]):
        errors.append(f"{board_code} {field} should be present from day {window}")
    return errors
