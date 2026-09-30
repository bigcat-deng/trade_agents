"""Plotly charts for concept Top200 2D wavelet page."""

from __future__ import annotations

from plotly import graph_objects as go
from plotly.subplots import make_subplots


def _y_ticks(dates: list[str], n: int = 6) -> tuple[list[int], list[str]]:
    if not dates:
        return [], []
    import numpy as np

    idx = np.linspace(0, len(dates) - 1, num=min(n, len(dates)), dtype=int)
    return idx.tolist(), [dates[i][5:] for i in idx]


def _x_ticks(names: list[str], n: int = 8) -> tuple[list[int], list[str]]:
    if not names:
        return [], []
    import numpy as np

    idx = np.linspace(0, len(names) - 1, num=min(n, len(names)), dtype=int)
    labels = []
    for i in idx:
        name = names[i]
        labels.append(name if len(name) <= 6 else name[:5] + "…")
    return idx.tolist(), labels


def _heatmap(
    z: list[list[float]],
    *,
    dates: list[str],
    names: list[str],
    colorscale: str,
    zmid: float | None = None,
    zmin: float | None = None,
    zmax: float | None = None,
    entity_label: str = "概念",
) -> go.Heatmap:
    y = list(range(len(dates)))
    x = list(range(len(names)))
    customdata = [
        [[names[j], dates[i]] for j in range(len(names))]
        for i in range(len(dates))
    ]
    return go.Heatmap(
        x=x,
        y=y,
        z=z,
        colorscale=colorscale,
        zmid=zmid,
        zmin=zmin,
        zmax=zmax,
        colorbar=dict(len=0.75, thickness=12),
        customdata=customdata,
        hovertemplate=(
            f"{entity_label} %{{customdata[0]}}<br>"
            "日期 %{customdata[1]}<br>"
            "值 %{z:.3f}<extra></extra>"
        ),
    )


def render_wavelet_multiscale(
    *,
    dates: list[str],
    names: list[str],
    z_short: list[list[float | None]],
    approx: list[list[float]],
    d3: list[list[float]],
    d1: list[list[float]],
    as_of: str,
    include_plotlyjs: bool = True,
    height: int = 960,
    entity_label: str = "概念",
) -> str:
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            f"原图 · {entity_label}短热翻转 · {as_of}",
            "A3 粗结构（+均值）≈ 主线/占位背景",
            "D3 中粗细节 · 红偏热 / 蓝偏冷",
            "D1 细尺度 · 局部脉冲",
        ),
        # Room for row-1 angled ticks + axis title without colliding row-2 titles.
        vertical_spacing=0.18,
        horizontal_spacing=0.06,
    )
    yt, yl = _y_ticks(dates)
    xt, xl = _x_ticks(names)

    import numpy as np

    d3_a = np.asarray(d3, dtype=float)
    d1_a = np.asarray(d1, dtype=float)
    vmax = float(
        np.percentile(np.abs(np.concatenate([d3_a.ravel(), d1_a.ravel()])), 99)
    )
    vmax = max(vmax, 1e-3)

    fig.add_trace(
        _heatmap(
            z_short,
            dates=dates,
            names=names,
            colorscale="YlOrRd",
            zmin=0,
            zmax=1,
            entity_label=entity_label,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        _heatmap(
            approx,
            dates=dates,
            names=names,
            colorscale="YlOrRd",
            zmin=0,
            zmax=1,
            entity_label=entity_label,
        ),
        row=1,
        col=2,
    )
    fig.add_trace(
        _heatmap(
            d3,
            dates=dates,
            names=names,
            colorscale="RdBu_r",
            zmid=0,
            zmin=-vmax,
            zmax=vmax,
            entity_label=entity_label,
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        _heatmap(
            d1,
            dates=dates,
            names=names,
            colorscale="RdBu_r",
            zmid=0,
            zmin=-vmax,
            zmax=vmax,
            entity_label=entity_label,
        ),
        row=2,
        col=2,
    )

    for r in (1, 2):
        for c in (1, 2):
            # Top row: no x tick text / axis title — angled labels were colliding
            # with D3/D1 subplot titles. Hover still shows board names.
            fig.update_xaxes(
                tickmode="array",
                tickvals=xt,
                ticktext=xl,
                tickangle=-30 if r == 2 else 0,
                showticklabels=(r == 2),
                title_text=f"{entity_label}叶序" if r == 2 else "",
                title_standoff=8 if r == 2 else 0,
                automargin=True,
                row=r,
                col=c,
            )
            fig.update_yaxes(
                tickmode="array",
                tickvals=yt,
                ticktext=yl,
                title_text="交易日",
                automargin=True,
                row=r,
                col=c,
            )

    fig.update_layout(
        height=height,
        margin=dict(l=56, r=28, t=64, b=56),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", size=11, color="#1c1917"),
        showlegend=False,
    )
    # Nudge subplot titles slightly so row-2 titles sit clear of row-1 ticks.
    for ann in fig.layout.annotations or []:
        if getattr(ann, "text", None):
            ann.update(yshift=6)
    return fig.to_html(full_html=False, include_plotlyjs="cdn" if include_plotlyjs else False)


def render_wavelet_energy(
    *,
    energy: list[dict],
    directions: list[dict],
    as_of: str,
    top_n: int,
    include_plotlyjs: bool = False,
    height: int = 360,
) -> str:
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=(
            f"多尺度能量 · Top{top_n} · {as_of}",
            "方向拆分（全部细节层）",
        ),
        horizontal_spacing=0.1,
    )
    e_labels = [row["label"] for row in energy]
    e_vals = [row["share_pct"] for row in energy]
    d_labels = [row["label"] for row in directions]
    d_vals = [row["share_pct"] for row in directions]

    fig.add_trace(
        go.Bar(
            x=e_labels,
            y=e_vals,
            marker_color=["#b45309", "#ea580c", "#f59e0b", "#fbbf24"][: len(e_vals)],
            text=[f"{v:.1f}%" for v in e_vals],
            textposition="outside",
            name="尺度",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=d_labels,
            y=d_vals,
            marker_color=["#1d4ed8", "#7c3aed", "#db2777"][: len(d_vals)],
            text=[f"{v:.1f}%" for v in d_vals],
            textposition="outside",
            name="方向",
        ),
        row=1,
        col=2,
    )
    fig.update_yaxes(title_text="能量占比 %", range=[0, max(e_vals + [1]) * 1.25], row=1, col=1)
    fig.update_yaxes(title_text="细节能量占比 %", range=[0, max(d_vals + [1]) * 1.25], row=1, col=2)
    fig.update_layout(
        height=height,
        margin=dict(l=40, r=20, t=48, b=80),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", size=11, color="#1c1917"),
        showlegend=False,
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn" if include_plotlyjs else False)
