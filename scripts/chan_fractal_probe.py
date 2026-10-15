#!/usr/bin/env python3
"""Probe custom fractals on one board and write a candlestick PNG.

Not part of the sync pipeline. Offline experiment only.

Rule:
  avg = (high + low + close) / 3
  smooth = trailing MA5 of avg
  A smooth local extremum uses a 7-point window (center ± 3).
  A local high marks a top: the true top is the max raw high in that window.
  A local low marks a bottom: the true bottom is the min raw low in that window.
  Adjacent fractals must alternate. Same-type neighbors whose bar gap is
  <= 10 merge, keeping the more extreme price. A gap > 10 inserts the
  opposite extreme on the bars strictly between them.
  If the last bar is at least 5 bars after the previous fractal, that bar
  is itself a fractal of the opposite kind.

Usage (repo root):
  .venv/bin/python scripts/chan_fractal_probe.py
  .venv/bin/python scripts/chan_fractal_probe.py --n 200 --code 881121
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
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

from app.db import fetch_board_daily_bars_from_db, fetch_board_name

OUT_DIR = ROOT / "experiments" / "out"
BOARD_TYPE = "industry"
DEFAULT_CODE = "881121"
WINDOW = 7
RADIUS = WINDOW // 2
MA = 5
# Same-type neighbors at this gap or closer merge; a wider gap inserts.
SAME_TYPE_GAP = 10
ENDPOINT_GAP = 5
VOLUME_BINS = 15
VOLUME_GROUP = 4
# MA5 at index i needs bars [i-4, i]. A center at the first plotted bar also
# looks 3 bars further left, whose MA needs 4 more bars.
WARMUP = (MA - 1) + RADIUS


@dataclass(frozen=True)
class Fractal:
    kind: str
    index: int
    smooth_index: int
    price: float
    source: str = "raw"


@dataclass(frozen=True)
class Stroke:
    direction: str
    start: Fractal
    end: Fractal


@dataclass(frozen=True)
class Pivot:
    zd: float
    zg: float
    first: Stroke
    last: Stroke
    count: int


@dataclass(frozen=True)
class RepairEvent:
    op: str
    gap: int
    left: Fractal
    right: Fractal
    result: Fractal
    dropped: Fractal | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=200, help="plotted trading days")
    parser.add_argument("--code", default=DEFAULT_CODE, help="board code")
    parser.add_argument(
        "--board-type",
        default=BOARD_TYPE,
        choices=("industry", "concept"),
        help="board universe",
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = parser.parse_args()
    if args.n < WINDOW + MA:
        raise SystemExit(f"--n must be >= {WINDOW + MA}")

    end = args.as_of or date.today()
    start = end - timedelta(days=(args.n + WARMUP) * 3)
    rows = fetch_board_daily_bars_from_db(args.board_type, args.code, start, end)
    if args.as_of is not None:
        rows = [row for row in rows if row["trade_date"] <= args.as_of]
    need = args.n + WARMUP
    if len(rows) < args.n:
        raise SystemExit(
            f"{args.board_type}:{args.code} has {len(rows)} bars ending {end}, need {args.n}"
        )
    rows = rows[-need:]
    name = fetch_board_name(args.board_type, args.code) or args.code

    opens = np.array([float(row["open"]) for row in rows])
    highs = np.array([float(row["high"]) for row in rows])
    lows = np.array([float(row["low"]) for row in rows])
    closes = np.array([float(row["close"]) for row in rows])
    volumes = np.array([float(row["volume"] or 0) for row in rows])
    dates = [row["trade_date"] for row in rows]
    avg = (highs + lows + closes) / 3.0
    smooth = _trailing_ma(avg, MA)
    fractals = find_fractals(smooth, highs, lows)
    repaired, events = alternate_fractals(fractals, highs, lows)
    repaired, endpoint = append_endpoint(repaired, highs, lows)
    strokes = strokes_from_fractals(repaired)
    pivots = find_pivots(strokes)

    plot_start = len(rows) - args.n
    visible = [item for item in repaired if item.index >= plot_start]
    dropped = [
        event.dropped
        for event in events
        if event.dropped is not None and event.dropped.index >= plot_start
    ]
    _setup_font()
    fig = plot_fractals(
        dates[plot_start:],
        opens[plot_start:],
        highs[plot_start:],
        lows[plot_start:],
        closes[plot_start:],
        smooth[plot_start:],
        visible,
        dropped,
        [item for item in strokes if item.end.index >= plot_start],
        pivots,
        volume_profile(
            highs[plot_start:],
            lows[plot_start:],
            closes[plot_start:],
            volumes[plot_start:],
        ),
        origin=plot_start,
        title=f"{name} {args.code}",
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    end_day = dates[-1]
    png = OUT_DIR / f"chan_vol_{args.code}_{end_day}.png"
    fig.savefig(png, dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    tops = sum(1 for item in visible if item.kind == "top")
    bottoms = sum(1 for item in visible if item.kind == "bottom")
    print(
        f"{name} {args.code}  {dates[plot_start]} -> {end_day}  "
        f"n={args.n}  warmup={len(rows) - args.n}"
    )
    shown = [item for item in strokes if item.end.index >= plot_start]
    ups = sum(1 for item in shown if item.direction == "up")
    downs = sum(1 for item in shown if item.direction == "down")
    print(f"交错后 顶分型 {tops}  底分型 {bottoms}  笔 {len(shown)}（上 {ups} / 下 {downs}）")
    if not events:
        print("相邻同类型：无")
    for event in events:
        _print_event(event, dates)
    if endpoint is not None:
        previous = repaired[-2]
        kind = "顶" if endpoint.kind == "top" else "底"
        print(
            f"末端 {kind} 间距 {endpoint.index - previous.index}  "
            f"前一分型 {dates[previous.index]}  "
            f"→ {dates[endpoint.index]} {endpoint.price:.2f}"
        )
    labels = {"insert": "插入", "endpoint": "末端"}
    for item in visible:
        label = "顶" if item.kind == "top" else "底"
        print(
            f"  {label}  {dates[item.index]}  price={item.price:.2f}  "
            f"{labels.get(item.source, '保留')}"
        )
    for item in shown:
        direction = "向上" if item.direction == "up" else "向下"
        print(
            f"  {direction}笔  {dates[item.start.index]} {item.start.price:.2f}"
            f" → {dates[item.end.index]} {item.end.price:.2f}"
            f"  跨 {item.end.index - item.start.index} 根"
        )
    for item in pivots:
        print(
            f"中枢 {item.zd:.2f}–{item.zg:.2f}  "
            f"{dates[item.first.start.index]} → {dates[item.last.end.index]}  "
            f"笔 {item.count}"
        )
    edges, totals = volume_profile(
        highs[plot_start:],
        lows[plot_start:],
        closes[plot_start:],
        volumes[plot_start:],
    )
    peak = int(np.argmax(totals))
    print(
        f"成交量峰值档 {edges[peak]:.2f}–{edges[peak + 1]:.2f}  "
        f"量 {totals[peak]:.0f}  占 {totals[peak] / totals.sum():.1%}"
    )
    raw_levels = volume_group_levels(edges, totals)
    levels = alternate_volume_levels(raw_levels)
    for level in levels:
        name = "最大" if level.kind == "max" else "最小"
        group = level.band // VOLUME_GROUP + 1
        print(
            f"  第{group}组{name}  中价 {level.price:.2f}  "
            f"档 {edges[level.band]:.2f}–{edges[level.band + 1]:.2f}"
        )
    dropped = [item for item in raw_levels if item.band not in {level.band for level in levels}]
    for item in dropped:
        name = "最大" if item.kind == "max" else "最小"
        print(f"  合并去掉 第{item.band // VOLUME_GROUP + 1}组{name}  中价 {item.price:.2f}")
    band = float(edges[1] - edges[0])
    avgs = (highs[plot_start:] + lows[plot_start:] + closes[plot_start:]) / 3.0
    sigma, mean, threshold = avg_return_threshold(avgs)
    raw_important = cluster_important_levels(
        important_level_points(visible, levels, pivots),
        band,
    )
    important = absorb_close_levels(raw_important, threshold)
    keys = key_levels(important, levels, threshold)
    print(
        f"σ={sigma:.4f}  mean={mean:.2f}  th={threshold:.2f}  "
        f"重要线 {len(raw_important)} → {len(important)}  "
        f"关键水平线 {len(keys)}"
    )
    removed = {level.price for level in raw_important} - {level.price for level in important}
    for level in raw_important:
        if level.price in removed:
            print(f"  吸收去掉 {level.price:.2f}  总分 {level.score}")
    for level in keys:
        if level.kind == "vol_min":
            print(
                f"  补入最小量线 {level.price:.2f}  "
                f"成交量 {level.band_volume:.0f}"
            )
            continue
        print(
            f"  {level.price:.2f}  总分 {level.score}  "
            f"点数 {level.count}  中枢 {level.pivot}  "
            f"极值 {level.extreme}  量 {level.volume}"
        )
    print(f"wrote {png}")


def find_fractals(
    smooth: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
) -> list[Fractal]:
    """Map each strict smooth extremum to the same-type raw extreme nearby."""
    found: list[Fractal] = []
    last = len(smooth) - RADIUS
    for center in range(RADIUS, last):
        window = smooth[center - RADIUS : center + RADIUS + 1]
        if np.isnan(window).any():
            continue
        left = window[:RADIUS]
        right = window[RADIUS + 1 :]
        value = window[RADIUS]
        if value > left.max() and value >= right.max():
            offset = int(np.argmax(highs[center - RADIUS : center + RADIUS + 1]))
            index = center - RADIUS + offset
            found.append(
                Fractal("top", index, center, float(highs[index]))
            )
        elif value < left.min() and value <= right.min():
            offset = int(np.argmin(lows[center - RADIUS : center + RADIUS + 1]))
            index = center - RADIUS + offset
            found.append(
                Fractal("bottom", index, center, float(lows[index]))
            )
    return _dedupe(found)


def alternate_fractals(
    fractals: list[Fractal],
    highs: np.ndarray,
    lows: np.ndarray,
) -> tuple[list[Fractal], list[RepairEvent]]:
    """Force top/bottom alternation by merging or inserting."""
    items = list(fractals)
    events: list[RepairEvent] = []
    guard = 0
    while True:
        guard += 1
        if guard > len(fractals) + len(events) + 2:
            raise RuntimeError("same-type repair did not settle")
        pair = _first_same_pair(items)
        if pair is None:
            break
        index, left, right = pair
        gap = right.index - left.index
        if gap > SAME_TYPE_GAP:
            inserted = _insert_between(left, right, highs, lows)
            items.insert(index + 1, inserted)
            events.append(
                RepairEvent("insert", gap, left, right, inserted)
            )
            continue
        kept, loser = _merge_pair(left, right)
        items[index] = kept
        del items[index + 1]
        events.append(RepairEvent("merge", gap, left, right, kept, loser))
    return items, events


def volume_profile(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Bin each bar's volume by where its avg sits in the window's price range.

    The window low-to-high span is split into equal bands. Returns the band
    edges and the volume accumulated in each band.
    """
    avg = (highs + lows + closes) / 3.0
    low = float(lows.min())
    high = float(highs.max())
    if high <= low:
        high = low + 1.0
    edges = np.linspace(low, high, VOLUME_BINS + 1)
    # Interior cuts only, so the top price lands in the last band.
    index = np.digitize(avg, edges[1:-1], right=False)
    totals = np.zeros(VOLUME_BINS, dtype=float)
    for band, volume in zip(index, volumes):
        totals[int(band)] += float(volume)
    return edges, totals


