#!/usr/bin/env python3
"""Industry rim top-3 → constituent rim top-3 stock cascade, last 100 sessions.

For each signal day T:
  1. industry short-heat plane (40d, same seriation as the wave page)
  2. near-end rim score, keep top 3 industries
  3. union constituents of those three as of T
  4. in-basket stock heat + rim score, keep top 3 stocks
  5. T+3 / T+10 close vs CSI500

Usage:
  .venv/bin/python scripts/rim_cascade_backtest.py
  .venv/bin/python scripts/rim_cascade_backtest.py --as-of 2026-09-24
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.env import load_env  # noqa: E402

load_env()

from app.db import (  # noqa: E402
    fetch_board_close_heat,
    fetch_board_constituents_many,
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
    fetch_stock_bars_for_codes,
    fetch_stock_code_names,
    fetch_trading_dates_after,
    fetch_trading_dates_ending,
)
from app.market_data.board_heat import compute_heat  # noqa: E402
from app.market_data.csi500 import fetch_csi500_closes  # noqa: E402
from app.themes.board_cross_marks import (  # noqa: E402
    CROSS_HISTORY_DAYS,
    build_cross_mark_overlay,
)
from app.themes.heat_rim_spread import (  # noqa: E402
    macd_up_by_code_from_overlay,
    rank_heat_rim_spread,
)
from app.themes.heat_seriation import (  # noqa: E402
    as_float,
    hotness_grid,
    hotness_series_by_code,
    order_by_trajectory_seriation,
)
from app.themes.stock_basket_wave import (  # noqa: E402
    STOCK_BASKET_MAX,
    bars_to_returns,
    close_heat_from_bars_and_heat,
    group_bars_by_code,
    heat_rows_to_tuples,
)

OUT_DIR = ROOT / "experiments" / "out"
WINDOW_DAYS = 40
SIGNAL_DAYS = 100
HORIZONS = (3, 10)
BOARD_TOP = 3
STOCK_TOP = 3
STOCK_PAD = 25


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    tip = fetch_heat_dates_ending("industry", args.as_of or date.today(), 1)
    as_of = args.as_of or (tip[-1] if tip else date.today())

    need = SIGNAL_DAYS + WINDOW_DAYS + CROSS_HISTORY_DAYS + max(HORIZONS) + STOCK_PAD
    calendar = fetch_trading_dates_ending("industry", as_of, need)
    if len(calendar) < WINDOW_DAYS + SIGNAL_DAYS:
        raise SystemExit(f"not enough trading days: {len(calendar)}")
    calendar.extend(fetch_trading_dates_after("industry", as_of, max(HORIZONS)))
    date_index = {day: i for i, day in enumerate(calendar)}
    if as_of in date_index:
        last_i = date_index[as_of]
    else:
        last_i = max((i for d, i in date_index.items() if d <= as_of), default=-1)
        if last_i < 0:
            raise SystemExit(f"as_of {as_of} not on industry calendar")
    first_signal_i = last_i - SIGNAL_DAYS + 1
    if first_signal_i < WINDOW_DAYS:
        first_signal_i = WINDOW_DAYS
    signal_dates = calendar[first_signal_i : last_i + 1]

    heat_start = calendar[max(0, first_signal_i - WINDOW_DAYS + 1)]
    heat_rows = fetch_industry_heat_window(heat_start, as_of)
    heat_by_day: dict[date, dict[str, float]] = {}
    names: dict[str, str] = {}
    all_board_codes: set[str] = set()
    for trade_date, board_code, board_name, heat_short, _long in heat_rows:
        if board_name:
            names[str(board_code)] = str(board_name)
        val = as_float(heat_short)
        if val is None:
            continue
        code = str(board_code)
        all_board_codes.add(code)
        heat_by_day.setdefault(trade_date, {})[code] = val

    macd_start = calendar[max(0, first_signal_i - WINDOW_DAYS - CROSS_HISTORY_DAYS)]
    board_close_heat = fetch_board_close_heat(
        "industry", sorted(all_board_codes), macd_start, as_of
    )
    index_closes = dict(fetch_csi500_closes(calendar[0], calendar[-1]))

    stock_bar_cache: dict[str, list[dict[str, object]]] = {}
    stock_close: dict[str, dict[date, float]] = {}
    stock_names: dict[str, str] = {}

    events: list[dict[str, object]] = []
    skipped = 0
    for n, day in enumerate(signal_dates, start=1):
        if n == 1 or n % 10 == 0 or n == len(signal_dates):
            print(f"  {n}/{len(signal_dates)} {day}", flush=True)
        day_i = date_index[day]
        window = calendar[day_i - WINDOW_DAYS + 1 : day_i + 1]
        board_rows = _rim_for_heat(
            window_dates=window,
            heat_by_day=heat_by_day,
            names=names,
            close_heat=_clip_close_heat(board_close_heat, day),
            top_n=BOARD_TOP,
        )
        if len(board_rows) < 1:
            skipped += 1
            continue
        board_codes = [str(row["board_code"]) for row in board_rows]
        members = fetch_board_constituents_many(
            "industry", board_codes, as_of=day
        )
        union: list[str] = []
        seen: set[str] = set()
        for code in board_codes:
            for stock in sorted(members.get(code) or []):
                if stock in seen:
                    continue
                seen.add(stock)
                union.append(stock)
        union = union[:STOCK_BASKET_MAX]
        if not union:
            skipped += 1
            continue
        _ensure_stock_bars(
            union,
            start=calendar[max(0, first_signal_i - WINDOW_DAYS - STOCK_PAD - CROSS_HISTORY_DAYS)],
            end=calendar[-1],
            bar_cache=stock_bar_cache,
            close_cache=stock_close,
            name_cache=stock_names,
        )
        stock_rows = _rim_for_stocks(
            window_dates=window,
            as_of=day,
            codes=union,
            names=stock_names,
            bar_cache=stock_bar_cache,
            top_n=STOCK_TOP,
        )
        if not stock_rows:
            skipped += 1
            continue
        board_label = ",".join(
            f"{row['board_name']}({row['score']})" for row in board_rows
        )
        for rank, row in enumerate(stock_rows, start=1):
            code = str(row["board_code"])
            for horizon in HORIZONS:
                exit_i = day_i + horizon
                if exit_i >= len(calendar):
                    continue
                exit_day = calendar[exit_i]
                stock_ret = _pct_return(
                    stock_close.get(code, {}).get(day),
                    stock_close.get(code, {}).get(exit_day),
                )
                index_ret = _pct_return(
                    index_closes.get(day), index_closes.get(exit_day)
                )
                if stock_ret is None or index_ret is None:
                    continue
                events.append(
                    {
                        "signal_date": day.isoformat(),
                        "horizon": horizon,
                        "stock_code": code,
                        "stock_name": row["board_name"],
                        "stock_rank": rank,
                        "stock_score": row["score"],
                        "macd_up": int(bool(row["macd_up"])),
                        "boards": board_label,
                        "stock_ret": stock_ret,
                        "index_ret": index_ret,
                        "excess": stock_ret - index_ret,
                    }
                )

    stamp = as_of.isoformat()
    summary = _summarize(events)
    notes = [
        f"as_of={stamp}",
        f"signal_days={len(signal_dates)} {signal_dates[0]} → {signal_dates[-1]}",
        f"window={WINDOW_DAYS} industry_top={BOARD_TOP} stock_top={STOCK_TOP}",
        f"skipped_days={skipped}",
        "cascade: industry rim top3 → union constituents → stock rim top3",
        "entry=T close; excess = stock_close_return − csi500 (pct points)",
        "win_rate = P(excess>0); hit_rate = P(stock_ret>0)",
        "",
        * _format_summary(summary),
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = OUT_DIR / f"rim_cascade_100d_{stamp}.txt"
    csv_path = OUT_DIR / f"rim_cascade_100d_events_{stamp}.csv"
    txt_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    _write_events(csv_path, events)
    print("\n".join(notes))
    print(f"wrote {txt_path}")
    print(f"wrote {csv_path}")


def _rim_for_heat(
    *,
    window_dates: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
    close_heat: dict[str, list[tuple[date, object, object, object]]],
    top_n: int,
) -> list[dict]:
    codes = sorted(
        {
            code
            for day in window_dates
            for code in (heat_by_day.get(day) or {})
        }
    )
    if not codes:
        return []
    series = hotness_series_by_code(
        window_dates=window_dates, codes=codes, heat_by_day=heat_by_day
    )
    ordered = order_by_trajectory_seriation(codes, series)
    labels = [names.get(code, code) for code in ordered]
    z = hotness_grid(
        window_dates=window_dates, ordered_codes=ordered, heat_by_day=heat_by_day
    )
    overlay = build_cross_mark_overlay(
        ordered_codes=ordered,
        window_dates=window_dates,
        close_heat_by_code=close_heat,
        names=names,
    )
    ranked = rank_heat_rim_spread(
        dates=window_dates,
        codes=ordered,
        names=labels,
        z=z,
        macd_up_by_code=macd_up_by_code_from_overlay(
            codes=ordered, dates=window_dates, overlay=overlay
        ),
        top_n=top_n,
    )
    return list(ranked.get("rows") or [])


def _clip_close_heat(
    close_heat: dict[str, list[tuple[date, object, object, object]]],
    end: date,
) -> dict[str, list[tuple[date, object, object, object]]]:
    return {
        code: [row for row in rows if row[0] <= end]
        for code, rows in close_heat.items()
    }


def _rim_for_stocks(
    *,
    window_dates: list[date],
    as_of: date,
    codes: list[str],
    names: dict[str, str],
    bar_cache: dict[str, list[dict[str, object]]],
    top_n: int,
) -> list[dict]:
    bars: list[dict[str, object]] = []
    for code in codes:
        for bar in bar_cache.get(code) or []:
            day = bar.get("trade_date")
            if isinstance(day, date) and day <= as_of:
                bars.append(bar)
    if not bars:
        return []
    returns = bars_to_returns(bars)
    heat = compute_heat(returns, board_type="stock")
    heat_tuples = heat_rows_to_tuples(heat, names)
    heat_by_day: dict[date, dict[str, float]] = {}
    for trade_date, board_code, _name, heat_short, _long in heat_tuples:
        val = as_float(heat_short)
        if val is None:
            continue
        heat_by_day.setdefault(trade_date, {})[str(board_code)] = val
    present = sorted(
        {
            code
            for day in window_dates
            for code in (heat_by_day.get(day) or {})
            if code in set(codes)
        }
    )
    if not present:
        return []
    series = hotness_series_by_code(
        window_dates=window_dates, codes=present, heat_by_day=heat_by_day
    )
    ordered = order_by_trajectory_seriation(present, series)
    labels = [names.get(code, code) for code in ordered]
    z = hotness_grid(
        window_dates=window_dates, ordered_codes=ordered, heat_by_day=heat_by_day
    )
    grouped = group_bars_by_code(bars)
    close_heat = close_heat_from_bars_and_heat(grouped, heat)
    overlay = build_cross_mark_overlay(
        ordered_codes=ordered,
        window_dates=window_dates,
        close_heat_by_code=close_heat,
        names=names,
    )
    ranked = rank_heat_rim_spread(
        dates=window_dates,
        codes=ordered,
        names=labels,
        z=z,
        macd_up_by_code=macd_up_by_code_from_overlay(
            codes=ordered, dates=window_dates, overlay=overlay
        ),
        top_n=top_n,
    )
    return list(ranked.get("rows") or [])


def _ensure_stock_bars(
    codes: list[str],
    *,
    start: date,
    end: date,
    bar_cache: dict[str, list[dict[str, object]]],
    close_cache: dict[str, dict[date, float]],
    name_cache: dict[str, str],
) -> None:
    missing = [code for code in codes if code not in bar_cache]
    if missing:
        fetched = fetch_stock_bars_for_codes(missing, start, end)
        grouped = group_bars_by_code(fetched)
        for code in missing:
            rows = grouped.get(code) or []
            bar_cache[code] = rows
            closes: dict[date, float] = {}
            for bar in rows:
                day = bar.get("trade_date")
                val = as_float(bar.get("close"))
                if isinstance(day, date) and val is not None:
                    closes[day] = val
            close_cache[code] = closes
        for code, name in fetch_stock_code_names(missing).items():
            name_cache.setdefault(code, name)
        for code in missing:
            name_cache.setdefault(code, code)


def _pct_return(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return (end / start - 1.0) * 100.0


def _summarize(events: list[dict[str, object]]) -> list[dict[str, object]]:
    buckets: dict[tuple[int, str], list[float]] = defaultdict(list)
    hits: dict[tuple[int, str], list[bool]] = defaultdict(list)
    abs_hits: dict[tuple[int, str], list[bool]] = defaultdict(list)
    for event in events:
        horizon = int(event["horizon"])
        excess = float(event["excess"])
        stock_ret = float(event["stock_ret"])
        for key in ("all", f"rank{event['stock_rank']}"):
            buckets[(horizon, key)].append(excess)
            hits[(horizon, key)].append(excess > 0)
            abs_hits[(horizon, key)].append(stock_ret > 0)
    rows = []
    for (horizon, key), excesses in sorted(buckets.items()):
        n = len(excesses)
        rows.append(
            {
                "horizon": horizon,
                "bucket": key,
                "n": n,
                "win_rate": sum(hits[(horizon, key)]) / n if n else None,
                "hit_rate": sum(abs_hits[(horizon, key)]) / n if n else None,
                "mean_excess": mean(excesses) if n else None,
            }
        )
    return rows


def _format_summary(rows: list[dict[str, object]]) -> list[str]:
    lines = [
        f"{'h':>4} {'bucket':<8} {'n':>5} {'win%':>7} {'hit%':>7} {'expp':>8}",
        "-" * 44,
    ]
    for row in rows:
        win = row["win_rate"]
        hit = row["hit_rate"]
        ex = row["mean_excess"]
        lines.append(
            f"{row['horizon']:>4} {row['bucket']:<8} {row['n']:>5} "
            f"{100 * win:6.1f}% {100 * hit:6.1f}% {ex:8.2f}"
            if win is not None and hit is not None and ex is not None
            else f"{row['horizon']:>4} {row['bucket']:<8} {row['n']:>5}"
        )
    return lines


def _write_events(path: Path, events: list[dict[str, object]]) -> None:
    if not events:
        path.write_text("", encoding="utf-8")
        return
    fields = list(events[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(events)


if __name__ == "__main__":
    main()
