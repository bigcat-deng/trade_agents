"""Chan structure chart for a board K-line page.

The visible window is at most 200 trading days ending on the page's end date.
Fewer bars are drawn when history is shorter. A few earlier bars stay in the
series only so the moving average and fractals are warmed up.

The page chart is Plotly, so a hover shows the price, stroke, pivot, or score
under the pointer. The offline probe still writes the same figure as a PNG.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Mapping, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from scripts.chan_fractal_probe import (
    Fractal,
    KeyLevel,
    VolumeLevel,
    WARMUP,
    absorb_close_levels,
    alternate_volume_levels,
    avg_return_threshold,
    cluster_important_levels,
    important_level_points,
    key_levels,
    prepare_chan_window,
    volume_group_levels,
)

WINDOW = 200

_PIVOT_COLORS = ("#2563eb", "#d97706", "#059669", "#7c3aed")
_FONT = "PingFang SC, Noto Sans SC, sans-serif"
_PLAN_LINES = (
    ("target", "目标", "rgba(185, 28, 28, 0.5)"),
    ("buy", "买点", "rgba(37, 99, 235, 0.5)"),
    ("stop", "止损", "rgba(21, 128, 61, 0.5)"),
)


def chan_fetch_start(end: date, *, n: int = WINDOW) -> date:
    """Calendar start that covers ``n`` trading days plus fractal warmup."""
    return end - timedelta(days=(n + WARMUP) * 3)


def render_chan_board_html(
    rows: Sequence[Mapping[str, Any]],
    *,
    title: str,
    n: int = WINDOW,
    include_plotlyjs: bool | str = "cdn",
    plan_lines: bool = False,
) -> tuple[str, date, date, int, dict | None]:
    """Return Plotly HTML, visible start, visible end, length, and plan prices.

    Plan prices are present only when the target, buy, and stop lines are drawn.
    """
    window = prepare_chan_window(list(rows), n=n)
    figure, plan = build_chan_figure(window, title=title, plan_lines=plan_lines)
    html = figure.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        config={"displayModeBar": False, "scrollZoom": False},
    )
    start = window.dates[0]
    end = window.dates[-1]
    return html, start, end, len(window.dates), plan


def drawn_key_levels(window) -> list[KeyLevel]:
    """Important lines drawn on the Chan chart for this window."""
    levels = alternate_volume_levels(volume_group_levels(*window.profile))
    avgs = (window.highs + window.lows + window.closes) / 3.0
    _sigma, _mean, threshold = avg_return_threshold(avgs)
    band = float(window.profile[0][1] - window.profile[0][0])
    return key_levels(
        absorb_close_levels(
            cluster_important_levels(
                important_level_points(window.fractals, levels, window.pivots),
                band,
            ),
            threshold,
        ),
        levels,
        threshold,
    )


def build_chan_figure(window, *, title: str, plan_lines: bool = False):
    dates = window.dates
    keys = drawn_key_levels(window)
    plan = _chart_plan(window, keys) if plan_lines else None
    levels = alternate_volume_levels(volume_group_levels(*window.profile))
    avgs = (window.highs + window.lows + window.closes) / 3.0
    sigma, mean, threshold = avg_return_threshold(avgs)
    span = float(window.highs.max() - window.lows.min())
    pad = span * 0.018 if span else 0.0

    figure = make_subplots(
        rows=2,
        cols=2,
        shared_xaxes=True,
        shared_yaxes=True,
        column_widths=[0.81, 0.19],
        row_heights=[0.76, 0.24],
        horizontal_spacing=0.03,
        vertical_spacing=0.03,
        specs=[[{}, {}], [{}, None]],
    )
    _add_pivots(figure, window)
    _add_candles(figure, window)
    _add_smooth(figure, window)
    _add_strokes(figure, window)
    _add_key_levels(figure, window, keys)
    if plan is not None and plan.target is not None:
        _add_plan_lines(figure, window, plan)
    _add_fractals(figure, window, pad)
    _add_volume_profile(figure, window, levels)
    _add_daily_volume(figure, window)
    _add_threshold(figure, threshold, sigma, mean, float(window.lows.min()))

    low = float(window.lows.min())
    high = float(window.highs.max())
    plan_prices = _plan_prices(plan)
    bound_low = min([low, *plan_prices]) if plan_prices else low
    bound_high = max([high, *plan_prices]) if plan_prices else high
    y_pad = (high - low) * 0.04 if high > low else 1.0
    y_top = max(bound_high + y_pad, low + threshold)
    figure.update_yaxes(
        title_text="价格", range=[bound_low - y_pad, y_top], row=1, col=1
    )
    figure.update_yaxes(showticklabels=False, row=1, col=2)
    figure.update_yaxes(title_text="成交量", exponentformat="e", row=2, col=1)
    x_range = _xaxis_range(dates)
    figure.update_xaxes(
        rangeslider_visible=False,
        range=x_range,
        showticklabels=False,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikecolor="#a8a29e",
        row=1,
        col=1,
    )
    figure.update_xaxes(
        rangeslider_visible=False,
        tickformat="%Y-%m-%d",
        range=x_range,
        row=2,
        col=1,
    )
    figure.update_xaxes(
        title_text="成交量",
        exponentformat="e",
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        row=1,
        col=2,
    )
    figure.update_layout(
        title=dict(
            text=(
                f"{title}  最近 {len(dates)} 个交易日   {dates[0]} — {dates[-1]}"
            ),
            x=0,
            xanchor="left",
            xref="container",
            y=1,
            yanchor="top",
            font=dict(size=15),
            pad=dict(t=8, b=0),
        ),
        font=dict(family=_FONT, size=12),
        hovermode="closest",
        hoverdistance=24,
        hoverlabel=dict(bgcolor="white", font=dict(family=_FONT, size=12)),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=1.12,
            x=0,
            xanchor="left",
            font=dict(size=11),
        ),
        margin=dict(t=118, l=64, r=24, b=48),
        height=860,
        paper_bgcolor="white",
        plot_bgcolor="white",
        bargap=0.08,
        xaxis4=dict(
            overlaying="x",
            range=[0, 1],
            showgrid=False,
            zeroline=False,
            showticklabels=False,
            visible=False,
            anchor="y",
            fixedrange=True,
        ),
    )
    figure.add_annotation(
        text="均价所在档",
        xref="x2 domain",
        yref="paper",
        x=0,
        y=1.0,
        yshift=8,
        showarrow=False,
        xanchor="left",
        font=dict(size=13, family=_FONT),
    )
    return figure, _plan_caption(plan)


def chan_xaxis_range(start: date, end: date, n: int) -> list[datetime]:
    """Same padded x-range as the Chan figure for a window of ``n`` bars."""
    if n < 1:
        return []
    if n == 1 or start == end:
        pad = timedelta(days=2)
    else:
        step = (end - start).days / (n - 1)
        pad = timedelta(days=max(step * 1.5, 1.5))
    return [
        datetime.combine(start, time.min) - pad,
        datetime.combine(end, time.min) + pad,
    ]


def _xaxis_range(dates: Sequence[date]) -> list[datetime]:
    """Leave half a bar on each side so the first and last candles stay whole."""
    if not dates:
        return []
    return chan_xaxis_range(dates[0], dates[-1], len(dates))


def _day(window, index: int):
    index = min(max(index, 0), len(window.timeline) - 1)
    return window.timeline[index]


def _add_candles(figure: go.Figure, window) -> None:
    figure.add_trace(
        go.Candlestick(
            x=window.dates,
            open=window.opens,
            high=window.highs,
            low=window.lows,
            close=window.closes,
            name="K线",
            increasing=dict(line=dict(color="#b91c1c", width=1), fillcolor="#b91c1c"),
            decreasing=dict(line=dict(color="#15803d", width=1), fillcolor="#15803d"),
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>"
                "开盘 %{open:.2f}<br>"
                "最高 %{high:.2f}<br>"
                "最低 %{low:.2f}<br>"
                "收盘 %{close:.2f}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )


def _add_smooth(figure: go.Figure, window) -> None:
    figure.add_trace(
        go.Scatter(
            x=window.dates,
            y=window.smooth,
            name="MA5(avg)",
            mode="lines",
            line=dict(color="#64748b", width=1.2),
            connectgaps=False,
            hovertemplate="%{x|%Y-%m-%d}<br>MA5(avg) %{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )


def _add_strokes(figure: go.Figure, window) -> None:
    counts = {
        "up": sum(1 for item in window.strokes if item.direction == "up"),
        "down": sum(1 for item in window.strokes if item.direction == "down"),
    }
    labeled: set[str] = set()
    colors = {"up": "#1d4ed8", "down": "#c2410c"}
    for item in window.strokes:
        name = "向上笔" if item.direction == "up" else "向下笔"
        show = item.direction not in labeled
        labeled.add(item.direction)
        text = (
            f"{name}<br>"
            f"{_day(window, item.start.index)}  {_fmt(item.start.price)}"
            f" → {_day(window, item.end.index)}  {_fmt(item.end.price)}"
        )
        figure.add_trace(
            go.Scatter(
                x=[_day(window, item.start.index), _day(window, item.end.index)],
                y=[item.start.price, item.end.price],
                name=f"{name} {counts[item.direction]}",
                mode="lines",
                line=dict(color=colors[item.direction], width=1.6),
                hovertemplate=text + "<extra></extra>",
                showlegend=show,
            ),
            row=1,
            col=1,
        )


def _add_pivots(figure: go.Figure, window) -> None:
    last = window.origin + len(window.dates) - 1
    for index, pivot in enumerate(window.pivots):
        x0 = pivot.first.start.index
        x1 = pivot.last.end.index
        if x1 < window.origin or x0 > last:
            continue
        left = _day(window, max(x0, window.origin))
        right = _day(window, min(x1, last))
        color = _PIVOT_COLORS[index % len(_PIVOT_COLORS)]
        text = (
            f"中枢{index + 1}<br>"
            f"{_day(window, x0)} → {_day(window, x1)}<br>"
            f"ZD {_fmt(pivot.zd)}<br>"
            f"ZG {_fmt(pivot.zg)}<br>"
            f"{pivot.count} 笔"
        )
        figure.add_trace(
            go.Scatter(
                x=[left, right, right, left, left],
                y=[pivot.zd, pivot.zd, pivot.zg, pivot.zg, pivot.zd],
                name=f"中枢{index + 1} {pivot.zd:.0f}–{pivot.zg:.0f}",
                mode="lines",
                fill="toself",
                fillcolor=_rgba(color, 0.16),
                line=dict(color=color, width=1),
                hovertemplate=text + "<extra></extra>",
            ),
            row=1,
            col=1,
        )


def _add_fractals(figure: go.Figure, window, pad: float) -> None:
    groups = (
        ("顶分型", "top", "raw", "triangle-down", "#1d4ed8", pad),
        ("底分型", "bottom", "raw", "triangle-up", "#c2410c", -pad),
        ("插入", None, "insert", "diamond", "#7c3aed", None),
        ("末端分型", None, "endpoint", "square", "#111827", None),
    )
    for label, kind, source, symbol, color, offset in groups:
        items = [
            item
            for item in window.fractals
            if item.source == source and (kind is None or item.kind == kind)
        ]
        if not items:
            continue
        ys = []
        for item in items:
            shift = offset
            if shift is None:
                shift = pad if item.kind == "top" else -pad
            ys.append(item.price + shift)
        figure.add_trace(
            go.Scatter(
                x=[_day(window, item.index) for item in items],
                y=ys,
                name=f"{label} {len(items)}",
                mode="markers",
                marker=dict(symbol=symbol, size=9, color=color),
                customdata=[
                    [_kind_label(item), _fmt(item.price)] for item in items
                ],
                hovertemplate=(
                    "%{customdata[0]}<br>%{x|%Y-%m-%d}<br>价格 %{customdata[1]}<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )
    if window.dropped:
        figure.add_trace(
            go.Scatter(
                x=[_day(window, item.index) for item in window.dropped],
                y=[
                    item.price + (pad if item.kind == "top" else -pad)
                    for item in window.dropped
                ],
                name=f"合并去掉 {len(window.dropped)}",
                mode="markers",
                marker=dict(symbol="x", size=9, color="#94a3b8"),
                customdata=[
                    [_kind_label(item), _fmt(item.price)] for item in window.dropped
                ],
                hovertemplate=(
                    "合并去掉 %{customdata[0]}<br>%{x|%Y-%m-%d}<br>"
                    "价格 %{customdata[1]}<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )


def _add_key_levels(figure: go.Figure, window, levels: list[KeyLevel]) -> None:
    x0, x1 = window.dates[0], window.dates[-1]
    labeled = False
    for level in levels:
        if level.kind == "vol_min":
            hover = (
                "关键水平线 %{y:.2f}<br>"
                f"交易量最小线<br>成交量 {_fmt(level.band_volume or 0, 0)}<extra></extra>"
            )
        else:
            hover = (
                "关键水平线 %{y:.2f}<br>"
                f"总分 {level.score}<br>"
                f"聚类 {level.count}　中枢 {level.pivot}"
                f"　极值 {level.extreme}　量分 {level.volume}<extra></extra>"
            )
        figure.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[level.price, level.price],
                name="关键水平线",
                mode="lines",
                line=dict(color="#0f172a", width=2.4, dash="dashdot"),
                hovertemplate=hover,
                showlegend=not labeled,
            ),
            row=1,
            col=1,
        )
        labeled = True
        if level.score is None:
            continue
        figure.add_annotation(
            x=x1,
            y=level.price,
            text=str(level.score),
            showarrow=False,
            xanchor="right",
            yanchor="middle",
            font=dict(size=11, color="#0f172a", family=_FONT),
            bgcolor="rgba(255,255,255,0.88)",
            borderpad=1,
        )


def _chart_plan(window, levels: list[KeyLevel]):
    """Target, buy, and stop for the last visible bar. None when lines are short."""
    from app.levels.target_stop import target_stop_plan

    try:
        return target_stop_plan(
            [level.price for level in levels],
            high=float(window.highs[-1]),
            low=float(window.lows[-1]),
            close=float(window.closes[-1]),
        )
    except ValueError:
        return None


def _plan_caption(plan) -> dict | None:
    """Plan prices plus the return and loss of buying at the current close.

    Target and stop stay as drawn. Yield is ``(target − close) / close`` and
    loss is ``(close − stop) / close``. Ratio is reward∶risk as ``x : 1``.
    """
    if plan is None or plan.target is None or plan.buy is None or plan.stop is None:
        return None
    close = float(plan.close)
    return {
        "target": f"{plan.target:.2f}",
        "buy": f"{plan.buy:.2f}",
        "stop": f"{plan.stop:.2f}",
        "close": f"{close:.2f}",
        "yield_rate": _percent((plan.target - close) / close) if close else "—",
        "loss_rate": _percent((close - plan.stop) / close) if close else "—",
        "ratio": "—" if plan.ratio is None else f"{plan.ratio:.2f} : 1",
    }


def _percent(ratio: float) -> str:
    return f"{ratio * 100:.2f}%"


def _plan_prices(plan) -> list[float]:
    if plan is None or plan.target is None:
        return []
    return [price for price in (plan.target, plan.buy, plan.stop) if price is not None]


def _add_plan_lines(figure: go.Figure, window, plan) -> None:
    x0, x1 = window.dates[0], window.dates[-1]
    for attr, label, color in _PLAN_LINES:
        price = getattr(plan, attr)
        if price is None:
            continue
        figure.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[price, price],
                name=label,
                mode="lines",
                line=dict(color=color, width=8, dash="dash"),
                hovertemplate=f"{label} %{{y:.2f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )


def _add_daily_volume(figure: go.Figure, window) -> None:
    up = window.closes >= window.opens
    colors = ["#b91c1c" if flag else "#15803d" for flag in up]
    figure.add_trace(
        go.Bar(
            x=window.dates,
            y=window.volumes,
            name="成交量",
            marker=dict(color=colors, line=dict(width=0)),
            hovertemplate="%{x|%Y-%m-%d}<br>成交量 %{y:,.0f}<extra></extra>",
            showlegend=False,
        ),
        row=2,
        col=1,
    )


def _add_volume_profile(figure: go.Figure, window, levels: list[VolumeLevel]) -> None:
    edges, totals = window.profile
    centers = (edges[:-1] + edges[1:]) / 2.0
    colors = ["#cbd5e1"] * len(totals)
    roles = [""] * len(totals)
    for level in levels:
        if level.kind == "max":
            colors[level.band] = "#1d4ed8"
            roles[level.band] = "组内最大量<br>"
        else:
            colors[level.band] = "#b45309"
            roles[level.band] = "组内最小量<br>"
    custom = [
        [f"{float(edges[i]):.2f}", f"{float(edges[i + 1]):.2f}", roles[i]]
        for i in range(len(totals))
    ]
    figure.add_trace(
        go.Bar(
            y=centers,
            x=totals,
            orientation="h",
            marker=dict(color=colors, line=dict(width=0)),
            name="成交量档",
            customdata=custom,
            hovertemplate=(
                "%{customdata[2]}"
                "价格 %{customdata[0]} – %{customdata[1]}<br>"
                "成交量 %{x:,.0f}<extra></extra>"
            ),
            showlegend=False,
        ),
        row=1,
        col=2,
    )


def _add_threshold(
    figure: go.Figure,
    threshold: float,
    sigma: float,
    mean: float,
    low: float,
) -> None:
    if threshold <= 0:
        return
    y0 = low
    y1 = low + threshold
    text = f"吸收门限 th {_fmt(threshold)}<br>σ {_fmt(sigma, 4)}<br>窗口均价 {_fmt(mean)}"
    figure.add_trace(
        go.Scatter(
            x=[0.012, 0.012],
            y=[y0, y1],
            xaxis="x4",
            yaxis="y",
            name=f"th {threshold:.0f}",
            mode="lines",
            line=dict(color="#0f172a", width=3),
            hovertemplate=text + "<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[0.006, 0.020, None, 0.006, 0.020],
            y=[y0, y0, None, y1, y1],
            xaxis="x4",
            yaxis="y",
            mode="lines",
            line=dict(color="#0f172a", width=1.4),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    figure.add_annotation(
        x=0.028,
        y=(y0 + y1) / 2.0,
        xref="x4",
        yref="y",
        text=f"th {threshold:.0f}",
        showarrow=False,
        xanchor="left",
        font=dict(size=11, color="#0f172a", family=_FONT),
    )


def _kind_label(item: Fractal) -> str:
    kind = "顶分型" if item.kind == "top" else "底分型"
    if item.source == "insert":
        return f"插入{kind}"
    if item.source == "endpoint":
        return f"末端{kind}"
    return kind


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _rgba(hex_color: str, alpha: float) -> str:
    red = int(hex_color[1:3], 16)
    green = int(hex_color[3:5], 16)
    blue = int(hex_color[5:7], 16)
    return f"rgba({red},{green},{blue},{alpha})"