@dataclass(frozen=True)
class VolumeLevel:
    kind: str
    band: int
    price: float
    volume: float


def volume_group_levels(edges: np.ndarray, totals: np.ndarray) -> list[VolumeLevel]:
    """Min and max volume inside each block of consecutive bands.

    Bands run from low price to high price. A short final block is kept.
    The marked price is the midpoint of that band.
    """
    centers = (edges[:-1] + edges[1:]) / 2.0
    levels: list[VolumeLevel] = []
    for start in range(0, len(totals), VOLUME_GROUP):
        block = totals[start : start + VOLUME_GROUP]
        high_at = start + int(np.argmax(block))
        low_at = start + int(np.argmin(block))
        levels.append(
            VolumeLevel("max", high_at, float(centers[high_at]), float(totals[high_at]))
        )
        if low_at != high_at:
            levels.append(
                VolumeLevel("min", low_at, float(centers[low_at]), float(totals[low_at]))
            )
    levels.sort(key=lambda item: item.band)
    return levels


def alternate_volume_levels(levels: list[VolumeLevel]) -> list[VolumeLevel]:
    """Collapse adjacent same-kind levels, keeping the more extreme volume."""
    kept: list[VolumeLevel] = []
    for level in levels:
        if not kept or kept[-1].kind != level.kind:
            kept.append(level)
            continue
        kept[-1] = _more_extreme_volume(kept[-1], level)
    return kept


