"""Line charts for concept theme heat consistency."""

from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots


_A_COLORS = ("#1d4ed8", "#3b82f6", "#93c5fd")
_B_COLORS = ("#b45309", "#d97706", "#fbbf24")
_GROUP_A = "#1e3a8a"
_GROUP_B = "#92400e"
_SAT = "#78716c"


def render_theme_charts(
    *,
    dates: list[str],
    series_a: list[float | None],
    series_b: list[float | None],
    members_a: list[dict],
    members_b: list[dict],
    satellite: dict | None,
    include_plotlyjs: bool = True,
) -> tuple[str, str]:
    """Return (group chart HTML, member chart HTML).

    Series values are market percentiles (0=hottest). Y axis is reversed.
    ``members_*`` items: {name, values: list[float|None]}
    ``satellite``: {name, values} or None.
    """
    group_fig = go.Figure()
    group_fig.add_trace(
        go.Scatter(
            x=dates,
            y=series_a,
            mode="lines+markers",
            name="群A 中位",
            line=dict(color=_GROUP_A, width=2.5),
            marker=dict(size=6),
        )
    )
    group_fig.add_trace(
        go.Scatter(
            x=dates,
            y=series_b,
            mode="lines+markers",
            name="群B 中位",
            line=dict(color=_GROUP_B, width=2.5),
            marker=dict(size=6),
        )
    )
    _style_heat_axis(group_fig, title="群热度分位（中位数）· 上热下冷")
    group_html = group_fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
    )

    member_fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.14,
        subplot_titles=("群A 成员短热分位", "群B 与卫星"),
        row_heights=[0.55, 0.45],
    )
    for index, member in enumerate(members_a):
        member_fig.add_trace(
            go.Scatter(
                x=dates,
                y=member["values"],
                mode="lines",
                name=member["name"],
                line=dict(color=_A_COLORS[index % len(_A_COLORS)], width=2),
            ),
            row=1,
            col=1,
        )
    for index, member in enumerate(members_b):
        member_fig.add_trace(
            go.Scatter(
                x=dates,
                y=member["values"],
                mode="lines",
                name=member["name"],
                line=dict(color=_B_COLORS[index % len(_B_COLORS)], width=1.8),
            ),
            row=2,
            col=1,
        )
    if satellite is not None:
        member_fig.add_trace(
            go.Scatter(
                x=dates,
                y=satellite["values"],
                mode="lines",
                name=satellite["name"],
                line=dict(color=_SAT, width=1.6, dash="dot"),
            ),
            row=2,
            col=1,
        )
    member_fig.update_yaxes(autorange="reversed", title_text="分位", row=1, col=1)
    member_fig.update_yaxes(autorange="reversed", title_text="分位", row=2, col=1)
    member_fig.update_layout(
        height=560,
        margin=dict(l=48, r=24, t=72, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
        plot_bgcolor="#fffdf8",
        paper_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", color="#1c1917"),
    )
    member_fig.update_annotations(font_size=13, yshift=8)
    member_html = member_fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True},
    )
    return group_html, member_html


def _style_heat_axis(figure: go.Figure, *, title: str) -> None:
    figure.update_yaxes(autorange="reversed", title_text="分位 0=最热")
    figure.update_layout(
        title=dict(text=title, font=dict(size=14)),
        height=320,
        margin=dict(l=48, r=24, t=48, b=36),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        plot_bgcolor="#fffdf8",
        paper_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", color="#1c1917"),
    )
