"""3D heat-wave surface and planar contour across theme spectrum × time."""

from __future__ import annotations

import plotly.graph_objects as go

_COLORSCALE = [
    [0.0, "#1e3a5f"],
    [0.35, "#0ea5e9"],
    [0.55, "#86efac"],
    [0.75, "#fbbf24"],
    [1.0, "#dc2626"],
]


def _theme_label_for_x(
    x_value: float,
    x_tickvals: list[float],
    x_ticktext: list[str],
) -> str:
    """Exact theme name on ticks; 'A ↔ B' on interpolated positions."""
    if not x_tickvals or not x_ticktext:
        return f"主题轴 {x_value:.2f}"
    for tick, label in zip(x_tickvals, x_ticktext):
        if abs(x_value - tick) < 1e-9:
            return label
    for i in range(len(x_tickvals) - 1):
        left_x, right_x = x_tickvals[i], x_tickvals[i + 1]
        if left_x <= x_value <= right_x:
            return f"{x_ticktext[i]} ↔ {x_ticktext[i + 1]}"
    if x_value < x_tickvals[0]:
        return x_ticktext[0]
    return x_ticktext[-1]


def _format_heat(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.3f}"


def _y_ticks(dates: list[str]) -> tuple[list[int], list[str]]:
    n_dates = len(dates)
    tick_step = max(1, n_dates // 6)
    y_tickvals = list(range(0, n_dates, tick_step))
    if y_tickvals[-1] != n_dates - 1:
        y_tickvals.append(n_dates - 1)
    y_ticktext = [dates[i] for i in y_tickvals]
    return y_tickvals, y_ticktext


def render_theme_wave_surface(
    *,
    dates: list[str],
    x: list[float],
    z: list[list[float | None]],
    x_tickvals: list[float],
    x_ticktext: list[str],
    include_plotlyjs: bool = True,
    height: int = 560,
    title: str = "主题热度水面 · 可拖拽旋转",
    xaxis_title: str = "主题光谱（防守 → 科技）",
) -> str:
    """Plotly surface: x=theme spectrum, y=time, z=hotness (high=hot)."""
    if not dates or not x or not z:
        return "<p class='meta'>没有可绘制的曲面数据</p>"

    y = list(range(len(dates)))
    y_tickvals, y_ticktext = _y_ticks(dates)

    fig = go.Figure(
        data=[
            go.Surface(
                x=x,
                y=y,
                z=z,
                surfacecolor=z,
                colorscale=_COLORSCALE,
                cmin=0.0,
                cmax=1.0,
                opacity=0.92,
                showscale=True,
                colorbar=dict(
                    title=dict(text="热度", side="right"),
                    ticks="outside",
                    len=0.65,
                    x=1.02,
                ),
                # Interaction is on the planar contour; 3D is display-only.
                hoverinfo="skip",
                hovertemplate=None,
                contours=dict(
                    z=dict(
                        show=True,
                        usecolormap=True,
                        highlightcolor="#f8fafc",
                        project_z=False,
                    )
                ),
            ),
            # Red pick marker; updated from the planar map via Plotly.restyle.
            go.Scatter3d(
                x=[None],
                y=[None],
                z=[None],
                mode="markers",
                marker=dict(
                    size=7,
                    color="#dc2626",
                    symbol="circle",
                    line=dict(width=1, color="#7f1d1d"),
                ),
                name="选点",
                hoverinfo="skip",
                showlegend=False,
            ),
        ]
    )

    fig.update_layout(
        margin=dict(l=0, r=0, t=36, b=0),
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", size=13, color="#1c1917"),
        title=dict(text=title, x=0, xanchor="left", font=dict(size=15)),
        scene=dict(
            xaxis=dict(
                title=dict(text=xaxis_title, font=dict(size=12)),
                tickmode="array",
                tickvals=x_tickvals,
                ticktext=x_ticktext,
                tickfont=dict(size=10),
                backgroundcolor="rgba(244,241,234,0.55)",
                gridcolor="#d6d3d1",
                showspikes=False,
            ),
            yaxis=dict(
                title=dict(text="时间", font=dict(size=12)),
                tickmode="array",
                tickvals=y_tickvals,
                ticktext=y_ticktext,
                tickfont=dict(size=10),
                backgroundcolor="rgba(244,241,234,0.45)",
                gridcolor="#d6d3d1",
                showspikes=False,
            ),
            zaxis=dict(
                title=dict(text="热度（高=热）", font=dict(size=12)),
                range=[0, 1],
                tickfont=dict(size=10),
                backgroundcolor="rgba(244,241,234,0.35)",
                gridcolor="#d6d3d1",
                showspikes=False,
            ),
            aspectmode="manual",
            aspectratio=dict(x=1.55, y=1.35, z=0.55),
            camera=dict(
                eye=dict(x=0.05, y=-0.08, z=2.15),
                center=dict(x=0, y=0, z=-0.12),
                up=dict(x=0, y=1, z=0),
            ),
        ),
    )
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": True, "responsive": True, "scrollZoom": True},
    )


