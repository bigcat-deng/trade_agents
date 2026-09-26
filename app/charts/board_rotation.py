"""Side-by-side scatter charts of industry-board heat rotation."""

from __future__ import annotations

from decimal import Decimal

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.db import BoardRotationRow

_COLORSCALE = [
    [0.0, "#15803d"],
    [0.5, "#e7e5e4"],
    [1.0, "#b91c1c"],
]


def render_board_rotation(
    rows: list[BoardRotationRow],
    *,
    as_of: str,
    prev_date: str,
    include_plotlyjs: bool = True,
    highlight: str | None = None,
) -> tuple[str, int, int]:
    """Return embeddable HTML plus short and long point counts."""
    short_rows = [
        row
        for row in rows
        if row.heat_short is not None
        and row.prev_heat_short is not None
        and row.vol is not None
    ]
    long_rows = [
        row
        for row in rows
        if row.heat_long is not None
        and row.prev_heat_long is not None
        and row.vol is not None
    ]
    figure = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("短期热度轮转", "长期热度轮转"),
        horizontal_spacing=0.08,
    )
    plotted = short_rows + long_rows
    pct_values = [_float(row.pct_chg) for row in plotted]
    color_limit = max((abs(value) for value in pct_values), default=1.0) or 1.0
    max_vol = max((_float(row.vol) for row in plotted), default=1.0) or 1.0
    sizeref = max_vol / 42.0

    _add_panel(
        figure,
        short_rows,
        heat=lambda row: _float(row.heat_short),
        previous=lambda row: _float(row.prev_heat_short),
        sizeref=sizeref,
        highlight=highlight,
        row=1,
        col=1,
    )
    _add_panel(
        figure,
        long_rows,
        heat=lambda row: _float(row.heat_long),
        previous=lambda row: _float(row.prev_heat_long),
        sizeref=sizeref,
        highlight=highlight,
        row=1,
        col=2,
    )
    figure.update_layout(
        height=680,
        margin=dict(l=60, r=40, t=60, b=50),
        paper_bgcolor="#fffdf8",
        plot_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", color="#1c1917"),
        coloraxis=dict(
            colorscale=_COLORSCALE,
            cmin=-color_limit,
            cmax=color_limit,
            colorbar=dict(title=dict(text="当日收益率"), len=0.7),
        ),
        title=dict(text=f"{as_of} 对比 {prev_date}", x=0, xanchor="left"),
    )
    for axis in (1, 2):
        figure.update_xaxes(
            title_text="当日热度（越小越热）",
            row=1,
            col=axis,
            zeroline=False,
            showgrid=True,
            gridcolor="#e7e5e4",
        )
        figure.update_yaxes(
            title_text="热度变化（前日 − 当日）",
            row=1,
            col=axis,
            zeroline=True,
            zerolinecolor="#a8a29e",
            showgrid=True,
            gridcolor="#e7e5e4",
        )
    html = figure.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
    )
    return html, len(short_rows), len(long_rows)


def _add_panel(
    figure: go.Figure,
    rows: list[BoardRotationRow],
    *,
    heat,
    previous,
    sizeref: float,
    highlight: str | None,
    row: int,
    col: int,
) -> None:
    if not rows:
        return
    chosen = [item for item in rows if highlight and item.board_name == highlight]
    others = [item for item in rows if item not in chosen]
    if others:
        _add_trace(
            figure,
            others,
            heat=heat,
            previous=previous,
            sizeref=sizeref,
            color=[_float(item.pct_chg) for item in others],
            coloraxis="coloraxis",
            text_color="#1c1917",
            row=row,
            col=col,
        )
    if chosen:
        _add_trace(
            figure,
            chosen,
            heat=heat,
            previous=previous,
            sizeref=sizeref,
            color="#2563eb",
            coloraxis=None,
            text_color="#2563eb",
            row=row,
            col=col,
        )


def _add_trace(
    figure: go.Figure,
    rows: list[BoardRotationRow],
    *,
    heat,
    previous,
    sizeref: float,
    color,
    coloraxis: str | None,
    text_color: str,
    row: int,
    col: int,
) -> None:
    marker: dict = dict(
        size=[_float(item.vol) for item in rows],
        sizemode="diameter",
        sizeref=sizeref,
        sizemin=7,
        color=color,
        line=dict(width=0.6, color="#1d4ed8" if coloraxis is None else "#44403c"),
    )
    if coloraxis is not None:
        marker["coloraxis"] = coloraxis
    figure.add_trace(
        go.Scatter(
            x=[heat(item) for item in rows],
            y=[previous(item) - heat(item) for item in rows],
            mode="markers+text",
            textposition="top center",
            textfont=dict(size=10, color=text_color),
            marker=marker,
            text=[item.board_name for item in rows],
            customdata=[
                [item.board_code, _float(item.pct_chg), _float(item.vol)]
                for item in rows
            ],
            hovertemplate=(
                "%{text}（%{customdata[0]}）<br>"
                "当日热度 %{x:.2f}<br>"
                "热度变化 %{y:.2f}<br>"
                "当日收益率 %{customdata[1]:.2f}<br>"
                "20日波动率 %{customdata[2]:.2f}"
                "<extra></extra>"
            ),
            showlegend=False,
        ),
        row=row,
        col=col,
    )


def _float(value: Decimal | float | int) -> float:
    return float(value)
