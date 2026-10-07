#!/usr/bin/env python3
"""Step 0: daily industry bright-patch panel (no trades).

Each signal day T: 40d short-heat plane (same seriation as the wave page),
then every expanding or brightening connected run. No Top-N cut, no MACD score.

Usage:
  .venv/bin/python scripts/rim_patch_panel.py
  .venv/bin/python scripts/rim_patch_panel.py --as-of 2026-09-24
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path
from statistics import mean

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
from app.themes.heat_rim_spread import list_heat_rim_patches  # noqa: E402
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

    patch_rows: list[dict[str, object]] = []
    member_rows: list[dict[str, object]] = []
    empty_days = 0
    for n, day in enumerate(signal_dates, start=1):
        if n == 1 or n % 20 == 0 or n == len(signal_dates):
            print(f"  {n}/{len(signal_dates)} {day}", flush=True)
        day_i = date_index[day]
        window = calendar[day_i - WINDOW_DAYS + 1 : day_i + 1]
        listed = _patches_for_day(
            window_dates=window, heat_by_day=heat_by_day, names=names
        )
        patches = list(listed.get("patches") or [])
        if not patches:
            empty_days += 1
        for seq, patch in enumerate(patches, start=1):
            n_core = sum(1 for m in patch["members"] if m["role"] == "核")
            n_edge = sum(1 for m in patch["members"] if m["role"] == "边")
            patch_id = f"{day.isoformat()}-{seq}"
            patch_rows.append(
                {
                    "signal_date": day.isoformat(),
                    "as_of": listed.get("as_of"),
                    "patch_id": patch_id,
                    "patch_seq": seq,
                    "label": patch["label"],
                    "lo": patch["lo"],
                    "hi": patch["hi"],
                    "width_then": patch["width_then"],
                    "width_now": patch["width_now"],
                    "expanding": int(bool(patch["expanding"])),
                    "brightening": int(bool(patch["brightening"])),
                    "mean_heat": patch["mean_heat"],
                    "n_members": len(patch["members"]),
                    "n_core": n_core,
                    "n_edge": n_edge,
                    "members": ",".join(
                        str(m["board_name"]) for m in patch["members"]
                    ),
                }
            )
            for member in patch["members"]:
                member_rows.append(
                    {
                        "signal_date": day.isoformat(),
                        "as_of": listed.get("as_of"),
                        "patch_id": patch_id,
                        "patch_seq": seq,
                        "label": patch["label"],
                        "lo": patch["lo"],
                        "hi": patch["hi"],
                        "width_then": patch["width_then"],
                        "width_now": patch["width_now"],
                        "expanding": int(bool(patch["expanding"])),
                        "brightening": int(bool(patch["brightening"])),
                        "mean_heat": patch["mean_heat"],
                        "board_code": member["board_code"],
                        "board_name": member["board_name"],
                        "col": member["col"],
                        "role": member["role"],
                        "hotness_asof": member["hotness_asof"],
                        "near_slope": member["near_slope"],
                    }
                )

    stamp = as_of.isoformat()
    notes = _summarize(
        as_of=stamp,
        signal_dates=signal_dates,
        empty_days=empty_days,
        patch_rows=patch_rows,
        member_rows=member_rows,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = OUT_DIR / f"rim_patch_panel_{stamp}.txt"
    patch_path = OUT_DIR / f"rim_patch_panel_patches_{stamp}.csv"
    member_path = OUT_DIR / f"rim_patch_panel_members_{stamp}.csv"
    txt_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    _write_csv(patch_path, patch_rows)
    _write_csv(member_path, member_rows)
    print("\n".join(notes))
    print(f"wrote {txt_path}")
    print(f"wrote {patch_path}")
    print(f"wrote {member_path}")


def _patches_for_day(
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
        return {"as_of": None, "patches": []}
    series = hotness_series_by_code(
        window_dates=window_dates, codes=codes, heat_by_day=heat_by_day
    )
    ordered = order_by_trajectory_seriation(codes, series)
    labels = [names.get(code, code) for code in ordered]
    z = hotness_grid(
        window_dates=window_dates, ordered_codes=ordered, heat_by_day=heat_by_day
    )
    return list_heat_rim_patches(
        dates=window_dates, codes=ordered, names=labels, z=z
    )


def _summarize(
    *,
    as_of: str,
    signal_dates: list[date],
    empty_days: int,
    patch_rows: list[dict[str, object]],
    member_rows: list[dict[str, object]],
) -> list[str]:
    n_days = len(signal_dates)
    n_patch = len(patch_rows)
    widths = [int(row["width_now"]) for row in patch_rows]
    n_exp = sum(int(row["expanding"]) for row in patch_rows)
    n_brt = sum(int(row["brightening"]) for row in patch_rows)
    n_both = sum(
        int(row["expanding"]) and int(row["brightening"]) for row in patch_rows
    )
    n_core = sum(1 for row in member_rows if row["role"] == "核")
    n_edge = sum(1 for row in member_rows if row["role"] == "边")
    last_rows = [row for row in patch_rows if row["signal_date"] == as_of]
    if not last_rows and signal_dates:
        last_rows = [
            row
            for row in patch_rows
            if row["signal_date"] == signal_dates[-1].isoformat()
        ]
    last_lines = []
    for row in last_rows:
        last_lines.append(
            f"  {row['label']}  {row['width_then']}→{row['width_now']}  "
            f"扩开={row['expanding']} 加亮={row['brightening']}  "
            f"核{row['n_core']}/边{row['n_edge']}  {row['members']}"
        )
    return [
        f"as_of={as_of}",
        f"signal_days={n_days} {signal_dates[0]} → {signal_dates[-1]}",
        f"window={WINDOW_DAYS} industry patches (no top-n, no MACD score)",
        f"days_with_no_patch={empty_days}",
        f"patches={n_patch}  expanding={n_exp} brightening={n_brt} both={n_both}",
        f"mean_width_now={mean(widths):.2f}" if widths else "mean_width_now=",
        f"members={len(member_rows)}  core={n_core} edge={n_edge}",
        "",
        f"last_day patches ({last_rows[0]['signal_date'] if last_rows else '—'}):",
        *(last_lines or ["  (none)"]),
    ]


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
