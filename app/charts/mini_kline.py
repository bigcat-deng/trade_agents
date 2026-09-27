"""Compact OHLC candlesticks for theme grids (no volume/MACD/heat)."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

import plotly.graph_objects as go


def scale_benchmark_to_price(
    board_bars: Sequence[Mapping[str, Any]],
    benchmark_closes: Mapping[date, float],
) -> list[tuple[date, float]] | None:
    """Map benchmark closes onto this chart's high/low range.

    Returns aligned (trade_date, scaled_y) or None when scaling is impossible.
    """
    if not board_bars or not benchmark_closes:
        return None

    highs: list[float] = []
    lows: list[float] = []
    aligned: list[tuple[date, float]] = []
    for row in board_bars:
        day = _as_day(row["trade_date"])
        index_close = benchmark_closes.get(day)
        if index_close is None:
            continue
        high = _float(row.get("high"))
        low = _float(row.get("low"))
        if high is None or low is None:
            continue
        highs.append(high)
        lows.append(low)
        aligned.append((day, index_close))

    if len(aligned) < 2:
        return None
    price_min = min(lows)
    price_max = max(highs)
    index_min = min(value for _, value in aligned)
    index_max = max(value for _, value in aligned)
    if price_max <= price_min or index_max <= index_min:
        return None

    span_price = price_max - price_min
    span_index = index_max - index_min
    return [
        (
            day,
            price_min + (value - index_min) / span_index * span_price,
        )
        for day, value in aligned
    ]


def render_mini_kline(
    bars: Sequence[Mapping[str, Any]],
    *,
    title: str,
    height: int = 240,
    include_plotlyjs: bool = False,
    benchmark_closes: Mapping[date, float] | None = None,
) -> str:
    """Return embeddable HTML for one mini candlestick chart.

    X ticks are the first trading day of each calendar month in the series.
    Optional CSI 500 (or other) closes are min-max scaled to this chart's
    high/low and drawn as a translucent background fill.
    """
    if not bars:
        return (
            '<div class="mini-empty">'
            f'<strong>{_escape(title)}</strong>'
            "<span>无日 K</span>"
            "</div>"
        )

    day_values = [_as_day(row["trade_date"]) for row in bars]
    xs = [day.isoformat() for day in day_values]
    opens = [_float(row.get("open")) for row in bars]
    highs = [_float(row.get("high")) for row in bars]
    lows = [_float(row.get("low")) for row in bars]
    closes = [_float(row.get("close")) for row in bars]
    tick_days, tick_text = _month_ticks(day_values)
    tick_vals = [day.isoformat() for day in tick_days]

    traces: list = []
    scaled = None
    if benchmark_closes:
        scaled = scale_benchmark_to_price(bars, benchmark_closes)
    if scaled:
        price_min = min(v for v in lows if v is not None)
        bx = [day.isoformat() for day, _ in scaled]
        by = [value for _, value in scaled]
        traces.append(
            go.Scatter(
                x=bx,
                y=[price_min] * len(bx),
                mode="lines",
                line=dict(width=0),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        traces.append(
            go.Scatter(
                x=bx,
                y=by,
                mode="lines",
                line=dict(color="rgba(100, 116, 139, 0.45)", width=1.2),
                fill="tonexty",
                fillcolor="rgba(100, 116, 139, 0.16)",
                hoverinfo="skip",
                showlegend=False,
                name="中证500",
            )
        )

    traces.append(
        go.Candlestick(
            x=xs,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            increasing_line_color="#b91c1c",
            decreasing_line_color="#15803d",
            increasing_fillcolor="#b91c1c",
            decreasing_fillcolor="#15803d",
            name=title,
            showlegend=False,
            hoverinfo="skip",
        )
    )

    # Invisible hover rail: spikes need a hoverable trace; `skip` on everything
    # disables the vertical spike. Empty hovertemplate = no numeric label.
    rail_y = [
        ((high + low) / 2.0 if high is not None and low is not None else close)
        for high, low, close in zip(highs, lows, closes)
    ]
    traces.append(
        go.Scatter(
            x=xs,
            y=rail_y,
            mode="markers",
            marker=dict(size=24, opacity=0),
            hovertemplate="<extra></extra>",
            showlegend=False,
            name="",
        )
    )

    figure = go.Figure(data=traces)
    figure.update_layout(
        title=None,
        height=height,
        margin=dict(l=36, r=12, t=16, b=28),
        plot_bgcolor="#fffdf8",
        paper_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", color="#1c1917", size=11),
        hovermode="x",
        spikedistance=-1,
        hoverlabel=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)",
            font=dict(size=1, color="rgba(0,0,0,0)"),
        ),
        xaxis=dict(
            # Date axis: category + spikes often fail to draw the vertical line.
            type="date",
            tickmode="array",
            tickvals=tick_vals,
            ticktext=tick_text,
            rangeslider=dict(visible=False),
            showgrid=False,
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1.25,
            spikedash="solid",
            spikecolor="rgba(28, 25, 23, 0.65)",
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#e7e5e4",
            zeroline=False,
            tickfont=dict(size=10),
            showspikes=False,
        ),
    )
    # JS crosshair: Plotly spikes are unreliable when most traces use hoverinfo=skip.
    post_script = """
    var gd = document.getElementById('{plot_id}');
    if (gd) {
      gd.on('plotly_hover', function(data) {
        if (!data || !data.points || !data.points.length) return;
        var x = data.points[0].x;
        Plotly.relayout(gd, {
          shapes: [{
            type: 'line',
            xref: 'x',
            yref: 'paper',
            x0: x,
            x1: x,
            y0: 0,
            y1: 1,
            line: {color: 'rgba(28, 25, 23, 0.65)', width: 1}
          }]
        });
      });
      gd.on('plotly_unhover', function() {
        Plotly.relayout(gd, {shapes: []});
      });
    }
    """
    return figure.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
        post_script=post_script,
    )


def _month_ticks(days: Sequence[date]) -> tuple[list[date], list[str]]:
    ticks: list[date] = []
    labels: list[str] = []
    previous: tuple[int, int] | None = None
    for day in days:
        key = (day.year, day.month)
        if key == previous:
            continue
        previous = key
        ticks.append(day)
        labels.append(f"{day.year}-{day.month:02d}")
    return ticks, labels


def _as_day(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
