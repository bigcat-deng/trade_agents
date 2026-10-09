#!/usr/bin/env python3
"""Industry 1D Morlet CWT → near-end strongest mode → 5-day phase forecast.

Phase-1 offline experiment only (no web page). Writes under experiments/out/:
  - industry_cwt_phase_{as_of}.csv   per-board mode / asymmetry / forecast
  - industry_cwt_phase_{as_of}.png    hist+forecast hotness plane (own-window h)
  - industry_cwt_spectrum_{as_of}.png a few board energy-weighted period spectra

Usage (repo root):
  .venv/bin/python scripts/industry_cwt_phase_forecast.py
  .venv/bin/python scripts/industry_cwt_phase_forecast.py --as-of 2026-05-13
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap

from app.charts.theme_wave import _COLORSCALE  # noqa: E402
from app.db import (  # noqa: E402
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
    fetch_trading_dates_after,
)
from app.themes.heat_cwt1d import (  # noqa: E402
    FORECAST_DAYS,
    WINDOW_DAYS,
    analyze_board_series,
)
from app.themes.heat_forecast import resolve_forecast_dates  # noqa: E402
from app.themes.heat_seriation import (  # noqa: E402
    densify_hotness_plane,
    order_by_trajectory_seriation,
)

OUT_DIR = ROOT / "experiments" / "out"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    parser.add_argument("--forecast-days", type=int, default=FORECAST_DAYS)
    parser.add_argument(
        "--spectrum-boards",
        type=int,
        default=6,
        help="How many boards to plot individual spectra for",
    )
    args = parser.parse_args()
    if args.window_days < 40:
        raise SystemExit("--window-days must be >= 40")

    tip_dates = fetch_heat_dates_ending("industry", args.as_of or date.today(), 1)
    if not tip_dates:
        raise SystemExit("no industry heat tip date")
    tip = tip_dates[-1]
    hist = fetch_heat_dates_ending("industry", tip, args.window_days)
    if len(hist) < 40:
        raise SystemExit(f"only {len(hist)} heat days ending {tip}")
    rows = fetch_industry_heat_window(hist[0], tip)
    heat: dict[date, dict[str, float]] = {}
    names: dict[str, str] = {}
    for trade_date, code, name, hs, _hl in rows:
        names[code] = name or code
        if hs is None:
            continue
        heat.setdefault(trade_date, {})[code] = float(hs)

    codes = sorted({c for day in hist for c in (heat.get(day) or {})})
    # series for seriation: own-window h after analyze (build raw heat_short lists)
    hs_by_code: dict[str, list[float | None]] = {
        c: [ (heat.get(d) or {}).get(c) for d in hist ] for c in codes
    }
    analyses = {c: analyze_board_series(hs_by_code[c]) for c in codes}
    h_series = {
        c: [None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)
            for v in analyses[c]["h"]]
        for c in codes
    }
    ordered = order_by_trajectory_seriation(codes, h_series)

    known_fwd = fetch_trading_dates_after("industry", tip, args.forecast_days)
    fwd = resolve_forecast_dates(
        as_of=tip, n=args.forecast_days, known_forward=known_fwd
    )

    # Plane: history h + forecast
    z_hist: list[list[float | None]] = []
    for i, _d in enumerate(hist):
        z_hist.append([h_series[c][i] for c in ordered])
    z_fwd: list[list[float | None]] = []
    for j in range(len(fwd)):
        row: list[float | None] = []
        for c in ordered:
            fc = analyses[c].get("forecast") or []
            row.append(float(fc[j]) if j < len(fc) else None)
        z_fwd.append(row)
    z_native = z_hist + z_fwd
    display_dates = list(hist) + list(fwd)
    x_ticks = list(range(len(ordered)))
    dense_x, dense_z = densify_hotness_plane(
        theme_x=[float(i) for i in x_ticks],
        z_short=z_native,
        densify=3,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / f"industry_cwt_phase_{tip.isoformat()}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "board_code",
                "board_name",
                "period",
                "energy_share",
                "amp",
                "amp_trend",
                "phase",
                "center",
                "up_mean_len",
                "down_mean_len",
                "up_mean_slope",
                "down_mean_slope",
                *[f"h_{d.isoformat()}" for d in fwd],
            ]
        )
        for c in ordered:
            a = analyses[c]
            m = a.get("mode")
            asym = a.get("asym")
            fc = a.get("forecast") or []
            w.writerow(
                [
                    c,
                    names.get(c, c),
                    None if m is None else round(m.period, 3),
                    None if m is None else round(m.energy_share, 4),
                    None if a.get("amp") is None else round(float(a["amp"]), 4),
                    a.get("amp_trend"),
                    None if m is None else round(m.phase, 4),
                    None if m is None else round(m.center, 4),
                    None if asym is None or asym.up_mean_len is None else round(asym.up_mean_len, 3),
                    None if asym is None or asym.down_mean_len is None else round(asym.down_mean_len, 3),
                    None if asym is None or asym.up_mean_slope is None else round(asym.up_mean_slope, 4),
                    None if asym is None or asym.down_mean_slope is None else round(asym.down_mean_slope, 4),
                    *[
                        (round(fc[j], 4) if j < len(fc) else None)
                        for j in range(len(fwd))
                    ],
                ]
            )

    _setup_font()
    plane_path = OUT_DIR / f"industry_cwt_phase_{tip.isoformat()}.png"
    _plot_plane(
        tip=tip,
        dates=display_dates,
        hist_n=len(hist),
        ordered=ordered,
        names=names,
        dense_x=dense_x,
        dense_z=dense_z,
        x_ticks=x_ticks,
        out_path=plane_path,
    )

    # Spectra for boards with highest near-end energy share
    scored = []
    for c in ordered:
        m = analyses[c].get("mode")
        if m is not None:
            scored.append((m.energy_share, c))
    scored.sort(reverse=True)
    pick = [c for _s, c in scored[: max(1, args.spectrum_boards)]]
    spec_path = OUT_DIR / f"industry_cwt_spectrum_{tip.isoformat()}.png"
    _plot_spectra(pick, names, analyses, tip, spec_path)

    print(f"as_of={tip.isoformat()} boards={len(ordered)} hist={len(hist)} fwd={len(fwd)}")
    print(f"wrote {csv_path}")
    print(f"wrote {plane_path}")
    print(f"wrote {spec_path}")
    if scored:
        top = scored[0][1]
        m = analyses[top]["mode"]
        print(
            f"top_share {names.get(top, top)} period={m.period:.1f}d "
            f"share={m.energy_share:.2%} trend={analyses[top].get('amp_trend')}"
        )


def _setup_font() -> None:
    for fname in ("PingFang SC", "Heiti SC", "Arial Unicode MS", "Noto Sans CJK SC"):
        if any(fname in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [fname]
            break
    plt.rcParams["axes.unicode_minus"] = False


def _plot_plane(
    *,
    tip: date,
    dates: list[date],
    hist_n: int,
    ordered: list[str],
    names: dict[str, str],
    dense_x: list[float],
    dense_z: list[list[float | None]],
    x_ticks: list[int],
    out_path: Path,
) -> None:
    arr = np.array(
        [[(np.nan if v is None else v) for v in row] for row in dense_z], dtype=float
    )
    cmap = LinearSegmentedColormap.from_list(
        "theme_heat", [(s, c) for s, c in _COLORSCALE]
    )
    n_hist_d = int(round(hist_n * (arr.shape[0] / len(dates))))
    join_y = n_hist_d - 0.5
    fig, ax = plt.subplots(figsize=(14, 8.0), dpi=140)
    fig.patch.set_facecolor("#fffdf8")
    ax.set_facecolor("#fffdf8")
    im = ax.imshow(
        arr,
        aspect="auto",
        origin="lower",
        cmap=cmap,
        vmin=0,
        vmax=1,
        interpolation="bilinear",
        extent=(-0.5, len(ordered) - 0.5, -0.5, arr.shape[0] - 0.5),
    )
    ax.axhline(join_y, color="#dc2626", lw=2.0, ls="--", zorder=5)
    # y ticks
    yticks = []
    ylabels = []
    step = max(1, hist_n // 8)
    for i in list(range(0, hist_n, step)) + [hist_n - 1]:
        y = (i + 0.5) * (arr.shape[0] / len(dates)) - 0.5
        yticks.append(y)
        ylabels.append(dates[i].isoformat()[5:])
    for j in range(hist_n, len(dates)):
        y = (j + 0.5) * (arr.shape[0] / len(dates)) - 0.5
        yticks.append(y)
        ylabels.append(dates[j].isoformat()[5:])
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=8)
    labels = [names.get(c, c) for c in ordered]
    step_x = max(1, len(ordered) // 16)
    xt = list(range(0, len(ordered), step_x))
    ax.set_xticks(xt)
    ax.set_xticklabels([labels[i] for i in xt], rotation=55, ha="right", fontsize=7)
    ax.set_title(
        f"行业短热 · CWT相位续推（窗{WINDOW_DAYS}日，截止 {tip.isoformat()}）",
        fontsize=12,
    )
    ax.set_xlabel("行业（轨迹叶序）")
    ax.set_ylabel("交易日")
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("h（板内映射，越大越热）")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_spectra(
    codes: list[str],
    names: dict[str, str],
    analyses: dict,
    tip: date,
    out_path: Path,
) -> None:
    n = len(codes)
    fig, axes = plt.subplots(n, 1, figsize=(10, 1.8 * n + 1.0), dpi=130, sharex=True)
    if n == 1:
        axes = [axes]
    fig.patch.set_facecolor("#fffdf8")
    for ax, c in zip(axes, codes):
        a = analyses[c]
        periods = a.get("spectrum_periods") or []
        spec = a.get("spectrum") or []
        ax.set_facecolor("#fffdf8")
        if periods and spec:
            ax.plot(periods, spec, color="#0f766e", lw=1.6)
            m = a.get("mode")
            if m is not None:
                ax.axvline(m.period, color="#dc2626", ls="--", lw=1.2)
                ax.set_title(
                    f"{names.get(c, c)} · 主导周期 {m.period:.0f}日 · "
                    f"能量占比 {m.energy_share:.1%} · {a.get('amp_trend')}",
                    fontsize=10,
                    loc="left",
                )
        ax.set_ylabel("能量份额")
    axes[-1].set_xlabel("周期（交易日）")
    fig.suptitle(f"能量加权周期谱（近端加权）· {tip.isoformat()}", fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