def _more_extreme_volume(left: VolumeLevel, right: VolumeLevel) -> VolumeLevel:
    if left.kind == "max":
        return right if right.volume > left.volume else left
    return right if right.volume < left.volume else left


@dataclass(frozen=True)
class LevelPoint:
    price: float
    role: str


@dataclass(frozen=True)
class ImportantLevel:
    price: float
    score: int
    count: int
    pivot: int
    extreme: int
    volume: int


@dataclass(frozen=True)
class KeyLevel:
    """A horizontal line kept on the candle chart.

    ``kind`` is ``cluster`` for a line that survived absorption, or ``vol_min``
    for a volume-minimum line added because it sits more than th/3 away.
    """

    price: float
    kind: str
    score: int | None = None
    count: int = 0
    pivot: int = 0
    extreme: int = 0
    volume: int = 0
    band_volume: float | None = None


def important_level_points(
    fractals: list[Fractal],
    levels: list[VolumeLevel],
    pivots: list[Pivot],
) -> list[LevelPoint]:
    points = [LevelPoint(item.price, "price") for item in fractals]
    points.extend(
        LevelPoint(level.price, "vol_max" if level.kind == "max" else "vol_min")
        for level in levels
    )
    for pivot in pivots:
        points.append(LevelPoint(pivot.zd, "pivot"))
        points.append(LevelPoint(pivot.zg, "pivot"))
    return points