def render_theme_wave_contour(
    *,
    dates: list[str],
    x: list[float],
    z: list[list[float | None]],
    x_tickvals: list[float],
    x_ticktext: list[str],
    include_plotlyjs: bool = False,
    height: int = 560,
    title: str = "平面等位图 · 点击取点",
    xaxis_title: str = "主题光谱（防守 → 科技）",
) -> str:
    """2D contour for accurate theme×time picking; drives the 3D red marker."""
    if not dates or not x or not z:
        return "<p class='meta'>没有可绘制的等位图数据</p>"

    theme_labels = [_theme_label_for_x(value, x_tickvals, x_ticktext) for value in x]
    y = list(range(len(dates)))
    y_tickvals, y_ticktext = _y_ticks(dates)
    customdata = [
        [[theme_labels[j], dates[i], _format_heat(z[i][j])] for j in range(len(x))]
        for i in range(len(dates))
    ]

    fig = go.Figure(
        data=[
            go.Contour(
                x=x,
                y=y,
                z=z,
                colorscale=_COLORSCALE,
                zmin=0.0,
                zmax=1.0,
                contours=dict(
                    coloring="heatmap",
                    showlines=True,
                    start=0.0,
                    end=1.0,
                    size=0.1,
                ),
                line=dict(width=0.6, color="rgba(28,25,23,0.25)"),
                colorbar=dict(
                    title=dict(text="热度", side="right"),
                    ticks="outside",
                    len=0.75,
                ),
                customdata=customdata,
                hovertemplate=(
                    "主题 %{customdata[0]}<br>"
                    "日期 %{customdata[1]}<br>"
                    "热度 %{customdata[2]}<extra></extra>"
                ),
                name="等位图",
            )
        ]
    )

    fig.update_layout(
        margin=dict(l=48, r=8, t=36, b=40),
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", size=12, color="#1c1917"),
        title=dict(text=title, x=0, xanchor="left", font=dict(size=15)),
        xaxis=dict(
            title=dict(text=xaxis_title, font=dict(size=12)),
            tickmode="array",
            tickvals=x_tickvals,
            ticktext=x_ticktext,
            tickfont=dict(size=10),
            gridcolor="#e7e5e4",
            zeroline=False,
        ),
        yaxis=dict(
            title=dict(text="时间", font=dict(size=12)),
            tickmode="array",
            tickvals=y_tickvals,
            ticktext=y_ticktext,
            tickfont=dict(size=10),
            gridcolor="#e7e5e4",
            zeroline=False,
        ),
    )
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
    )


def render_board_heat_heatmap(
    *,
    dates: list[str],
    x: list[float],
    z: list[list[float | None]],
    x_tickvals: list[float],
    x_ticktext: list[str],
    include_plotlyjs: bool = False,
    height: int = 560,
    title: str = "行业热度平面图",
    xaxis_title: str = "行业板块（高 → 低）",
    entity_label: str = "板块",
) -> str:
    """Discrete heatmap for board × time (no interpolation between boards)."""
    if not dates or not x or not z:
        return "<p class='meta'>没有可绘制的热力图数据</p>"

    labels = list(x_ticktext) if x_ticktext else [str(v) for v in x]
    # Pad labels to x length if densified (not used here, but safe).
    if len(labels) < len(x):
        labels = labels + [f"#{i}" for i in range(len(labels), len(x))]
    y = list(range(len(dates)))
    y_tickvals, y_ticktext = _y_ticks(dates)
    customdata = [
        [[labels[j], dates[i], _format_heat(z[i][j])] for j in range(len(x))]
        for i in range(len(dates))
    ]

    # With many boards, thin tick labels; keep every label for lookup via hover.
    tickfont_size = 8 if len(x_tickvals) > 40 else 10
    fig = go.Figure(
        data=[
            go.Heatmap(
                x=x,
                y=y,
                z=z,
                colorscale=_COLORSCALE,
                zmin=0.0,
                zmax=1.0,
                colorbar=dict(
                    title=dict(text="热度", side="right"),
                    ticks="outside",
                    len=0.75,
                ),
                customdata=customdata,
                hovertemplate=(
                    f"{entity_label} %{{customdata[0]}}<br>"
                    "日期 %{customdata[1]}<br>"
                    "热度 %{customdata[2]}<extra></extra>"
                ),
                name="热力",
            )
        ]
    )

    fig.update_layout(
        margin=dict(l=48, r=8, t=36, b=110),
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", size=12, color="#1c1917"),
        title=dict(text=title, x=0, xanchor="left", font=dict(size=15)),
        xaxis=dict(
            title=dict(text=xaxis_title, font=dict(size=12)),
            tickmode="array",
            tickvals=x_tickvals,
            ticktext=x_ticktext,
            tickfont=dict(size=tickfont_size),
            tickangle=-55,
            gridcolor="#e7e5e4",
            zeroline=False,
        ),
        yaxis=dict(
            title=dict(text="时间", font=dict(size=12)),
            tickmode="array",
            tickvals=y_tickvals,
            ticktext=y_ticktext,
            tickfont=dict(size=10),
            gridcolor="#e7e5e4",
            zeroline=False,
        ),
    )
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
    )
