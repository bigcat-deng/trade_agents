"""3D heat-wave surface and planar contour across theme spectrum × time."""

from __future__ import annotations

import plotly.graph_objects as go

from app.themes.board_cross_marks import CROSS_STYLE

# Hover on CSI 500 traces draws a paper-wide row line (shared y with the heat).
# Also force dual-subplot double-click to reset heat x + CSI x2 + shared y.
_CSI_ROW_HOVER_SCRIPT = """
var gd = document.getElementById('{plot_id}');
if (gd && typeof Plotly !== 'undefined') {
  if (!gd._heatZoomResetBound) {
    gd._heatZoomResetBound = true;
    gd.on('plotly_doubleclick', function() {
      var update = {'xaxis.autorange': true, 'yaxis.autorange': true};
      if (gd.layout && gd.layout.xaxis2) update['xaxis2.autorange'] = true;
      Plotly.relayout(gd, update);
    });
  }
  if (!gd._csiRowHoverBound) {
    gd._csiRowHoverBound = true;
    var csiNames = {'中证500日收益': 1, '中证500成交量': 1};
    function nonCsiShapes() {
      return (gd.layout.shapes || []).filter(function(s) {
        return s && s.name !== 'csi-row-mark';
      });
    }
    function clearCsiRowMark() {
      gd._csiRowY = null;
      Plotly.relayout(gd, {shapes: nonCsiShapes()});
    }
    function showCsiRowMark(y) {
      if (gd._csiRowY === y) return;
      gd._csiRowY = y;
      var shapes = nonCsiShapes();
      shapes.push({
        type: 'line',
        name: 'csi-row-mark',
        xref: 'paper',
        yref: 'y',
        x0: 0,
        x1: 1,
        y0: y,
        y1: y,
        line: {color: 'rgba(28, 25, 23, 0.55)', width: 1},
        layer: 'above'
      });
      Plotly.relayout(gd, {shapes: shapes});
    }
    gd.on('plotly_hover', function(data) {
      var pt = data && data.points && data.points[0];
      var name = pt && pt.data && pt.data.name;
      if (!name || !csiNames[name] || pt.y == null) {
        if (gd._csiRowY != null) clearCsiRowMark();
        return;
      }
      showCsiRowMark(pt.y);
    });
    gd.on('plotly_unhover', function() {
      if (gd._csiRowY != null) clearCsiRowMark();
    });
  }
}
"""


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


