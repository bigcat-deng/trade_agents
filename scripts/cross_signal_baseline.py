#!/usr/bin/env python3
"""Step-0 baseline: naked MACD / heat-cross predictive power.

Same cross rules as the rotation table (app.interpret.cross_stats).
Forward return from signal close to close T+h; excess = board − 中证500.

Does not touch the web app. Writes under experiments/out/.

Usage (from repo root):
  .venv/bin/python scripts/cross_signal_baseline.py
  .venv/bin/python scripts/cross_signal_baseline.py --board-type industry
  .venv/bin/python scripts/cross_signal_baseline.py --board-type both
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg

from app.db import database_url, fetch_board_close_heat, fetch_trading_dates_ending
from app.interpret.cross_stats import list_cross_event_dates
from app.market_data.csi500 import fetch_csi500_closes

OUT_DIR = ROOT / "experiments" / "out"

# MACD(12,26,9) needs warm-up; keep signals after this many bars.
WARMUP_BARS = 40
HORIZONS = (3, 5, 10)
SIGNALS = ("macd_up", "macd_down", "heat_up", "heat_down")
UP_SIGNALS = frozenset({"macd_up", "heat_up"})


@dataclass(frozen=True)
class EventOutcome:
    board_type: str
    board_code: str
    signal: str
    signal_date: date
    horizon: int
    board_ret: float
    index_ret: float
    excess: float


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--board-type",
        choices=("industry", "concept", "both"),
        default="both",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="End date YYYY-MM-DD (default: latest industry bar day)",
    )
    args = parser.parse_args()
    types = (
        ["industry", "concept"] if args.board_type == "both" else [args.board_type]
    )
    as_of = args.as_of or _latest_bar_day("industry")
    if as_of is None:
        raise RuntimeError("no board_daily_bar dates found")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_outcomes: list[EventOutcome] = []
    meta_lines: list[str] = [
        f"as_of={as_of.isoformat()}",
        f"horizons={list(HORIZONS)}",
        f"warmup_bars={WARMUP_BARS}",
        "excess = board_close_return − csi500_close_return (pct points)",
        "win_rate: up signals → P(excess>0); down signals → P(excess<0)",
        "",
    ]

    for board_type in types:
        outcomes, note = _run_board_type(board_type, as_of)
        all_outcomes.extend(outcomes)
        meta_lines.append(note)
        meta_lines.append("")

    summary_rows = _summarize(all_outcomes)
    stamp = as_of.isoformat()
    txt_path = OUT_DIR / f"cross_signal_baseline_{stamp}.txt"
    csv_path = OUT_DIR / f"cross_signal_baseline_{stamp}.csv"
    events_path = OUT_DIR / f"cross_signal_baseline_events_{stamp}.csv"

    txt_path.write_text(
        "\n".join(meta_lines + _format_summary_table(summary_rows)) + "\n",
        encoding="utf-8",
    )
    _write_summary_csv(csv_path, summary_rows)
    _write_events_csv(events_path, all_outcomes)
    print(txt_path.read_text(encoding="utf-8"))
    print(f"wrote {txt_path}")
    print(f"wrote {csv_path}")
    print(f"wrote {events_path}")


def _run_board_type(board_type: str, as_of: date) -> tuple[list[EventOutcome], str]:
    dates = fetch_trading_dates_ending(board_type, as_of, 500)
    if len(dates) < WARMUP_BARS + max(HORIZONS) + 5:
        return [], f"{board_type}: insufficient trading days ({len(dates)})"
    start, end = dates[0], dates[-1]
    codes = _board_codes_with_heat(board_type, start, end)
    if not codes:
        return [], f"{board_type}: no boards with bars+heat in window"

    series = fetch_board_close_heat(board_type, codes, start, end)
    index_closes = dict(fetch_csi500_closes(start, end))
    if len(index_closes) < len(dates) // 2:
        return [], (
            f"{board_type}: csi500 closes too sparse "
            f"({len(index_closes)} vs {len(dates)} board days)"
        )

    date_index = {day: i for i, day in enumerate(dates)}
    eval_start_i = WARMUP_BARS
    max_h = max(HORIZONS)
    outcomes: list[EventOutcome] = []
    signal_counts = {key: 0 for key in SIGNALS}

    for code in codes:
        rows = series.get(code) or []
        if len(rows) < WARMUP_BARS + max_h + 1:
            continue
        close_by_day = {}
        for day, close, _hs, _hl in rows:
            value = _as_float(close)
            if value is not None:
                close_by_day[day] = value
        events = list_cross_event_dates(rows)
        for signal in SIGNALS:
            for signal_day in events[signal]:
                i = date_index.get(signal_day)
                if i is None or i < eval_start_i:
                    continue
                signal_counts[signal] += 1
                for horizon in HORIZONS:
                    j = i + horizon
                    if j >= len(dates):
                        continue
                    exit_day = dates[j]
                    board_ret = _pct_return(
                        close_by_day.get(signal_day), close_by_day.get(exit_day)
                    )
                    index_ret = _pct_return(
                        index_closes.get(signal_day), index_closes.get(exit_day)
                    )
                    if board_ret is None or index_ret is None:
                        continue
                    outcomes.append(
                        EventOutcome(
                            board_type=board_type,
                            board_code=code,
                            signal=signal,
                            signal_date=signal_day,
                            horizon=horizon,
                            board_ret=board_ret,
                            index_ret=index_ret,
                            excess=board_ret - index_ret,
                        )
                    )

    note = (
        f"{board_type}: bars {start} → {end} ({len(dates)} days), "
        f"boards={len(codes)}, eval_from={dates[eval_start_i]}, "
        f"csi500_points={len(index_closes)}, "
        f"raw_signals={signal_counts}, outcomes={len(outcomes)}"
    )
    return outcomes, note


def _summarize(outcomes: list[EventOutcome]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, int], list[EventOutcome]] = defaultdict(list)
    for row in outcomes:
        buckets[(row.board_type, row.signal, row.horizon)].append(row)

    summary: list[dict[str, object]] = []
    for board_type, signal, horizon in sorted(buckets):
        group = buckets[(board_type, signal, horizon)]
        excesses = [item.excess for item in group]
        boards = [item.board_ret for item in group]
        indexes = [item.index_ret for item in group]
        if signal in UP_SIGNALS:
            hits = sum(1 for value in excesses if value > 0)
        else:
            hits = sum(1 for value in excesses if value < 0)
        n = len(group)
        summary.append(
            {
                "board_type": board_type,
                "signal": signal,
                "horizon": horizon,
                "n": n,
                "win_rate": hits / n if n else None,
                "mean_excess": mean(excesses) if excesses else None,
                "median_excess": median(excesses) if excesses else None,
                "mean_board": mean(boards) if boards else None,
                "mean_index": mean(indexes) if indexes else None,
            }
        )
    return summary


def _format_summary_table(rows: list[dict[str, object]]) -> list[str]:
    header = (
        f"{'type':<10} {'signal':<10} {'h':>2} {'n':>5} "
        f"{'win%':>7} {'mean_xs':>9} {'med_xs':>9} "
        f"{'mean_bd':>9} {'mean_idx':>9}"
    )
    lines = ["## summary", header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row['board_type']:<10} {row['signal']:<10} {row['horizon']:>2} "
            f"{row['n']:>5} "
            f"{_fmt_pct(row['win_rate'], as_ratio=True):>7} "
            f"{_fmt_num(row['mean_excess']):>9} "
            f"{_fmt_num(row['median_excess']):>9} "
            f"{_fmt_num(row['mean_board']):>9} "
            f"{_fmt_num(row['mean_index']):>9}"
        )
    if not rows:
        lines.append("(no outcomes)")
    return lines


def _write_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "board_type",
        "signal",
        "horizon",
        "n",
        "win_rate",
        "mean_excess",
        "median_excess",
        "mean_board",
        "mean_index",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_events_csv(path: Path, outcomes: list[EventOutcome]) -> None:
    fields = [
        "board_type",
        "board_code",
        "signal",
        "signal_date",
        "horizon",
        "board_ret",
        "index_ret",
        "excess",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in outcomes:
            writer.writerow(
                {
                    "board_type": row.board_type,
                    "board_code": row.board_code,
                    "signal": row.signal,
                    "signal_date": row.signal_date.isoformat(),
                    "horizon": row.horizon,
                    "board_ret": row.board_ret,
                    "index_ret": row.index_ret,
                    "excess": row.excess,
                }
            )


def _board_codes_with_heat(
    board_type: str, start: date, end: date
) -> list[str]:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT b.board_code
                FROM board_daily_bar AS b
                INNER JOIN board_heat_daily AS h
                  ON h.board_type = b.board_type
                 AND h.board_code = b.board_code
                 AND h.trade_date = b.trade_date
                WHERE b.board_type = %s
                  AND b.trade_date >= %s
                  AND b.trade_date <= %s
                ORDER BY b.board_code
                """,
                (board_type, start, end),
            )
            return [row[0] for row in cur.fetchall()]


def _latest_bar_day(board_type: str) -> date | None:
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(trade_date)
                FROM board_daily_bar
                WHERE board_type = %s
                """,
                (board_type,),
            )
            row = cur.fetchone()
    return row[0] if row else None


def _pct_return(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return (end / start - 1.0) * 100.0


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _fmt_num(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: object, *, as_ratio: bool = False) -> str:
    if value is None:
        return "-"
    number = float(value) * 100.0 if as_ratio else float(value)
    return f"{number:.1f}"


if __name__ == "__main__":
    main()