def cluster_important_levels(
    points: list[LevelPoint],
    width: float,
) -> list[ImportantLevel]:
    """Complete-linkage clusters no wider than one band, scored as agreed."""
    ordered = sorted(points, key=lambda item: item.price)
    if not ordered:
        return []
    clusters: list[list[LevelPoint]] = [[point] for point in ordered]
    while len(clusters) > 1:
        gaps = [
            clusters[index + 1][-1].price - clusters[index][0].price
            for index in range(len(clusters) - 1)
        ]
        nearest = int(np.argmin(gaps))
        if gaps[nearest] > width:
            break
        clusters[nearest] = clusters[nearest] + clusters[nearest + 1]
        del clusters[nearest + 1]
    lowest = ordered[0].price
    highest = ordered[-1].price
    scored: list[ImportantLevel] = []
    for group in clusters:
        roles = {point.role for point in group}
        count = len(group)
        pivot_score = 2 if "pivot" in roles else 0
        extreme_score = 2 if any(point.price in (lowest, highest) for point in group) else 0
        volume_score = (1 if "vol_max" in roles else 0) + (2 if "vol_min" in roles else 0)
        scored.append(
            ImportantLevel(
                float(np.median([point.price for point in group])),
                count + pivot_score + extreme_score + volume_score,
                count,
                pivot_score,
                extreme_score,
                volume_score,
            )
        )
    return scored


def avg_return_threshold(avgs: np.ndarray) -> tuple[float, float, float]:
    """RMS of avg returns, the window mean, and th = 3σ × mean."""
    if len(avgs) < 2:
        mean = float(avgs[0]) if len(avgs) else 0.0
        return 0.0, mean, 0.0
    previous = avgs[:-1]
    usable = previous != 0
    if not np.any(usable):
        return 0.0, float(np.mean(avgs)), 0.0
    returns = (avgs[1:][usable] - previous[usable]) / previous[usable]
    sigma = float(np.sqrt(np.mean(np.square(returns))))
    mean = float(np.mean(avgs))
    return sigma, mean, 3.0 * sigma * mean


def absorb_close_levels(
    levels: list[ImportantLevel],
    threshold: float,
) -> list[ImportantLevel]:
    """Drop the lower-scored line when two survivors are closer than th."""
    kept: list[ImportantLevel] = []
    for level in sorted(levels, key=lambda item: item.price):
        kept.append(level)
        while len(kept) >= 2 and kept[-1].price - kept[-2].price < threshold:
            if kept[-1].score > kept[-2].score:
                del kept[-2]
            else:
                del kept[-1]
                break
    return kept


def key_levels(
    important: list[ImportantLevel],
    volume_levels: list[VolumeLevel],
    threshold: float,
) -> list[KeyLevel]:
    """Key lines are the absorbed important lines, plus distant volume minima.

    A volume-minimum line is added when its distance to the nearest surviving
    important line is greater than th/3. Added lines are not compared with
    each other, only with those surviving lines.
    """
    keys = [
        KeyLevel(
            price=level.price,
            kind="cluster",
            score=level.score,
            count=level.count,
            pivot=level.pivot,
            extreme=level.extreme,
            volume=level.volume,
        )
        for level in important
    ]
    anchors = [level.price for level in important]
    gap = threshold / 3.0
    for level in volume_levels:
        if level.kind != "min":
            continue
        if anchors and min(abs(level.price - price) for price in anchors) <= gap:
            continue
        keys.append(
            KeyLevel(
                price=level.price,
                kind="vol_min",
                band_volume=level.volume,
            )
        )
    keys.sort(key=lambda item: item.price)
    return keys


