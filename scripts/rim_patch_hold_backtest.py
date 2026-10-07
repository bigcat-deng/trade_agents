#!/usr/bin/env python3
"""Step 1: industry bright-patch basket vs same-day complement.

Onset only (not every day). Equal-weight frozen members from entry close to
the first later session where the matched band is stale or Jaccard < 0.5.
Benchmark is equal-weight of other industries with prices on both days.

Usage:
  .venv/bin/python scripts/rim_patch_hold_backtest.py
  .venv/bin/python scripts/rim_patch_hold_backtest.py --as-of 2026-09-24
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.env import load_env  # noqa: E402

load_env()

from app.db import (  # noqa: E402
    fetch_board_close_heat,
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
    fetch_trading_dates_ending,
)
from app.market_data.csi500 import fetch_csi500_closes  # noqa: E402
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
JACCARD_KEEP = 0.5


@dataclass
class PatchView:
    codes: frozenset[str]
    names: tuple[str, ...]
    label: str
    width_then: int
    width_now: int
    expanding: bool
    brightening: bool
    active: bool
    n_core: int
    n_edge: int


@dataclass
class OpenEvent:
    event_id: str
    entry: date
    frozen: tuple[str, ...]
    last_set: frozenset[str]
    label: str
    width_then: int
    width_now: int
    n_core: int
    n_edge: int
    hottest: tuple[str, ...]
    random_run: tuple[str, ...]


@dataclass
class DayPlane:
    ordered: list[str]
    hotness: dict[str, float]
    live: list[PatchView]
    all_runs: list[PatchView]


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
    all_codes: set[str] = set()
    for trade_date, board_code, board_name, heat_short, _long in heat_rows:
        if board_name:
            names[str(board_code)] = str(board_name)
        val = as_float(heat_short)
        if val is None:
            continue
        code = str(board_code)
        all_codes.add(code)
        heat_by_day.setdefault(trade_date, {})[code] = val

    close_heat = fetch_board_close_heat(
        "industry", sorted(all_codes), calendar[0], as_of
    )
    closes: dict[str, dict[date, float]] = {}
    for code, rows in close_heat.items():
        by_day: dict[date, float] = {}
        for day, close, _hs, _hl in rows:
            val = as_float(close)
            if val is not None:
                by_day[day] = val
        closes[code] = by_day
    index_closes = dict(fetch_csi500_closes(calendar[0], as_of))

    open_events: list[OpenEvent] = []
    events: list[dict[str, object]] = []
    n_onset = 0
    n_censored = 0
    prev_live: list[PatchView] = []
    seq = 0

    for n, day in enumerate(signal_dates, start=1):
        if n == 1 or n % 20 == 0 or n == len(signal_dates):
            print(f"  {n}/{len(signal_dates)} {day}", flush=True)
        day_i = date_index[day]
        window = calendar[day_i - WINDOW_DAYS + 1 : day_i + 1]
        plane = _plane_for_day(
            window_dates=window, heat_by_day=heat_by_day, names=names
        )

        still_open: list[OpenEvent] = []
        for event in open_events:
            matched, jac = _best_match(event.last_set, plane.all_runs)
            stale = (
                matched is None
                or jac < JACCARD_KEEP
                or not matched.active
            )
            if not stale:
                event.last_set = matched.codes
                still_open.append(event)
                continue
            row = _settle_event(
                event=event,
                exit_day=day,
                hold_days=date_index[day] - date_index[event.entry],
                closes=closes,
                index_closes=index_closes,
                names=names,
                exit_reason=_exit_reason(matched, jac),
            )
            if row is None:
                n_censored += 1
            else:
                events.append(row)
        open_events = still_open

        for patch in plane.live:
            _, jac = _best_match(patch.codes, prev_live)
            if jac >= JACCARD_KEEP:
                continue
            seq += 1
            n_onset += 1
            frozen = tuple(sorted(patch.codes))
            hottest = _hottest_codes(plane.hotness, len(frozen))
            random_run = _random_run(
                ordered=plane.ordered,
                width=len(frozen),
                avoid=patch.codes,
                seed=f"{day.isoformat()}|{seq}",
            )
            open_events.append(
                OpenEvent(
                    event_id=f"{day.isoformat()}-{seq}",
                    entry=day,
                    frozen=frozen,
                    last_set=patch.codes,
                    label=patch.label,
                    width_then=patch.width_then,
                    width_now=patch.width_now,
                    n_core=patch.n_core,
                    n_edge=patch.n_edge,
                    hottest=hottest,
                    random_run=random_run,
                )
            )
        prev_live = plane.live

    n_censored += len(open_events)
    stamp = as_of.isoformat()
    notes = _format_report(
        as_of=stamp,
        signal_dates=signal_dates,
        n_onset=n_onset,
        n_censored=n_censored,
        events=events,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = OUT_DIR / f"rim_patch_hold_{stamp}.txt"
    csv_path = OUT_DIR / f"rim_patch_hold_events_{stamp}.csv"
    txt_path.write_text("\n".join(notes) + "\n", encoding="utf-8")
    _write_csv(csv_path, events)
    print("\n".join(notes))
    print(f"wrote {txt_path}")
    print(f"wrote {csv_path}")


def _plane_for_day(
    *,
    window_dates: list[date],
    heat_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
) -> DayPlane:
    empty = DayPlane(ordered=[], hotness={}, live=[], all_runs=[])
    codes = sorted(
        {
            code
            for day in window_dates
            for code in (heat_by_day.get(day) or {})
        }
    )
    if not codes:
        return empty
    series = hotness_series_by_code(
        window_dates=window_dates, codes=codes, heat_by_day=heat_by_day
    )
    ordered = order_by_trajectory_seriation(codes, series)
    labels = [names.get(code, code) for code in ordered]
    z = hotness_grid(
        window_dates=window_dates, ordered_codes=ordered, heat_by_day=heat_by_day
    )
    listed = list_heat_rim_patches(
        dates=window_dates,
        codes=ordered,
        names=labels,
        z=z,
        include_inactive=True,
    )
    grid = z
    hotness: dict[str, float] = {}
    finite_rows = [
        i
        for i, row in enumerate(grid)
        if any(v is not None for v in row)
    ]
    if finite_rows:
        t_end = finite_rows[-1]
        for col, code in enumerate(ordered):
            val = grid[t_end][col]
            if val is not None:
                hotness[code] = float(val)
    all_runs = [_as_patch_view(p) for p in (listed.get("patches") or [])]
    live = [p for p in all_runs if p.active]
    return DayPlane(ordered=ordered, hotness=hotness, live=live, all_runs=all_runs)


def _as_patch_view(patch: dict) -> PatchView:
    members = list(patch.get("members") or [])
    codes = frozenset(str(m["board_code"]) for m in members)
    return PatchView(
        codes=codes,
        names=tuple(str(m["board_name"]) for m in members),
        label=str(patch.get("label") or ""),
        width_then=int(patch.get("width_then") or 0),
        width_now=int(patch.get("width_now") or 0),
        expanding=bool(patch.get("expanding")),
        brightening=bool(patch.get("brightening")),
        active=bool(patch.get("active")),
        n_core=sum(1 for m in members if m.get("role") == "核"),
        n_edge=sum(1 for m in members if m.get("role") == "边"),
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _best_match(
    members: frozenset[str], patches: list[PatchView]
) -> tuple[PatchView | None, float]:
    best: PatchView | None = None
    best_j = -1.0
    for patch in patches:
        jac = _jaccard(members, patch.codes)
        if jac > best_j:
            best_j = jac
            best = patch
    if best is None:
        return None, 0.0
    return best, best_j


def _exit_reason(matched: PatchView | None, jac: float) -> str:
    if matched is None or jac < JACCARD_KEEP:
        return "jaccard"
    if not matched.active:
        return "stale"
    return "other"


def _hottest_codes(hotness: dict[str, float], n: int) -> tuple[str, ...]:
    if n < 1 or not hotness:
        return ()
    ranked = sorted(hotness, key=lambda code: (-hotness[code], code))
    return tuple(ranked[:n])


def _random_run(
    *,
    ordered: list[str],
    width: int,
    avoid: frozenset[str],
    seed: str,
) -> tuple[str, ...]:
    if width < 1 or len(ordered) < width:
        return ()
    rng = random.Random(seed)
    starts = list(range(0, len(ordered) - width + 1))
    rng.shuffle(starts)
    for start in starts:
        run = tuple(ordered[start : start + width])
        if frozenset(run) != avoid:
            return run
    start = starts[0] if starts else 0
    return tuple(ordered[start : start + width])


def _pct_return(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start == 0:
        return None
    return (end / start - 1.0) * 100.0


def _basket_return(
    codes: tuple[str, ...],
    start: date,
    end: date,
    closes: dict[str, dict[date, float]],
) -> tuple[float | None, int]:
    rets: list[float] = []
    for code in codes:
        ret = _pct_return(
            closes.get(code, {}).get(start),
            closes.get(code, {}).get(end),
        )
        if ret is not None:
            rets.append(ret)
    if not rets:
        return None, 0
    return mean(rets), len(rets)


def _complement_codes(
    frozen: tuple[str, ...],
    start: date,
    end: date,
    closes: dict[str, dict[date, float]],
) -> tuple[str, ...]:
    skip = set(frozen)
    out: list[str] = []
    for code, by_day in closes.items():
        if code in skip:
            continue
        if start in by_day and end in by_day:
            out.append(code)
    return tuple(sorted(out))


def _settle_event(
    *,
    event: OpenEvent,
    exit_day: date,
    hold_days: int,
    closes: dict[str, dict[date, float]],
    index_closes: dict[date, float],
    names: dict[str, str],
    exit_reason: str,
) -> dict[str, object] | None:
    if hold_days < 1:
        return None
    patch_ret, n_patch = _basket_return(event.frozen, event.entry, exit_day, closes)
    complement = _complement_codes(event.frozen, event.entry, exit_day, closes)
    rest_ret, n_rest = _basket_return(complement, event.entry, exit_day, closes)
    if patch_ret is None or rest_ret is None:
        return None
    hot_ret, n_hot = _basket_return(event.hottest, event.entry, exit_day, closes)
    hot_rest = _complement_codes(event.hottest, event.entry, exit_day, closes)
    hot_rest_ret, _n = _basket_return(hot_rest, event.entry, exit_day, closes)
    rnd_ret, n_rnd = _basket_return(event.random_run, event.entry, exit_day, closes)
    rnd_rest = _complement_codes(event.random_run, event.entry, exit_day, closes)
    rnd_rest_ret, _n = _basket_return(rnd_rest, event.entry, exit_day, closes)
    index_ret = _pct_return(index_closes.get(event.entry), index_closes.get(exit_day))
    excess = patch_ret - rest_ret
    return {
        "event_id": event.event_id,
        "entry": event.entry.isoformat(),
        "exit": exit_day.isoformat(),
        "hold_days": hold_days,
        "exit_reason": exit_reason,
        "label": event.label,
        "width_then": event.width_then,
        "width_now": event.width_now,
        "n_core": event.n_core,
        "n_edge": event.n_edge,
        "n_frozen": len(event.frozen),
        "n_patch_priced": n_patch,
        "n_rest": n_rest,
        "members": ",".join(names.get(code, code) for code in event.frozen),
        "patch_ret": patch_ret,
        "rest_ret": rest_ret,
        "excess": excess,
        "hot_ret": hot_ret,
        "hot_excess": None
        if hot_ret is None or hot_rest_ret is None
        else hot_ret - hot_rest_ret,
        "n_hot_priced": n_hot,
        "rnd_ret": rnd_ret,
        "rnd_excess": None
        if rnd_ret is None or rnd_rest_ret is None
        else rnd_ret - rnd_rest_ret,
        "n_rnd_priced": n_rnd,
        "index_ret": index_ret,
        "excess_vs_csi500": None if index_ret is None else patch_ret - index_ret,
    }


def _col(events: list[dict[str, object]], key: str) -> list[float]:
    out: list[float] = []
    for row in events:
        val = row.get(key)
        if val is None:
            continue
        out.append(float(val))
    return out


def _bucket_line(name: str, excesses: list[float]) -> str:
    if not excesses:
        return f"{name:<16} n=0"
    n = len(excesses)
    wins = sum(1 for x in excesses if x > 0)
    return (
        f"{name:<16} n={n:<4} win={100 * wins / n:5.1f}%  "
        f"med={median(excesses):7.2f}  mean={mean(excesses):7.2f}"
    )


def _format_report(
    *,
    as_of: str,
    signal_dates: list[date],
    n_onset: int,
    n_censored: int,
    events: list[dict[str, object]],
) -> list[str]:
    excess = _col(events, "excess")
    hot = _col(events, "hot_excess")
    rnd = _col(events, "rnd_excess")
    vs500 = _col(events, "excess_vs_csi500")
    holds = [int(row["hold_days"]) for row in events]
    gate = "fail"
    if excess:
        win = sum(1 for x in excess if x > 0) / len(excess)
        med = median(excess)
        if med > 0 and win > 0.5:
            gate = "pass"
        elif med > 0 or win > 0.5:
            gate = "mixed"
    holds_note = "—"
    if holds:
        holds_note = (
            f"min={min(holds)} p50={median(holds):.0f} "
            f"mean={mean(holds):.1f} max={max(holds)}"
        )
    return [
        f"as_of={as_of}",
        f"signal_days={len(signal_dates)} {signal_dates[0]} → {signal_dates[-1]}",
        f"window={WINDOW_DAYS} jaccard_keep={JACCARD_KEEP}",
        "onset frozen patch vs same-day complement; exit stale or Jaccard<0.5",
        f"onsets={n_onset} settled={len(events)} censored_open={n_censored}",
        f"hold_days {holds_note}",
        "",
        _bucket_line("patch-rest", excess),
        _bucket_line("hottest-rest", hot),
        _bucket_line("random-rest", rnd),
        _bucket_line("patch-csi500", vs500),
        "",
        f"gate (median>0 and win>50% on patch-rest): {gate}",
        "pass requires both; mixed = one of the two; fail = neither.",
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
