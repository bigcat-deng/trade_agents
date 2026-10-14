"""Three-panel size-ladder chart: cumulative return, spread, range position."""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.market_data.index_ladder import INDICES

_FONT = "IBM Plex Sans, Noto Sans SC, sans-serif"
_PAPER = "#fffdf8"
_GRID = "#e7e5e4"
_ZERO = "#a8a29e"


def render_index_size_ladder(payload: dict, *, include_plotlyjs: bool = True) -> str:
    dates = payload["dates"]
    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.07,
        row_heights=[0.42, 0.28, 0.30],
        subplot_titles=(
            "累计收益（%），窗口首日收盘 = 0",
            "散度（百分点）",
            "区间位置（0 = 本窗口最低，1 = 最高）",
        ),
    )
    for name, _code, color in INDICES:
        figure.add_trace(
            go.Scatter(
                x=dates,
                y=payload["returns_pct"][name],
                name=name,
                mode="lines",
                line=dict(color=color, width=1.6),
                legendgroup=name,
                hovertemplate=f"{name} %{{x}} %{{y:.2f}}%<extra></extra>",
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(
                x=dates,
                y=payload["position"][name],
                name=name,
                mode="lines",
                line=dict(color=color, width=1.6),
                legendgroup=name,
                showlegend=False,
                hovertemplate=f"{name} %{{x}} %{{y:.3f}}<extra></extra>",
            ),
            row=3,
            col=1,
        )
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=payload["range_pp"],
            name="截面极差",
            mode="lines",
            line=dict(color="#57534e", width=1.6),
            hovertemplate="截面极差 %{x} %{y:.2f} 个百分点<extra></extra>",
        ),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=payload["spread_50_2000_pp"],
            name="上证50 − 国证2000",
            mode="lines",
            line=dict(color="#1f4e79", width=1.6),
            hovertemplate="上证50−国证2000 %{x} %{y:.2f} 个百分点<extra></extra>",
        ),
        row=2,
        col=1,
    )
    figure.update_layout(
        height=980,
        margin=dict(l=64, r=16, t=28, b=72),
        paper_bgcolor=_PAPER,
        plot_bgcolor=_PAPER,
        font=dict(family=_FONT, color="#1c1917"),
        legend=dict(orientation="h", yanchor="top", y=-0.04, x=0),
        hovermode="x unified",
    )
    figure.update_yaxes(
        title_text="累计收益 (%)",
        zeroline=True,
        zerolinecolor=_ZERO,
        showgrid=True,
        gridcolor=_GRID,
        row=1,
        col=1,
    )
    figure.update_yaxes(
        title_text="百分点",
        zeroline=True,
        zerolinecolor=_ZERO,
        showgrid=True,
        gridcolor=_GRID,
        row=2,
        col=1,
    )
    figure.update_yaxes(
        title_text="区间位置",
        range=[-0.02, 1.02],
        zeroline=False,
        showgrid=True,
        gridcolor=_GRID,
        row=3,
        col=1,
    )
    figure.update_xaxes(showgrid=False, row=1, col=1)
    figure.update_xaxes(showgrid=False, row=2, col=1)
    figure.update_xaxes(showgrid=False, row=3, col=1)
    return figure.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
    )


def render_a_share_breadth(payload: dict, *, include_plotlyjs: bool = True) -> str:
    """Diverging up/down counts, with the up-share on its own axis below."""
    dates = payload["dates"]
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.72, 0.28],
        subplot_titles=("涨跌家数", "上涨占比（%）"),
    )
    figure.add_trace(
        go.Bar(
            x=dates,
            y=payload["up"],
            name="上涨",
            marker_color="#15803d",
            hovertemplate="上涨 %{y}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            x=dates,
            y=payload["down"],
            name="下跌",
            marker_color="#b91c1c",
            hovertemplate="下跌 %{customdata}<extra></extra>",
            customdata=[None if value is None else -value for value in payload["down"]],
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=payload["flat"],
            name="平盘",
            mode="lines",
            line=dict(color="#a8a29e", width=1.2),
            hovertemplate="平盘 %{y}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=payload["incomplete"],
            name="数据不全",
            mode="markers",
            marker=dict(color="#a8a29e", size=7, symbol="circle"),
            hovertemplate="成交家数不足，当日留空<extra></extra>",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=payload["up_ratio"],
            name="上涨占比",
            mode="lines",
            line=dict(color="#1d4ed8", width=1.6),
            hovertemplate="上涨占比 %{y:.1f}%<extra></extra>",
        ),
        row=2,
        col=1,
    )
    figure.update_layout(
        height=520,
        barmode="relative",
        margin=dict(l=64, r=16, t=36, b=96),
        paper_bgcolor=_PAPER,
        plot_bgcolor=_PAPER,
        font=dict(family=_FONT, color="#1c1917"),
        legend=dict(orientation="h", yanchor="top", y=-0.06, x=0),
        hovermode="x unified",
        bargap=0.15,
    )
    figure.update_yaxes(
        title_text="家数",
        zeroline=True,
        zerolinecolor=_ZERO,
        showgrid=True,
        gridcolor=_GRID,
        row=1,
        col=1,
    )
    figure.update_yaxes(
        title_text="占比",
        range=[0, 100],
        zeroline=False,
        showgrid=True,
        gridcolor=_GRID,
        row=2,
        col=1,
    )
    figure.update_xaxes(showgrid=False, row=1, col=1)
    figure.update_xaxes(showgrid=False, row=2, col=1)
    return figure.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
    )
