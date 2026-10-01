#!/usr/bin/env python3
"""Step-2: causal daily heat-surface structure flags (hard events).

For each as_of day, rebuild the theme-wave short-heat plane on trailing
WINDOW_DAYS and emit per-board binary flags:

  near_warming    near-end hotness OLS slope > eps (getting hotter)
  near_cooling    near-end hotness OLS slope < -eps
  crowded_top     as-of hotness ≥ 0.90 (top decile of that roster)
  in_hot_cluster  late-hot self + ≥50% of ±2 leaf-order neighbors late-hot

Writes under experiments/out/. Does not change web pages beyond attaching
`surface_flags` onto heat-plane payloads.

Usage (from repo root):
  .venv/bin/python scripts/surface_flags_baseline.py
  .venv/bin/python scripts/surface_flags_baseline.py --board-type industry
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import (  # noqa: E402
    fetch_board_type_heat_window,
    fetch_heat_dates_ending,
)
from app.themes.concept_wave import build_concept_top_heat_payload  # noqa: E402
from app.themes.heat_surface_flags import SURFACE_FLAG_KEYS  # noqa: E402
from app.themes.industry_wave import build_industry_board_heat_payload  # noqa: E402

OUT_DIR = ROOT / "experiments" / "out"
WINDOW_DAYS = 60
DEFAULT_STEP_DAYS = 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--board-type",
        choices=("industry", "concept", "both"),
        default="both",
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--step-days", type=int, default=DEFAULT_STEP_DAYS)
    parser.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    args = parser.parse_args()
    if args.step_days < 1:
        raise SystemExit("--step-days must be >= 1")

    types = (
        ["industry", "concept"] if args.board_type == "both" else [args.board_type]
    )
    as_of = args.as_of or _latest_heat_day(types[0])
    if as_of is None:
        raise RuntimeError("no heat dates found")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, object]] = []
    notes: list[str] = [
        f"as_of={as_of.isoformat()}",
        f"window_days={args.window_days}",
        f"step_days={args.step_days}",
        f"flags={list(SURFACE_FLAG_KEYS)}",
        "causal: each trade_date uses only heat on/before that day",
        "",
    ]

    for board_type in types:
        rows, note = _build_panel(
            board_type=board_type,
            as_of=as_of,
            window_days=args.window_days,
            step_days=args.step_days,
        )
        all_rows.extend(rows)
        notes.append(note)
        notes.append(_flag_rate_line(board_type, rows))
        notes.append("")

    stamp = as_of.isoformat()
    flags_path = OUT_DIR / f"surface_structure_flags_{stamp}.csv"
    txt_path = OUT_DIR / f"surface_structure_flags_{stamp}.txt"
    _write_flags_csv(flags_path, all_rows)
    notes.extend(_join_with_cross_events(stamp, all_rows))
    txt_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    print(txt_path.read_text(encoding="utf-8"))
    print(f"wrote {txt_path}")
    print(f"wrote {flags_path}")


def _build_panel(
    *,
    board_type: str,
    as_of: date,
    window_days: int,
    step_days: int,
) -> tuple[list[dict[str, object]], str]:
    history = fetch_heat_dates_ending(board_type, as_of, 500)
    if len(history) < window_days:
        return [], f"{board_type}: need >={window_days} heat days, got {len(history)}"

    eval_dates = list(history[window_days - 1 :: step_days])
    if eval_dates[-1] != history[-1]:
        eval_dates.append(history[-1])
        seen: set[date] = set()
        ordered: list[date] = []
        for day in eval_dates:
            if day in seen:
                continue
            seen.add(day)
            ordered.append(day)
        eval_dates = ordered

    heat_start, heat_end = history[0], history[-1]
    heat_rows = fetch_board_type_heat_window(board_type, heat_start, heat_end)
    by_day: dict[date, list] = defaultdict(list)
    for row in heat_rows:
        by_day[row[0]].append(row)

    out: list[dict[str, object]] = []
    empty_days = 0
    for day in eval_dates:
        end_i = history.index(day)
        start_i = end_i - window_days + 1
        window = history[start_i : end_i + 1]
        sliced = [row for d in window for row in by_day.get(d, [])]
        if board_type == "industry":
            payload = build_industry_board_heat_payload(
                window_dates=window, heat_rows=sliced
            )
        else:
            payload = build_concept_top_heat_payload(
                window_dates=window, heat_rows=sliced
            )
        flags = payload.get("surface_flags") or []
        if payload.get("empty_message") or not flags:
            empty_days += 1
            continue
        for item in flags:
            out.append(
                {
                    "board_type": board_type,
                    "trade_date": day.isoformat(),
                    "board_code": item["board_code"],
                    "board_name": item["board_name"],
                    **{key: int(bool(item[key])) for key in SURFACE_FLAG_KEYS},
                    "hotness_asof": item.get("hotness_asof"),
                    "hotness_late": item.get("hotness_late"),
                    "near_slope": item.get("near_slope"),
                }
            )

    note = (
        f"{board_type}: heat {heat_start} → {heat_end} ({len(history)} days), "
        f"eval_days={len(eval_dates)}, empty_days={empty_days}, "
        f"flag_rows={len(out)}, "
        f"boards_last="
        f"{len({r['board_code'] for r in out if r['trade_date'] == history[-1].isoformat()})}"
    )
    return out, note


def _flag_rate_line(board_type: str, rows: list[dict[str, object]]) -> str:
    if not rows:
        return f"{board_type} flag rates: (none)"
    n = len(rows)
    parts = [
        f"{key}={sum(int(row[key]) for row in rows) / n:.1%}"
        for key in SURFACE_FLAG_KEYS
    ]
    return f"{board_type} flag rates: " + ", ".join(parts)


def _join_with_cross_events(
    stamp: str, flag_rows: list[dict[str, object]]
) -> list[str]:
    events_path = OUT_DIR / f"cross_signal_baseline_events_{stamp}.csv"
    lines = ["## join smoke vs cross events (same as_of stamp)", f"events={events_path}"]
    if not events_path.exists():
        lines.append("events file missing — skip join")
        return lines
    if not flag_rows:
        lines.append("no flag rows — skip join")
        return lines

    flag_index = {
        (str(row["board_type"]), str(row["board_code"]), str(row["trade_date"])): row
        for row in flag_rows
    }
    with events_path.open(encoding="utf-8") as fh:
        events = list(csv.DictReader(fh))

    matched = 0
    total = 0
    by_signal: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        if int(event["horizon"]) != 3:
            continue
        total += 1
        key = (event["board_type"], event["board_code"], event["signal_date"])
        flags = flag_index.get(key)
        if flags is None:
            continue
        matched += 1
        signal = event["signal"]
        by_signal[signal]["n"] += 1
        for flag in SURFACE_FLAG_KEYS:
            if int(flags[flag]):
                by_signal[signal][flag] += 1

    if total:
        lines.append(f"horizon=3 events={total}, joined={matched} ({matched / total:.1%})")
    else:
        lines.append("no events")
    lines.append("flag hit-rate among joined events (not yet a filtered backtest):")
    for signal in sorted(by_signal):
        counter = by_signal[signal]
        n = counter["n"]
        bits = [f"n={n}"] + [
            f"{flag}={counter[flag] / n:.1%}" if n else f"{flag}=-"
            for flag in SURFACE_FLAG_KEYS
        ]
        lines.append(f"  {signal}: " + ", ".join(bits))
    return lines


def _write_flags_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "board_type",
        "trade_date",
        "board_code",
        "board_name",
        *SURFACE_FLAG_KEYS,
        "hotness_asof",
        "hotness_late",
        "near_slope",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _latest_heat_day(board_type: str) -> date | None:
    days = fetch_heat_dates_ending(board_type, date.today(), 1)
    return days[-1] if days else None


if __name__ == "__main__":
    main()
