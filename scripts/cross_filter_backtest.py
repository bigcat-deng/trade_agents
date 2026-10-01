#!/usr/bin/env python3
"""Step-3/5: joint backtest — naked cross vs wavelet/surface/range filters.

Joins step-0 event outcomes with step-1/2 causal flag panels, then compares:

  bare_all            all events (step-0 style; may lack flags)
  bare_joined         events that successfully join both flag panels (fair baseline)
  wavelet_pass        bare_joined ∩ wavelet filter
  surface_pass        bare_joined ∩ surface filter
  surface_range_pass  surface_pass ∩ not range-high (UP only; DOWN same as surface)
  both_pass           bare_joined ∩ wavelet ∩ surface

Filter rules (primary preset):

  UP  (macd_up / heat_up):
    wavelet: (a3_still_hot OR d3_warming) AND NOT d1_pulse
    surface: near_warming AND NOT crowded_top
    range:   NOT (top>=5 or top>mid and top>bottom) on 100d-range / 10d counts

  DOWN (macd_down / heat_down):
    wavelet: (a3_fading OR d3_cooling) AND NOT d1_pulse
    surface: near_cooling

win_rate: up → P(excess>0); down → P(excess<0)

Usage (from repo root):
  .venv/bin/python scripts/cross_filter_backtest.py
  .venv/bin/python scripts/cross_filter_backtest.py --as-of 2026-09-24
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import fetch_board_daily_bars_many, fetch_trading_dates_ending  # noqa: E402
from app.interpret.cross_stats import (  # noqa: E402
    _KLINE_RANGE_DAYS,
    _RANGE_BOTTOM,
    _RANGE_COUNT_DAYS,
    _RANGE_TOP,
    _number,
    _range_high_biased,
)

OUT_DIR = ROOT / "experiments" / "out"
UP_SIGNALS = frozenset({"macd_up", "heat_up"})
DOWN_SIGNALS = frozenset({"macd_down", "heat_down"})
BUCKETS = (
    "bare_all",
    "bare_joined",
    "wavelet_pass",
    "surface_pass",
    "surface_range_pass",
    "both_pass",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="Stamp matching step-0/1/2 outputs (default: newest events file)",
    )
    args = parser.parse_args()
    stamp = (args.as_of or _latest_stamp()).isoformat()

    events_path = OUT_DIR / f"cross_signal_baseline_events_{stamp}.csv"
    wavelet_path = OUT_DIR / f"wavelet_structure_flags_{stamp}.csv"
    surface_path = OUT_DIR / f"surface_structure_flags_{stamp}.csv"
    for path in (events_path, wavelet_path, surface_path):
        if not path.exists():
            raise SystemExit(f"missing required file: {path}")

    events = _read_csv(events_path)
    wavelet = _index_flags(_read_csv(wavelet_path))
    surface = _index_flags(_read_csv(surface_path))
    range_high = _range_high_by_event(events)

    enriched: list[dict[str, object]] = []
    for event in events:
        key = (event["board_type"], event["board_code"], event["signal_date"])
        w = wavelet.get(key)
        s = surface.get(key)
        signal = event["signal"]
        joined = w is not None and s is not None
        w_pass = joined and _wavelet_pass(signal, w)
        s_pass = joined and _surface_pass(signal, s)
        high = bool(range_high.get(key, False))
        if signal in UP_SIGNALS:
            sr_pass = s_pass and not high
        else:
            sr_pass = s_pass
        row = {
            **event,
            "joined": int(joined),
            "wavelet_pass": int(w_pass),
            "surface_pass": int(s_pass),
            "range_high": int(high),
            "surface_range_pass": int(sr_pass),
            "both_pass": int(w_pass and s_pass),
            "excess": float(event["excess"]),
            "board_ret": float(event["board_ret"]),
            "index_ret": float(event["index_ret"]),
            "horizon": int(event["horizon"]),
        }
        enriched.append(row)

    summary = _summarize(enriched)
    notes = [
        f"as_of={stamp}",
        f"events={events_path.name}",
        f"wavelet={wavelet_path.name}",
        f"surface={surface_path.name}",
        "",
        "filters:",
        "  UP:   wavelet=(a3_still_hot|d3_warming)&~d1_pulse; surface=near_warming&~crowded_top; range=~high",
        "  DOWN: wavelet=(a3_fading|d3_cooling)&~d1_pulse; surface=near_cooling",
        "win_rate: up→P(excess>0); down→P(excess<0)",
        "fair compare: use bare_joined vs *_pass (same joinable universe)",
        "product trusted signal ≈ surface_range_pass on macd_up",
        "",
    ]
    notes.extend(_format_summary(summary))
    notes.append("")
    notes.extend(_format_lift(summary))

    txt_path = OUT_DIR / f"cross_filter_backtest_{stamp}.txt"
    csv_path = OUT_DIR / f"cross_filter_backtest_{stamp}.csv"
    events_out = OUT_DIR / f"cross_filter_backtest_events_{stamp}.csv"
    txt_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    _write_summary_csv(csv_path, summary)
    _write_events_csv(events_out, enriched)

    print(txt_path.read_text(encoding="utf-8"))
    print(f"wrote {txt_path}")
    print(f"wrote {csv_path}")
    print(f"wrote {events_out}")


def _range_high_by_event(
    events: list[dict[str, str]],
) -> dict[tuple[str, str, str], bool]:
    """Map (board_type, code, signal_date) → range_high using 100d/10d buckets."""
    need: dict[str, set[tuple[str, date]]] = defaultdict(set)
    for event in events:
        day = date.fromisoformat(event["signal_date"])
        need[event["board_type"]].add((event["board_code"], day))

    out: dict[tuple[str, str, str], bool] = {}
    for board_type, pairs in need.items():
        codes = sorted({code for code, _day in pairs})
        days_needed = {day for _code, day in pairs}
        if not codes or not days_needed:
            continue
        end = max(days_needed)
        calendar = fetch_trading_dates_ending(board_type, end, 500)
        if len(calendar) < _KLINE_RANGE_DAYS:
            continue
        date_index = {day: i for i, day in enumerate(calendar)}
        bars = fetch_board_daily_bars_many(
            board_type, codes, calendar[0], calendar[-1]
        )
        for code, day in pairs:
            i = date_index.get(day)
            if i is None or i + 1 < _KLINE_RANGE_DAYS:
                out[(board_type, code, day.isoformat())] = False
                continue
            window = calendar[i - _KLINE_RANGE_DAYS + 1 : i + 1]
            recent = set(window[-_RANGE_COUNT_DAYS:])
            window_set = set(window)
            code_bars = [
                bar
                for bar in bars.get(code) or []
                if bar.get("trade_date") in window_set
            ]
            counts = _range_counts(code_bars, recent)
            out[(board_type, code, day.isoformat())] = _range_high_biased(counts)
    return out


def _range_counts(
    bars: list[dict[str, object]], recent: set[date]
) -> dict[str, int]:
    highs = [_number(bar.get("high")) for bar in bars]
    lows = [_number(bar.get("low")) for bar in bars]
    valid_highs = [v for v in highs if v is not None]
    valid_lows = [v for v in lows if v is not None]
    if not valid_highs or not valid_lows:
        return {"top": 0, "mid": 0, "bottom": 0}
    range_high = max(valid_highs)
    range_low = min(valid_lows)
    span = range_high - range_low
    if span <= 0:
        return {"top": 0, "mid": 0, "bottom": 0}
    top = mid = bottom = 0
    for bar in bars:
        if bar.get("trade_date") not in recent:
            continue
        close = _number(bar.get("close"))
        if close is None:
            continue
        pos = (close - range_low) / span
        if pos >= _RANGE_TOP:
            top += 1
        elif pos <= _RANGE_BOTTOM:
            bottom += 1
        else:
            mid += 1
    return {"top": top, "mid": mid, "bottom": bottom}


def _wavelet_pass(signal: str, flags: dict[str, str]) -> bool:
    pulse = _flag(flags, "d1_pulse")
    if signal in UP_SIGNALS:
        return (_flag(flags, "a3_still_hot") or _flag(flags, "d3_warming")) and not pulse
    if signal in DOWN_SIGNALS:
        return (_flag(flags, "a3_fading") or _flag(flags, "d3_cooling")) and not pulse
    return False


def _surface_pass(signal: str, flags: dict[str, str]) -> bool:
    if signal in UP_SIGNALS:
        return _flag(flags, "near_warming") and not _flag(flags, "crowded_top")
    if signal in DOWN_SIGNALS:
        return _flag(flags, "near_cooling")
    return False


def _flag(row: dict[str, str], key: str) -> bool:
    return str(row.get(key, "0")).strip() in {"1", "true", "True"}


def _summarize(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str, int, str], list[float]] = defaultdict(list)
    board_buckets: dict[tuple[str, str, int, str], list[float]] = defaultdict(list)

    for row in rows:
        signal = str(row["signal"])
        board_type = str(row["board_type"])
        horizon = int(row["horizon"])
        excess = float(row["excess"])
        board_ret = float(row["board_ret"])
        candidates = {
            "bare_all": True,
            "bare_joined": bool(row["joined"]),
            "wavelet_pass": bool(row["wavelet_pass"]),
            "surface_pass": bool(row["surface_pass"]),
            "surface_range_pass": bool(row["surface_range_pass"]),
            "both_pass": bool(row["both_pass"]),
        }
        for bucket, keep in candidates.items():
            if not keep:
                continue
            key = (board_type, signal, horizon, bucket)
            buckets[key].append(excess)
            board_buckets[key].append(board_ret)

    summary: list[dict[str, object]] = []
    for key in sorted(buckets):
        board_type, signal, horizon, bucket = key
        excesses = buckets[key]
        boards = board_buckets[key]
        n = len(excesses)
        if signal in UP_SIGNALS:
            hits = sum(1 for value in excesses if value > 0)
        else:
            hits = sum(1 for value in excesses if value < 0)
        summary.append(
            {
                "board_type": board_type,
                "signal": signal,
                "horizon": horizon,
                "bucket": bucket,
                "n": n,
                "win_rate": hits / n if n else None,
                "mean_excess": mean(excesses) if excesses else None,
                "median_excess": median(excesses) if excesses else None,
                "mean_board": mean(boards) if boards else None,
            }
        )
    return summary


def _format_summary(rows: list[dict[str, object]]) -> list[str]:
    header = (
        f"{'type':<10} {'signal':<10} {'h':>2} {'bucket':<13} "
        f"{'n':>5} {'win%':>7} {'mean_xs':>9} {'med_xs':>9} {'mean_bd':>9}"
    )
    lines = ["## summary", header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row['board_type']:<10} {row['signal']:<10} {row['horizon']:>2} "
            f"{row['bucket']:<13} {row['n']:>5} "
            f"{_fmt_pct(row['win_rate']):>7} "
            f"{_fmt_num(row['mean_excess']):>9} "
            f"{_fmt_num(row['median_excess']):>9} "
            f"{_fmt_num(row['mean_board']):>9}"
        )
    return lines


def _format_lift(rows: list[dict[str, object]]) -> list[str]:
    """Delta of each pass bucket vs bare_joined on same type/signal/horizon."""
    by_key: dict[tuple[str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        key = (str(row["board_type"]), str(row["signal"]), int(row["horizon"]))
        by_key[key][str(row["bucket"])] = row

    header = (
        f"{'type':<10} {'signal':<10} {'h':>2} {'bucket':<13} "
        f"{'n':>5} {'d_win':>7} {'d_mean':>9} {'base_n':>6}"
    )
    lines = ["## lift vs bare_joined", header, "-" * len(header)]
    for key in sorted(by_key):
        group = by_key[key]
        base = group.get("bare_joined")
        if not base or not base["n"]:
            continue
        base_win = float(base["win_rate"] or 0)
        base_mean = float(base["mean_excess"] or 0)
        for bucket in ("wavelet_pass", "surface_pass", "surface_range_pass", "both_pass"):
            row = group.get(bucket)
            if not row:
                continue
            win = float(row["win_rate"] or 0)
            mean_xs = float(row["mean_excess"] or 0)
            lines.append(
                f"{key[0]:<10} {key[1]:<10} {key[2]:>2} {bucket:<13} "
                f"{row['n']:>5} "
                f"{(win - base_win) * 100:>+6.1f} "
                f"{mean_xs - base_mean:>+8.2f} "
                f"{base['n']:>6}"
            )
    return lines


def _index_flags(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[str, str]]:
    out: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["board_type"], row["board_code"], row["trade_date"])
        out[key] = row
    return out


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "board_type",
        "signal",
        "horizon",
        "bucket",
        "n",
        "win_rate",
        "mean_excess",
        "median_excess",
        "mean_board",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_events_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "board_type",
        "board_code",
        "signal",
        "signal_date",
        "horizon",
        "board_ret",
        "index_ret",
        "excess",
        "joined",
        "wavelet_pass",
        "surface_pass",
        "range_high",
        "surface_range_pass",
        "both_pass",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _latest_stamp() -> date:
    files = sorted(OUT_DIR.glob("cross_signal_baseline_events_*.csv"))
    if not files:
        raise SystemExit("no cross_signal_baseline_events_*.csv found")
    stamp = files[-1].stem.replace("cross_signal_baseline_events_", "")
    return date.fromisoformat(stamp)


def _fmt_num(value: object, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}"


if __name__ == "__main__":
    main()