def strokes_from_fractals(fractals: list[Fractal]) -> list[Stroke]:
    """A stroke is the segment joining two adjacent, opposite fractals."""
    strokes: list[Stroke] = []
    for start, end in zip(fractals, fractals[1:]):
        direction = "up" if start.kind == "bottom" else "down"
        strokes.append(Stroke(direction, start, end))
    return strokes


def find_pivots(strokes: list[Stroke]) -> list[Pivot]:
    """Stroke pivots: overlap of three consecutive strokes, then extension.

    ZG and ZD stay fixed at the first three strokes. A later stroke extends
    the pivot while its price range still meets [ZD, ZG]. The next pivot must
    sit entirely above or entirely below the previous one.
    """
    pivots: list[Pivot] = []
    index = 0
    count = len(strokes)
    while index <= count - 3:
        zone = _overlap_zone(strokes[index : index + 3])
        if zone is None:
            index += 1
            continue
        zd, zg = zone
        if pivots and _ranges_overlap(zd, zg, pivots[-1]):
            index += 1
            continue
        last = index + 2
        cursor = index + 3
        while cursor < count and _stroke_meets(strokes[cursor], zd, zg):
            last = cursor
            cursor += 1
        pivots.append(
            Pivot(zd, zg, strokes[index], strokes[last], last - index + 1)
        )
        index = last + 1
    return pivots


def _stroke_bounds(stroke: Stroke) -> tuple[float, float]:
    return (
        min(stroke.start.price, stroke.end.price),
        max(stroke.start.price, stroke.end.price),
    )


def _overlap_zone(strokes: list[Stroke]) -> tuple[float, float] | None:
    lows, highs = zip(*(_stroke_bounds(item) for item in strokes))
    zd = max(lows)
    zg = min(highs)
    if zg > zd:
        return zd, zg
    return None


def _stroke_meets(stroke: Stroke, zd: float, zg: float) -> bool:
    low, high = _stroke_bounds(stroke)
    return low < zg and high > zd


def _ranges_overlap(zd: float, zg: float, pivot: Pivot) -> bool:
    return zd < pivot.zg and zg > pivot.zd


def append_endpoint(
    fractals: list[Fractal],
    highs: np.ndarray,
    lows: np.ndarray,
) -> tuple[list[Fractal], Fractal | None]:
    """Treat the last bar as the opposite fractal when it sits far enough out."""
    if not fractals:
        return fractals, None
    previous = fractals[-1]
    end = len(highs) - 1
    if end - previous.index < ENDPOINT_GAP:
        return fractals, None
    if previous.kind == "top":
        added = Fractal("bottom", end, end, float(lows[end]), "endpoint")
    else:
        added = Fractal("top", end, end, float(highs[end]), "endpoint")
    return [*fractals, added], added


def _first_same_pair(
    items: list[Fractal],
) -> tuple[int, Fractal, Fractal] | None:
    for index in range(len(items) - 1):
        left, right = items[index], items[index + 1]
        if left.kind == right.kind:
            return index, left, right
    return None


def _merge_pair(left: Fractal, right: Fractal) -> tuple[Fractal, Fractal]:
    if left.kind == "top":
        return (left, right) if left.price >= right.price else (right, left)
    return (left, right) if left.price <= right.price else (right, left)


def _insert_between(
    left: Fractal,
    right: Fractal,
    highs: np.ndarray,
    lows: np.ndarray,
) -> Fractal:
    start = left.index + 1
    stop = right.index
    if left.kind == "top":
        offset = int(np.argmin(lows[start:stop]))
        index = start + offset
        return Fractal("bottom", index, index, float(lows[index]), "insert")
    offset = int(np.argmax(highs[start:stop]))
    index = start + offset
    return Fractal("top", index, index, float(highs[index]), "insert")


def _print_event(event: RepairEvent, dates: list[date]) -> None:
    kind = "顶" if event.left.kind == "top" else "底"
    if event.op == "merge" and event.dropped is not None:
        print(
            f"合并 {kind} 间距 {event.gap}  "
            f"{dates[event.left.index]} {event.left.price:.2f} / "
            f"{dates[event.right.index]} {event.right.price:.2f}  "
            f"→ 保留 {dates[event.result.index]} {event.result.price:.2f}"
        )
        return
    opposite = "顶" if event.result.kind == "top" else "底"
    print(
        f"插入 {opposite} 间距 {event.gap}  "
        f"位于两个{kind} {dates[event.left.index]} 与 {dates[event.right.index]} 之间  "
        f"→ {dates[event.result.index]} {event.result.price:.2f}"
    )