def exceedance_label_annotations(return_exceedance: dict[str, object]) -> list[dict]:
    """45° upward name labels for last-day ±2σ boards (Scatter has no textangle)."""
    anns: list[dict] = []
    for color, xs, ys, texts in (
        (
            "#dc2626",
            return_exceedance.get("last_pos_x") or [],
            return_exceedance.get("last_pos_y") or [],
            return_exceedance.get("last_pos_text") or [],
        ),
        (
            "#16a34a",
            return_exceedance.get("last_neg_x") or [],
            return_exceedance.get("last_neg_y") or [],
            return_exceedance.get("last_neg_text") or [],
        ),
    ):
        for x, y, text in zip(xs, ys, texts):
            if text is None or x is None or y is None:
                continue
            anns.append(
                dict(
                    x=float(x),
                    y=float(y),
                    text=str(text),
                    showarrow=False,
                    textangle=-45,
                    font=dict(color=color, size=9),
                    xanchor="left",
                    yanchor="bottom",
                    xref="x",
                    yref="y",
                )
            )
    return anns


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
    title: str = "平面等位图",
    xaxis_title: str = "主题光谱（防守 → 科技）",
    entity_label: str = "主题",
    tickangle: float = 0,
    bottom_margin: int | None = None,
    return_exceedance: dict[str, object] | None = None,
    cross_marks: dict[str, object] | None = None,
    csi500_returns: list[float | None] | None = None,
    csi500_volumes: list[float | None] | None = None,
    csi500_volumes_scaled: list[float | None] | None = None,
) -> str:
    """2D contour of theme × time hotness."""
    if not dates or not x or not z:
        return "<p class='meta'>没有可绘制的等位图数据</p>"

    theme_labels = [_theme_label_for_x(value, x_tickvals, x_ticktext) for value in x]
    y = list(range(len(dates)))
    y_tickvals, y_ticktext = _y_ticks(dates)
    customdata = [
        [[theme_labels[j], dates[i], _format_heat(z[i][j])] for j in range(len(x))]
        for i in range(len(dates))
    ]
    tickfont_size = 8 if len(x_tickvals) > 40 else 10
    margin_b = bottom_margin if bottom_margin is not None else (110 if tickangle else 40)
    margin_t = 88 if return_exceedance is not None else 36
    has_csi500 = bool(csi500_returns) and any(v is not None for v in csi500_returns)
    colorbar = dict(
        title=dict(text="热度", side="right"),
        ticks="outside",
        len=0.55 if has_csi500 else 0.75,
        x=0.79 if has_csi500 else None,
        thickness=12 if has_csi500 else 20,
    )
    colorbar = {k: v for k, v in colorbar.items() if v is not None}

    traces: list = [
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
            colorbar=colorbar,
            customdata=customdata,
            hovertemplate=(
                f"{entity_label} %{{customdata[0]}}<br>"
                "日期 %{customdata[1]}<br>"
                "热度 %{customdata[2]}<extra></extra>"
            ),
            name="等位图",
        )
    ]
    if cross_marks is not None:
        for key, style in CROSS_STYLE.items():
            xs = list(cross_marks.get(f"{key}_x") or [])
            ys = list(cross_marks.get(f"{key}_y") or [])
            texts = list(cross_marks.get(f"{key}_text") or [])
            traces.append(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="markers",
                    marker=dict(
                        symbol=style["symbol"],
                        size=style["size"],
                        color=style["color"],
                        line=dict(width=1.4, color=style["color"]),
                    ),
                    text=texts,
                    hovertemplate=(
                        f"{style['name']}<br>%{{text}}<extra></extra>"
                    ),
                    showlegend=False,
                    name=style["name"],
                )
            )
    if has_csi500:
        csi_x = [v if v is not None else None for v in (csi500_returns or [])]
        traces.append(
            go.Scatter(
                x=csi_x,
                y=y,
                mode="lines",
                line=dict(color="#334155", width=1.3),
                connectgaps=False,
                customdata=dates,
                hovertemplate="中证500<br>%{customdata}<br>日收益 %{x:.2%}<extra></extra>",
                showlegend=False,
                name="中证500日收益",
                xaxis="x2",
                yaxis="y",
            )
        )
        has_vol = bool(csi500_volumes_scaled) and any(
            v is not None for v in csi500_volumes_scaled
        )
        if has_vol:
            raw_vol = list(csi500_volumes or [])
            vol_custom = [
                [
                    dates[i] if i < len(dates) else "",
                    raw_vol[i] if i < len(raw_vol) else None,
                ]
                for i in range(len(y))
            ]
            traces.append(
                go.Scatter(
                    x=list(csi500_volumes_scaled or []),
                    y=y,
                    mode="lines",
                    line=dict(color="#c2410c", width=1.15, dash="dot"),
                    connectgaps=False,
                    customdata=vol_custom,
                    hovertemplate=(
                        "中证500成交量<br>%{customdata[0]}<br>"
                        "成交量 %{customdata[1]:,.0f}<extra></extra>"
                    ),
                    showlegend=False,
                    name="中证500成交量",
                    xaxis="x2",
                    yaxis="y",
                )
            )
    # Draw ±2σ cell ticks last so cross marks / CSI overlays cannot cover them.
    if return_exceedance is not None:
        pos_x = list(return_exceedance.get("pos_x") or [])
        pos_y = list(return_exceedance.get("pos_y") or [])
        neg_x = list(return_exceedance.get("neg_x") or [])
        neg_y = list(return_exceedance.get("neg_y") or [])
        traces.append(
            go.Scatter(
                x=pos_x,
                y=pos_y,
                mode="lines",
                line=dict(color="#111111", width=1.2),
                hoverinfo="skip",
                showlegend=False,
                name="收益>+2σ",
            )
        )
        traces.append(
            go.Scatter(
                x=neg_x,
                y=neg_y,
                mode="lines",
                line=dict(color="#ffffff", width=1.2),
                hoverinfo="skip",
                showlegend=False,
                name="收益<-2σ",
            )
        )

    fig = go.Figure(data=traces)
    annotations = (
        exceedance_label_annotations(return_exceedance)
        if return_exceedance is not None
        else []
    )

    layout = dict(
        margin=dict(l=48, r=56 if has_csi500 else 8, t=margin_t, b=margin_b),
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", size=12, color="#1c1917"),
        title=dict(text=title, x=0, xanchor="left", font=dict(size=15)),
        annotations=annotations,
        xaxis=dict(
            title=dict(text=xaxis_title, font=dict(size=12)),
            tickmode="array",
            tickvals=x_tickvals,
            ticktext=x_ticktext,
            tickfont=dict(size=tickfont_size),
            tickangle=tickangle,
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
    if has_csi500:
        layout["hovermode"] = "closest"
        layout["hoverdistance"] = 80
        layout["xaxis"]["domain"] = [0.0, 0.78]
        layout["xaxis2"] = dict(
            title=dict(text="中证500收益/量", font=dict(size=10)),
            side="right",
            anchor="y",
            domain=[0.88, 1.0],
            tickformat=".1%",
            tickfont=dict(size=8),
            zeroline=True,
            zerolinecolor="#a8a29e",
            gridcolor="#e7e5e4",
        )
    fig.update_layout(**layout)
    html_kw: dict = dict(
        full_html=False,
        include_plotlyjs="cdn" if include_plotlyjs else False,
        config={"displayModeBar": False, "responsive": True},
    )
    if has_csi500:
        html_kw["post_script"] = _CSI_ROW_HOVER_SCRIPT
    return fig.to_html(**html_kw)


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
