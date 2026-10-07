#!/usr/bin/env python3
"""Daily industry regime panel: 主线 + 刚亮候选方向.

Main theme = near-end persistent hot core (spreading not required).
Candidates = near-end expanding/brightening patches outside the main core;
license = 可关注 under 衰落/无主线, 受压 under 统治.

Usage:
  .venv/bin/python scripts/rim_regime_panel.py
  .venv/bin/python scripts/rim_regime_panel.py --as-of 2026-09-24
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.env import load_env  # noqa: E402

load_env()

from app.db import (  # noqa: E402
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
    fetch_trading_dates_ending,
)
from app.themes.heat_rim_regime import (  # noqa: E402
    DOMINANCE_LOOKBACK,
    H_GAP_MIN,
    H_MIN,
    JACCARD_KEEP,
    PERSIST_DAYS,
    S_MIN,
    DayRegime,
    cores_from_listed,
    label_series,
    list_persistent_hot_cores,
)
from app.themes.heat_seriation import (  # noqa: E402
    as_float,
    hotness_grid,
    hotness_series_by_code,
    order_by_trajectory_seriation,
)

OUT_DIR = ROOT / "experiments" / "out"
WINDOW_DAYS = 40
SIGNAL_DAYS = 100


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    tip = fetch_heat_dates_ending("industry", args.as_of or date.today(), 1)
    as_of = args.as_of or (tip[-1] if tip else date.today())

    need = SIGNAL_DAYS + WINDOW_DAYS
    calendar = fetch_trading_dates_ending("industry", as_of, need)
    if len(calendar) < WINDOW_DAYS + SIGNAL_DAYS:
        raise SystemExit(f"not enough trading days: {len(calendar)}")
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
    for trade_date, board_code, board_name, heat_short, _long in heat_rows:
        if board_name:
            names[str(board_code)] = str(board_name)
        val = as_float(heat_short)
        if val is None:
            continue
        heat_by_day.setdefault(trade_date, {})[str(board_code)] = val

    daily: list[tuple] = []
    for n, day in enumerate(signal_dates, start=1):
        if n == 1 or n % 20 == 0 or n == len(signal_dates):
            print(f"  {n}/{len(signal_dates)} {day}", flush=True)
        day_i = date_index[day]
        window = calendar[day_i - WINDOW_DAYS + 1 : day_i + 1]
        plane = _plane_for_day(
            window_dates=window, heat_by_day=heat_by_day, names=names
        )
        listed = list_persistent_hot_cores(
            dates=plane["dates"],
            codes=plane["codes"],
            names=plane["names"],
            z=plane["z"],
        )
        daily.append((day, cores_from_listed(listed), plane))

    regimes = label_series(daily, lookback=DOMINANCE_LOOKBACK)
    stamp = as_of.isoformat()
    notes = _summarize(as_of=stamp, signal_dates=signal_dates, regimes=regimes)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = OUT_DIR / f"rim_regime_panel_{stamp}.txt"
    csv_path = OUT_DIR / f"rim_regime_panel_{stamp}.csv"
    txt_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    _write_csv(csv_path, regimes)
    print("\n".join(notes))
    print(f"wrote {txt_path}")
    print(f"wrote {csv_path}")


def _plane_for_day(
    *,
    window_dates: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
) -> dict:
    codes = sorted(
        {
            code
            for day in window_dates
            for code in (heat_by_day.get(day) or {})
        }
    )
    if not codes:
        return {
            "dates": window_dates,
            "codes": [],
            "names": [],
            "z": [],
        }
    series = hotness_series_by_code(
        window_dates=window_dates, codes=codes, heat_by_day=heat_by_day
    )
    ordered = order_by_trajectory_seriation(codes, series)
    labels = [names.get(code, code) for code in ordered]
    z = hotness_grid(
        window_dates=window_dates, ordered_codes=ordered, heat_by_day=heat_by_day
    )
    return {
        "dates": window_dates,
        "codes": ordered,
        "names": labels,
        "z": z,
    }


def _summarize(
    *,
    as_of: str,
    signal_dates: list[date],
    regimes: list[DayRegime],
) -> list[str]:
    counts = Counter(row.regime for row in regimes)
    n_cand_days = sum(1 for row in regimes if row.cand_n > 0)
    n_watch = sum(1 for row in regimes if row.cand_license == "可关注")
    n_press = sum(1 for row in regimes if row.cand_license == "受压")
    last = regimes[-5:] if regimes else []
    last_lines = [
        f"  {row.signal_date}  {row.regime}  main={row.members or '—'}  "
        f"cand[{row.cand_license}] {row.cand_members or '—'} ({row.cand_relation or '—'})"
        for row in last
    ]
    return [
        f"as_of={as_of}",
        f"signal_days={len(signal_dates)} {signal_dates[0]} → {signal_dates[-1]}",
        f"window={WINDOW_DAYS} persist={PERSIST_DAYS} lookback={DOMINANCE_LOOKBACK} "
        f"jaccard={JACCARD_KEEP}",
        f"main: persistent hot core; dominate H>={H_MIN} S>={S_MIN} or gap>={H_GAP_MIN}",
        "cand: rim expanding/brightening outside main; license 可关注|受压 by regime",
        f"counts: "
        + "  ".join(
            f"{name}={counts.get(name, 0)}" for name in ("主线统治", "主线衰落", "无主线")
        ),
        f"cand_days={n_cand_days}  可关注={n_watch}  受压={n_press}",
        "",
        "last 5 days:",
        *(last_lines or ["  (none)"]),
    ]


def _write_csv(path: Path, regimes: list[DayRegime]) -> None:
    if not regimes:
        path.write_text("", encoding="utf-8")
        return
    fields = [
        "signal_date",
        "regime",
        "label",
        "members",
        "w",
        "w2",
        "s",
        "h",
        "h2",
        "k",
        "jaccard_prev",
        "dominate_ok",
        "fade_flags",
        "lineage_label",
        "cand_n",
        "cand_license",
        "cand_relation",
        "cand_w",
        "cand_label",
        "cand_members",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in regimes:
            writer.writerow(
                {
                    "signal_date": row.signal_date.isoformat(),
                    "regime": row.regime,
                    "label": row.label,
                    "members": row.members,
                    "w": row.w,
                    "w2": row.w2,
                    "s": row.s,
                    "h": row.h,
                    "h2": row.h2,
                    "k": row.k,
                    "jaccard_prev": row.jaccard_prev,
                    "dominate_ok": int(row.dominate_ok),
                    "fade_flags": row.fade_flags,
                    "lineage_label": row.lineage_label,
                    "cand_n": row.cand_n,
                    "cand_license": row.cand_license,
                    "cand_relation": row.cand_relation,
                    "cand_w": row.cand_w,
                    "cand_label": row.cand_label,
                    "cand_members": row.cand_members,
                }
            )


if __name__ == "__main__":
    main()