def _dedupe(found: list[Fractal]) -> list[Fractal]:
    """One fractal per bar. Keep the detection closer to the smooth extremum."""
    best: dict[tuple[str, int], Fractal] = {}
    for item in found:
        key = (item.kind, item.index)
        current = best.get(key)
        if current is None or abs(item.index - item.smooth_index) < abs(
            current.index - current.smooth_index
        ):
            best[key] = item
    return sorted(best.values(), key=lambda item: (item.index, item.kind))


def _trailing_ma(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) < window:
        return out
    cum = np.cumsum(values)
    out[window - 1 :] = (cum[window - 1 :] - np.concatenate(([0.0], cum[:-window]))) / window
    return out


def plot_fractals(
    dates: list[date],
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    smooth: np.ndarray,
    fractals: list[Fractal],
    dropped: list[Fractal],
    strokes: list[Stroke],
    pivots: list[Pivot],
    profile: tuple[np.ndarray, np.ndarray],
    *,
    origin: int,
    title: str,
) -> plt.Figure:
    x = np.arange(len(dates))
    fig, (ax, ax_vol) = plt.subplots(
        1,
        2,
        figsize=(20.4, 6.4),
        sharey=True,
        gridspec_kw={"width_ratios": [5.4, 1.25]},
        layout="constrained",
    )
    fig.patch.set_facecolor("white")
    _draw_pivots(ax, pivots, origin, len(dates))
    _draw_candles(ax, x, opens, highs, lows, closes)
    ax.plot(x, smooth, color="#64748b", lw=1.0, label="MA5(avg)", zorder=3)
    _draw_strokes(ax, strokes, origin)
    levels = alternate_volume_levels(volume_group_levels(*profile))
    _draw_volume_profile(ax_vol, profile, levels)
    band = float(profile[0][1] - profile[0][0])
    avgs = (highs + lows + closes) / 3.0
    _sigma, _mean, threshold = avg_return_threshold(avgs)
    keys = key_levels(
        absorb_close_levels(
            cluster_important_levels(
                important_level_points(fractals, levels, pivots),
                band,
            ),
            threshold,
        ),
        levels,
        threshold,
    )
    _draw_key_levels(ax, keys, len(dates))

    span = float(highs.max() - lows.min())
    pad = span * 0.018
    kept_tops = [item for item in fractals if item.kind == "top" and item.source == "raw"]
    kept_bottoms = [
        item for item in fractals if item.kind == "bottom" and item.source == "raw"
    ]
    endpoints = [item for item in fractals if item.source == "endpoint"]
    inserted_tops = [item for item in fractals if item.kind == "top" and item.source == "insert"]
    inserted_bottoms = [
        item for item in fractals if item.kind == "bottom" and item.source == "insert"
    ]
    if kept_tops:
        ax.scatter(
            [item.index - origin for item in kept_tops],
            [item.price + pad for item in kept_tops],
            marker="v",
            s=36,
            c="#1d4ed8",
            zorder=5,
            label=f"顶分型 {len(kept_tops)}",
        )
    if kept_bottoms:
        ax.scatter(
            [item.index - origin for item in kept_bottoms],
            [item.price - pad for item in kept_bottoms],
            marker="^",
            s=36,
            c="#c2410c",
            zorder=5,
            label=f"底分型 {len(kept_bottoms)}",
        )
    if inserted_tops or inserted_bottoms:
        inserted = inserted_tops + inserted_bottoms
        ax.scatter(
            [item.index - origin for item in inserted],
            [
                item.price + pad if item.kind == "top" else item.price - pad
                for item in inserted
            ],
            marker="D",
            s=32,
            c="#7c3aed",
            zorder=6,
            label=f"插入 {len(inserted)}",
        )
    if endpoints:
        ax.scatter(
            [item.index - origin for item in endpoints],
            [
                item.price + pad if item.kind == "top" else item.price - pad
                for item in endpoints
            ],
            marker="s",
            s=36,
            c="#111827",
            zorder=6,
            label=f"末端分型 {len(endpoints)}",
        )
    if dropped:
        ax.scatter(
            [item.index - origin for item in dropped],
            [
                item.price + pad if item.kind == "top" else item.price - pad
                for item in dropped
            ],
            marker="x",
            s=42,
            c="#94a3b8",
            zorder=4,
            label=f"合并去掉 {len(dropped)}",
        )

    step = 20
    tick_idx = list(range(0, len(dates), step))
    if tick_idx[-1] != len(dates) - 1:
        tick_idx.append(len(dates) - 1)
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([dates[i].strftime("%Y-%m-%d") for i in tick_idx], rotation=0)
    ax.set_xlim(-1, len(dates))
    ax.set_ylabel("价格")
    ax.grid(True, axis="y", color="#e7e5e4", lw=0.6)
    ax.legend(loc="upper left", frameon=False, fontsize=9, ncol=4)
    low = float(min(lows))
    high = float(max(highs))
    pad = (high - low) * 0.04
    ax.set_ylim(low - pad, high + pad)
    _draw_threshold(ax, threshold, low)
    ax.set_title(
        f"{title}  最近 {len(dates)} 个交易日   {dates[0]} — {dates[-1]}\n"
        "15 档按 4 档一组；同类极值相邻时合并，只留更极端的一档",
        fontsize=12,
        loc="left",
    )
    return fig


