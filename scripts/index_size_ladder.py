#!/usr/bin/env python3
"""Write the size-ladder PNG and JSON under experiments/out/.

The page at /indices/size-ladder uses the same calculation. This script is the
offline copy.

Usage (repo root):
  .venv/bin/python scripts/index_size_ladder.py
  .venv/bin/python scripts/index_size_ladder.py --n 100 --as-of 2026-10-13
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

from app.market_data.index_ladder import INDICES, build_payload, fetch_index_bars

OUT_DIR = ROOT / "experiments" / "out"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=100, help="trading-day window")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    if args.n < 5:
        raise SystemExit("--n must be >= 5")

    end = args.as_of or date.today()
    start = end - timedelta(days=args.n * 2 + 40)
    try:
        bars = fetch_index_bars(start, end)
        payload = build_payload(bars, n=args.n, as_of=end)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = OUT_DIR / f"index_size_ladder_{payload['end']}"
    stem.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _setup_font()
    fig = plot_ladder(payload)
    png = stem.with_suffix(".png")
    fig.savefig(png, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    end_rows = payload["snapshot"]
    print(f"window {payload['start']} -> {payload['end']} n={payload['n']}")
    for name, _code, _color in INDICES:
        row = end_rows[name]
        print(
            f"{name}: ret={row['return_pct']:+.2f}% pos={row['position']:.3f} "
            f"high={row['high_date']} low={row['low_date']}"
        )
    print(
        f"range_pp={payload['range_pp'][-1]:.2f} "
        f"spread_50_2000_pp={payload['spread_50_2000_pp'][-1]:+.2f}"
    )
    print(f"wrote {png}")
    print(f"wrote {stem.with_suffix('.json')}")


def plot_ladder(payload: dict):
    dates = [date.fromisoformat(value) for value in payload["dates"]]
    x = np.arange(len(dates))
    fig, axes = plt.subplots(3, 1, figsize=(11.2, 8.6), sharex=True, layout="constrained")
    fig.patch.set_facecolor("white")

    ax_ret, ax_spread, ax_pos = axes
    for name, _code, color in INDICES:
        ax_ret.plot(x, payload["returns_pct"][name], color=color, lw=1.6, label=name)
        ax_pos.plot(x, payload["position"][name], color=color, lw=1.6, label=name)
    ax_ret.axhline(0.0, color="#888888", lw=0.8)
    ax_ret.set_ylabel("累计收益 (%)")
    ax_ret.set_title("累计收益，窗口首日收盘 = 0")
    ax_ret.legend(loc="upper right", frameon=False, fontsize=9)
    ax_ret.grid(True, axis="y", color="#e6e6e6", lw=0.6)

    ax_spread.plot(x, payload["range_pp"], color="#555555", lw=1.5, label="截面极差（五条最高−最低）")
    ax_spread.plot(
        x,
        payload["spread_50_2000_pp"],
        color="#1f4e79",
        lw=1.5,
        label="上证50 − 国证2000",
    )
    ax_spread.axhline(0.0, color="#888888", lw=0.8)
    ax_spread.set_ylabel("百分点")
    ax_spread.set_title("散度")
    ax_spread.legend(loc="upper left", frameon=False, fontsize=9)
    ax_spread.grid(True, axis="y", color="#e6e6e6", lw=0.6)

    ax_pos.set_ylim(-0.03, 1.03)
    ax_pos.set_ylabel("区间位置")
    ax_pos.set_title("区间位置，各自 avg=(高+低+收)/3 在本窗口的 min-max")
    ax_pos.set_xlabel("交易日")
    ax_pos.grid(True, axis="y", color="#e6e6e6", lw=0.6)

    tick_idx = list(range(0, len(dates), 10))
    if tick_idx[-1] != len(dates) - 1:
        tick_idx.append(len(dates) - 1)
    ax_pos.set_xticks(tick_idx)
    ax_pos.set_xticklabels([dates[i].strftime("%m-%d") for i in tick_idx])

    range_now = payload["range_pp"][-1]
    spread_now = payload["spread_50_2000_pp"][-1]
    fig.suptitle(
        f"市值阶梯  {payload['start']} — {payload['end']}  "
        f"（{payload['n']} 个交易日，baostock）\n"
        f"期末截面极差 {range_now:.1f} 个百分点，"
        f"上证50−国证2000 {spread_now:+.1f} 个百分点",
        fontsize=12,
    )
    return fig


def _setup_font() -> None:
    for fname in ("PingFang SC", "Heiti SC", "Arial Unicode MS", "Noto Sans CJK SC"):
        if any(fname in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [fname]
            break
    plt.rcParams["axes.unicode_minus"] = False


if __name__ == "__main__":
    main()
