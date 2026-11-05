"""Stock short/long heat curve aligned under the Chan chart.

Uses the same left-column width, margins, and padded x-range as
``chan_board`` so trading days line up when stacked on /analyze.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.charts.chan_board import chan_xaxis_range

_FONT = "PingFang SC, Noto Sans SC, sans-serif"


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _rank_change_label(value: object) -> str:
    if value is None:
        return "—"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "—"
    if number > 0:
        return f"+{number}"
    return str(number)


def _comment_points(
    comments: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[date], list[float], list[str]]:
    dates: list[date] = []
    ranks: list[float] = []
    changes: list[str] = []
    for row in comments or ():
        day = row.get("trade_date")
        rank = _as_float(row.get("rank_no"))
        if not isinstance(day, date) or rank is None:
            continue
        dates.append(day)
        ranks.append(rank)
        changes.append(_rank_change_label(row.get("rank_change")))
    return dates, ranks, changes


def build_stock_heat_figure(
    heats: Sequence[Mapping[str, Any]],
    *,
    title: str,
    start: date,
    end: date,
    n: int,
    comments: Sequence[Mapping[str, Any]] | None = None,
) -> go.Figure | None:
    """Plot heat_short / heat_long; return None when nothing finite to draw.

    ``comments`` are 千股千评 ranks on the same reversed axis. Only days with
    a rank are included; those points are joined with a dashed line.
    """
    dates: list[date] = []
    short: list[float | None] = []
    long: list[float | None] = []
    for row in heats:
        day = row.get("trade_date")
        if not isinstance(day, date):
            continue
        short_v = _as_float(row.get("heat_short"))
        long_v = _as_float(row.get("heat_long"))
        if short_v is None and long_v is None:
            continue
        dates.append(day)
        short.append(short_v)
        long.append(long_v)
    comment_dates, comment_ranks, comment_changes = _comment_points(comments)
    if not dates:
        return None

    x_range = chan_xaxis_range(start, end, n)
    figure = make_subplots(
        rows=1,
        cols=2,
        shared_yaxes=False,
        column_widths=[0.81, 0.19],
        horizontal_spacing=0.03,
        specs=[[{}, {}]],
    )
    if any(v is not None for v in short):
        figure.add_trace(
            go.Scatter(
                x=dates,
                y=short,
                name="短热",
                mode="lines",
                connectgaps=False,
                line=dict(color="#dc2626", width=1.8),
                hovertemplate="短热 %{y:.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if any(v is not None for v in long):
        figure.add_trace(
            go.Scatter(
                x=dates,
                y=long,
                name="长热",
                mode="lines",
                connectgaps=False,
                line=dict(color="#2563eb", width=1.6),
                hovertemplate="长热 %{y:.2f}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    series_title = "短热 / 长热"
    if comment_ranks:
        figure.add_trace(
            go.Scatter(
                x=comment_dates,
                y=comment_ranks,
                name="千股千评",
                mode="lines+markers",
                line=dict(color="#b45309", width=1.4, dash="dash"),
                marker=dict(color="#b45309", size=8, symbol="circle"),
                customdata=comment_changes,
                hovertemplate="千股千评 %{y:.0f}  变动 %{customdata}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        series_title = "短热 / 长热 / 千股千评"

    figure.update_xaxes(
        rangeslider_visible=False,
        tickformat="%Y-%m-%d",
        range=x_range,
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikecolor="#a8a29e",
        row=1,
        col=1,
    )
    figure.update_xaxes(visible=False, showticklabels=False, row=1, col=2)
    figure.update_yaxes(
        title_text="热度",
        autorange="reversed",
        showspikes=True,
        row=1,
        col=1,
    )
    figure.update_yaxes(visible=False, showticklabels=False, row=1, col=2)
    figure.update_layout(
        title=dict(
            text=f"{title}  {series_title}   {start} — {end}",
            x=0,
            xanchor="left",
            xref="container",
            y=1,
            yanchor="top",
            font=dict(size=14),
            pad=dict(t=4, b=0),
        ),
        font=dict(family=_FONT, size=12),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", font=dict(family=_FONT, size=12)),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            xanchor="left",
            font=dict(size=11),
        ),
        margin=dict(t=64, l=64, r=24, b=48),
        height=280,
        paper_bgcolor="white",
        plot_bgcolor="white",
        annotations=[
            dict(
                text="数值越小越热",
                xref="paper",
                yref="paper",
                x=1,
                y=1.08,
                showarrow=False,
                xanchor="right",
                font=dict(size=11, color="#78716c", family=_FONT),
            )
        ],
    )
    return figure


def render_stock_heat_html(
    heats: Sequence[Mapping[str, Any]],
    *,
    title: str,
    start: date,
    end: date,
    n: int,
    include_plotlyjs: bool | str = False,
    comments: Sequence[Mapping[str, Any]] | None = None,
) -> str | None:
    figure = build_stock_heat_figure(
        heats, title=title, start=start, end=end, n=n, comments=comments
    )
    if figure is None:
        return None
    return figure.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        config={"displayModeBar": False, "scrollZoom": False},
    )