def _draw_threshold(ax: plt.Axes, threshold: float, low: float) -> None:
    """Draw a vertical segment whose length is the absorption distance th."""
    from matplotlib.transforms import blended_transform_factory

    transform = blended_transform_factory(ax.transAxes, ax.transData)
    y0 = low
    y1 = low + threshold
    ax.plot(
        [0.015, 0.015],
        [y0, y1],
        transform=transform,
        color="#0f172a",
        lw=2.4,
        solid_capstyle="butt",
        zorder=8,
        clip_on=False,
    )
    ax.plot(
        [0.008, 0.022],
        [y0, y0],
        transform=transform,
        color="#0f172a",
        lw=1.4,
        zorder=8,
        clip_on=False,
    )
    ax.plot(
        [0.008, 0.022],
        [y1, y1],
        transform=transform,
        color="#0f172a",
        lw=1.4,
        zorder=8,
        clip_on=False,
    )
    ax.text(
        0.028,
        (y0 + y1) / 2.0,
        f"th {threshold:.0f}",
        transform=transform,
        va="center",
        ha="left",
        fontsize=8,
        color="#0f172a",
        zorder=8,
        clip_on=False,
    )


def _draw_volume_profile(
    ax: plt.Axes,
    profile: tuple[np.ndarray, np.ndarray],
    levels: list[VolumeLevel],
) -> None:
    edges, totals = profile
    centers = (edges[:-1] + edges[1:]) / 2.0
    height = float(edges[1] - edges[0]) * 0.9
    colors = np.full(len(totals), "#cbd5e1")
    for level in levels:
        colors[level.band] = "#1d4ed8" if level.kind == "max" else "#b45309"
    ax.barh(centers, totals, height=height, color=colors, zorder=2)
    ax.set_xlabel("成交量")
    ax.set_title("均价所在档", fontsize=11, loc="left")
    ax.grid(True, axis="x", color="#e7e5e4", lw=0.6)
    ax.ticklabel_format(axis="x", style="sci", scilimits=(0, 0))
    ax.tick_params(axis="y", left=False, labelleft=False)


def _draw_key_levels(ax: plt.Axes, levels: list[KeyLevel], n: int) -> None:
    labeled = False
    for level in levels:
        ax.axhline(
            level.price,
            color="#0f172a",
            linestyle="-.",
            lw=2.2,
            zorder=4,
            label="关键水平线" if not labeled else None,
        )
        labeled = True
        if level.score is None:
            continue
        ax.text(
            n - 0.6,
            level.price,
            str(level.score),
            ha="right",
            va="center",
            fontsize=8,
            color="#0f172a",
            zorder=7,
            bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.4, "alpha": 0.85},
        )


def _draw_pivots(ax: plt.Axes, pivots: list[Pivot], origin: int, n: int) -> None:
    colors = ("#2563eb", "#d97706", "#059669", "#7c3aed")
    for index, pivot in enumerate(pivots):
        x0 = pivot.first.start.index - origin
        x1 = pivot.last.end.index - origin
        if x1 < 0 or x0 > n - 1:
            continue
        x0 = max(x0, -0.5)
        x1 = min(x1, n - 0.5)
        color = colors[index % len(colors)]
        ax.add_patch(
            plt.Rectangle(
                (x0, pivot.zd),
                x1 - x0,
                pivot.zg - pivot.zd,
                facecolor=color,
                edgecolor=color,
                alpha=0.16,
                lw=1.0,
                zorder=0,
                label=f"中枢{index + 1} {pivot.zd:.0f}–{pivot.zg:.0f}",
            )
        )


def _draw_strokes(ax: plt.Axes, strokes: list[Stroke], origin: int) -> None:
    colors = {"up": "#1d4ed8", "down": "#c2410c"}
    counts = {
        "up": sum(1 for item in strokes if item.direction == "up"),
        "down": sum(1 for item in strokes if item.direction == "down"),
    }
    labeled: set[str] = set()
    for item in strokes:
        label = None
        if item.direction not in labeled:
            name = "向上笔" if item.direction == "up" else "向下笔"
            label = f"{name} {counts[item.direction]}"
            labeled.add(item.direction)
        ax.plot(
            [item.start.index - origin, item.end.index - origin],
            [item.start.price, item.end.price],
            color=colors[item.direction],
            lw=1.5,
            zorder=4,
            solid_capstyle="round",
            label=label,
        )


def _draw_candles(
    ax: plt.Axes,
    x: np.ndarray,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
) -> None:
    width = 0.62
    up = closes >= opens
    for i in range(len(x)):
        color = "#b91c1c" if up[i] else "#15803d"
        ax.vlines(x[i], lows[i], highs[i], color=color, linewidth=0.6, zorder=2)
        body_low = min(opens[i], closes[i])
        body_height = abs(closes[i] - opens[i])
        if body_height == 0:
            ax.hlines(
                opens[i],
                x[i] - width / 2,
                x[i] + width / 2,
                color=color,
                linewidth=0.8,
                zorder=2,
            )
            continue
        ax.add_patch(
            plt.Rectangle(
                (x[i] - width / 2, body_low),
                width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.3,
                zorder=2,
            )
        )


@dataclass
class ChanWindow:
    """Visible chan chart plus the warmup bars its fractals were measured on."""

    timeline: list
    dates: list
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    smooth: np.ndarray
    fractals: list[Fractal]
    dropped: list[Fractal]
    strokes: list[Stroke]
    pivots: list[Pivot]
    profile: tuple[np.ndarray, np.ndarray]
    origin: int


def prepare_chan_window(rows: list[dict], *, n: int = 200) -> ChanWindow:
    """Last ``n`` bars, with up to ``WARMUP`` earlier bars kept for MA5 and fractals."""
    if n < 1:
        raise ValueError("n must be >= 1")
    plotted = min(n, len(rows))
    if plotted < 1:
        raise ValueError("no bars")
    keep = plotted + min(WARMUP, len(rows) - plotted)
    rows = rows[-keep:]
    opens = np.array([float(row["open"]) for row in rows])
    highs = np.array([float(row["high"]) for row in rows])
    lows = np.array([float(row["low"]) for row in rows])
    closes = np.array([float(row["close"]) for row in rows])
    volumes = np.array([float(row["volume"] or 0) for row in rows])
    timeline = [row["trade_date"] for row in rows]
    avg = (highs + lows + closes) / 3.0
    smooth = _trailing_ma(avg, MA)
    fractals = find_fractals(smooth, highs, lows)
    repaired, events = alternate_fractals(fractals, highs, lows)
    repaired, _endpoint = append_endpoint(repaired, highs, lows)
    strokes = strokes_from_fractals(repaired)
    pivots = find_pivots(strokes)
    plot_start = len(rows) - plotted
    visible_slice = slice(plot_start, None)
    return ChanWindow(
        timeline=timeline,
        dates=timeline[plot_start:],
        opens=opens[visible_slice],
        highs=highs[visible_slice],
        lows=lows[visible_slice],
        closes=closes[visible_slice],
        smooth=smooth[visible_slice],
        fractals=[item for item in repaired if item.index >= plot_start],
        dropped=[
            event.dropped
            for event in events
            if event.dropped is not None and event.dropped.index >= plot_start
        ],
        strokes=[item for item in strokes if item.end.index >= plot_start],
        pivots=pivots,
        profile=volume_profile(
            highs[visible_slice],
            lows[visible_slice],
            closes[visible_slice],
            volumes[visible_slice],
        ),
        origin=plot_start,
    )


def render_chan_png(rows: list[dict], *, title: str, n: int = 200) -> bytes:
    """PNG of the chan board chart. ``rows`` may include warmup bars before ``n``."""
    window = prepare_chan_window(rows, n=n)
    _setup_font()
    fig = plot_fractals(
        window.dates,
        window.opens,
        window.highs,
        window.lows,
        window.closes,
        window.smooth,
        window.fractals,
        window.dropped,
        window.strokes,
        window.pivots,
        window.profile,
        origin=window.origin,
        title=title,
    )
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()


def _setup_font() -> None:
    for fname in ("PingFang SC", "Heiti SC", "Arial Unicode MS", "Noto Sans CJK SC"):
        if any(fname in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.sans-serif"] = [fname]
            break
    plt.rcParams["axes.unicode_minus"] = False


if __name__ == "__main__":
    main()
