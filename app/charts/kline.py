"""Reusable candlestick chart renderer."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


REQUIRED_FIELDS = ("trade_date", "open", "high", "low", "close")
PRICE_VOLUME_BINS = 20

BB_PERIOD = 20
BB_STD = 2.0
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


def _as_dataframe(bars: Sequence[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(bars, pd.DataFrame):
        frame = bars.copy()
    else:
        frame = pd.DataFrame(list(bars))

    missing = [name for name in REQUIRED_FIELDS if name not in frame.columns]
    if missing:
        raise ValueError(f"kline data missing required fields: {missing}")

    frame = frame.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.dropna(subset=["trade_date", "open", "high", "low", "close"])
    frame = frame.sort_values("trade_date").reset_index(drop=True)
    return frame


def _has_volume(frame: pd.DataFrame) -> bool:
    if "volume" not in frame.columns:
        return False
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    return bool(volume.notna().any() and (volume.fillna(0) > 0).any())


def _bollinger(
    close: pd.Series,
    *,
    period: int = BB_PERIOD,
    num_std: float = BB_STD,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid, upper, lower


def _macd(
    close: pd.Series,
    *,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = dif - dea
    return dif, dea, hist


def _price_volume_profile(
    frame: pd.DataFrame, bins: int = PRICE_VOLUME_BINS
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Accumulate volume across equal price bins covered by each bar's low-high."""
    lows = pd.to_numeric(frame["low"], errors="coerce")
    highs = pd.to_numeric(frame["high"], errors="coerce")
    volumes = pd.to_numeric(frame["volume"], errors="coerce")

    price_min = float(lows.min())
    price_max = float(highs.max())
    if not np.isfinite(price_min) or not np.isfinite(price_max):
        raise ValueError("invalid price range for volume profile")
    if price_max <= price_min:
        price_max = price_min + 1e-6

    edges = np.linspace(price_min, price_max, bins + 1)
    accumulated = np.zeros(bins, dtype=float)

    for low, high, volume in zip(lows, highs, volumes, strict=False):
        if pd.isna(low) or pd.isna(high) or pd.isna(volume) or volume <= 0:
            continue
        low_v = float(low)
        high_v = float(high)
        if high_v < low_v:
            low_v, high_v = high_v, low_v

        covered: list[int] = []
        for index in range(bins):
            bin_low = edges[index]
            bin_high = edges[index + 1]
            # Last bin is closed on the right so max price is included.
            if index < bins - 1:
                overlaps = high_v >= bin_low and low_v < bin_high
            else:
                overlaps = high_v >= bin_low and low_v <= bin_high
            if overlaps:
                covered.append(index)

        if not covered:
            # Degenerate point: put all volume into the nearest bin.
            nearest = int(np.clip(np.searchsorted(edges, low_v, side="right") - 1, 0, bins - 1))
            covered = [nearest]

        share = float(volume) / len(covered)
        for index in covered:
            accumulated[index] += share

    mids = (edges[:-1] + edges[1:]) / 2.0
    return mids, accumulated, price_min, price_max


def _add_bollinger_traces(
    fig: go.Figure,
    frame: pd.DataFrame,
    mid: pd.Series,
    upper: pd.Series,
    lower: pd.Series,
    *,
    row: int | None,
    col: int | None,
) -> None:
    kwargs: dict[str, Any] = {}
    if row is not None and col is not None:
        kwargs = {"row": row, "col": col}

    fig.add_trace(
        go.Scatter(
            x=frame["trade_date"],
            y=upper,
            name="BB Upper",
            line=dict(color="rgba(37, 99, 235, 0.45)", width=1),
            hoverinfo="skip",
        ),
        **kwargs,
    )
    fig.add_trace(
        go.Scatter(
            x=frame["trade_date"],
            y=lower,
            name="BB Lower",
            line=dict(color="rgba(37, 99, 235, 0.45)", width=1),
            fill="tonexty",
            fillcolor="rgba(37, 99, 235, 0.08)",
            hoverinfo="skip",
        ),
        **kwargs,
    )
    fig.add_trace(
        go.Scatter(
            x=frame["trade_date"],
            y=mid,
            name="BB Mid",
            line=dict(color="rgba(37, 99, 235, 0.8)", width=1.2),
            hoverinfo="skip",
        ),
        **kwargs,
    )


def _add_macd_traces(
    fig: go.Figure,
    frame: pd.DataFrame,
    dif: pd.Series,
    dea: pd.Series,
    hist: pd.Series,
    *,
    row: int,
    col: int,
) -> None:
    hist_colors = [
        "#dc2626" if (pd.notna(value) and value >= 0) else "#16a34a" for value in hist
    ]
    fig.add_trace(
        go.Bar(
            x=frame["trade_date"],
            y=hist,
            name="MACD Hist",
            marker_color=hist_colors,
            opacity=0.75,
        ),
        row=row,
        col=col,
    )
    fig.add_trace(
        go.Scatter(
            x=frame["trade_date"],
            y=dif,
            name="DIF",
            line=dict(color="#2563eb", width=1.2),
        ),
        row=row,
        col=col,
    )
    fig.add_trace(
        go.Scatter(
            x=frame["trade_date"],
            y=dea,
            name="DEA",
            line=dict(color="#ea580c", width=1.2),
        ),
        row=row,
        col=col,
    )
    fig.update_yaxes(title_text="MACD", row=row, col=col)
    fig.update_xaxes(rangeslider_visible=False, row=row, col=col)


def _finite_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _scaled_heat_series(
    frame: pd.DataFrame,
    heats: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[float | None], list[float | None], list[float | None], list[float | None]] | None:
    """Map negated short and long heat onto 0%–80% of this chart's volume.

    Smaller heat is hotter, so the series is negated before scaling. Both lines
    share one scale. A series that is entirely missing is returned as None.
    """
    if not heats:
        return None
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    volume_max = float(volume.max(skipna=True)) if volume.notna().any() else float("nan")
    if not np.isfinite(volume_max) or volume_max <= 0:
        return None

    by_date: dict[pd.Timestamp, Mapping[str, Any]] = {}
    for row in heats:
        day = pd.to_datetime(row.get("trade_date"), errors="coerce")
        if pd.isna(day):
            continue
        by_date[pd.Timestamp(day).normalize()] = row

    short: list[float | None] = []
    long: list[float | None] = []
    for day in frame["trade_date"]:
        row = by_date.get(pd.Timestamp(day).normalize())
        if row is None:
            short.append(None)
            long.append(None)
            continue
        short.append(_finite_number(row.get("heat_short")))
        long.append(_finite_number(row.get("heat_long")))

    negated = [-value for value in (*short, *long) if value is not None]
    if not negated:
        return None
    neg_min = min(negated)
    neg_max = max(negated)
    span = neg_max - neg_min
    ceiling = volume_max * 0.8

    def scale(series: list[float | None]) -> list[float | None] | None:
        if all(value is None for value in series):
            return None
        scaled: list[float | None] = []
        for value in series:
            if value is None:
                scaled.append(None)
                continue
            if span == 0:
                scaled.append(ceiling / 2)
                continue
            scaled.append(((-value - neg_min) / span) * ceiling)
        return scaled

    return short, long, scale(short), scale(long)


def _add_heat_traces(
    fig: go.Figure,
    frame: pd.DataFrame,
    heats: Sequence[Mapping[str, Any]] | None,
    *,
    row: int,
    col: int,
) -> None:
    scaled = _scaled_heat_series(frame, heats)
    if scaled is None:
        return
    short, long, scaled_short, scaled_long = scaled
    specs = (
        ("短期热度", scaled_short, short, "#dc2626"),
        ("长期热度", scaled_long, long, "#2563eb"),
    )
    for name, y_values, original, color in specs:
        if y_values is None:
            continue
        fig.add_trace(
            go.Scatter(
                x=frame["trade_date"],
                y=y_values,
                name=name,
                mode="lines",
                connectgaps=False,
                line=dict(color=color, width=1.6),
                customdata=original,
                hovertemplate=name + " %{customdata:.2f}<extra></extra>",
            ),
            row=row,
            col=col,
        )


def build_kline_figure(
    bars: Sequence[Mapping[str, Any]] | pd.DataFrame,
    *,
    title: str | None = None,
    code: str | None = None,
    height: int | None = None,
    bollinger: bool = True,
    macd: bool = True,
    bb_period: int = BB_PERIOD,
    bb_std: float = BB_STD,
    macd_fast: int = MACD_FAST,
    macd_slow: int = MACD_SLOW,
    macd_signal: int = MACD_SIGNAL,
    heats: Sequence[Mapping[str, Any]] | None = None,
) -> go.Figure:
    frame = _as_dataframe(bars)
    if frame.empty:
        raise ValueError("kline data is empty after cleaning")

    show_volume = _has_volume(frame)
    chart_title = title or code or "K线"
    close = frame["close"]

    bb_mid = bb_upper = bb_lower = None
    if bollinger:
        bb_mid, bb_upper, bb_lower = _bollinger(
            close, period=bb_period, num_std=bb_std
        )

    dif = dea = hist = None
    if macd:
        dif, dea, hist = _macd(
            close, fast=macd_fast, slow=macd_slow, signal=macd_signal
        )

    if height is None:
        if show_volume and macd:
            height = 640
        elif show_volume or macd:
            height = 560
        else:
            height = 480

    candle = go.Candlestick(
        x=frame["trade_date"],
        open=frame["open"],
        high=frame["high"],
        low=frame["low"],
        close=frame["close"],
        name="OHLC",
        increasing_line_color="#dc2626",
        increasing_fillcolor="#dc2626",
        decreasing_line_color="#16a34a",
        decreasing_fillcolor="#16a34a",
    )

    select_xrefs: list[str]

    if show_volume:
        mids, profile, price_min, price_max = _price_volume_profile(frame)
        if bollinger and bb_upper is not None and bb_lower is not None:
            upper_max = bb_upper.max(skipna=True)
            lower_min = bb_lower.min(skipna=True)
            if pd.notna(upper_max):
                price_max = max(price_max, float(upper_max))
            if pd.notna(lower_min):
                price_min = min(price_min, float(lower_min))

        if macd:
            fig = make_subplots(
                rows=3,
                cols=2,
                column_widths=[0.18, 0.82],
                row_heights=[0.52, 0.22, 0.26],
                shared_xaxes=False,
                vertical_spacing=0.03,
                horizontal_spacing=0.02,
                specs=[
                    [{"type": "xy"}, {"type": "xy"}],
                    [None, {"type": "xy"}],
                    [None, {"type": "xy"}],
                ],
            )
            volume_row, macd_row = 2, 3
            select_xrefs = ["x2", "x3", "x4"]
        else:
            fig = make_subplots(
                rows=2,
                cols=2,
                column_widths=[0.18, 0.82],
                row_heights=[0.72, 0.28],
                shared_xaxes=False,
                vertical_spacing=0.04,
                horizontal_spacing=0.02,
                specs=[
                    [{"type": "xy"}, {"type": "xy"}],
                    [None, {"type": "xy"}],
                ],
            )
            volume_row, macd_row = 2, None
            select_xrefs = ["x2", "x3"]

        fig.add_trace(
            go.Bar(
                x=profile,
                y=mids,
                orientation="h",
                name="Price Volume",
                marker=dict(color="rgba(37, 99, 235, 0.35)", line=dict(width=0)),
                hoverinfo="none",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(candle, row=1, col=2)
        if bollinger and bb_mid is not None:
            _add_bollinger_traces(
                fig, frame, bb_mid, bb_upper, bb_lower, row=1, col=2
            )

        colors = [
            "#dc2626" if close_v >= open_v else "#16a34a"
            for open_v, close_v in zip(frame["open"], frame["close"], strict=False)
        ]
        fig.add_trace(
            go.Bar(
                x=frame["trade_date"],
                y=pd.to_numeric(frame["volume"], errors="coerce"),
                name="Volume",
                marker_color=colors,
                opacity=0.7,
            ),
            row=volume_row,
            col=2,
        )
        _add_heat_traces(fig, frame, heats, row=volume_row, col=2)

        padding = (price_max - price_min) * 0.02
        price_range = [price_min - padding, price_max + padding]
        fig.update_yaxes(range=price_range, title_text="Price", row=1, col=1)
        fig.update_yaxes(range=price_range, title_text="Price", row=1, col=2)
        fig.update_yaxes(title_text="Volume", row=volume_row, col=2)
        fig.update_xaxes(
            title_text="Vol",
            row=1,
            col=1,
            showticklabels=False,
            autorange="reversed",
        )
        fig.update_xaxes(rangeslider_visible=False, row=1, col=2)
        fig.update_xaxes(rangeslider_visible=False, row=volume_row, col=2)

        if macd and macd_row is not None and dif is not None:
            _add_macd_traces(fig, frame, dif, dea, hist, row=macd_row, col=2)
    else:
        if macd:
            fig = make_subplots(
                rows=2,
                cols=1,
                row_heights=[0.7, 0.3],
                shared_xaxes=True,
                vertical_spacing=0.04,
            )
            fig.add_trace(candle, row=1, col=1)
            if bollinger and bb_mid is not None:
                _add_bollinger_traces(
                    fig, frame, bb_mid, bb_upper, bb_lower, row=1, col=1
                )
            fig.update_yaxes(title_text="Price", row=1, col=1)
            fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
            _add_macd_traces(fig, frame, dif, dea, hist, row=2, col=1)
            select_xrefs = ["x", "x2"]
        else:
            fig = go.Figure()
            fig.add_trace(candle)
            if bollinger and bb_mid is not None:
                _add_bollinger_traces(
                    fig, frame, bb_mid, bb_upper, bb_lower, row=None, col=None
                )
            fig.update_yaxes(title_text="Price")
            fig.update_xaxes(rangeslider_visible=False)
            select_xrefs = ["x"]

    fig.update_layout(
        title=chart_title,
        height=height,
        margin=dict(l=40, r=20, t=50, b=30),
        paper_bgcolor="#fffdf8",
        plot_bgcolor="#fffdf8",
        font=dict(family="IBM Plex Sans, Noto Sans SC, sans-serif", color="#1c1917"),
        showlegend=False,
        barmode="relative",
        clickmode="event",
        meta={"select_xrefs": select_xrefs},
    )
    fig.update_xaxes(showgrid=True, gridcolor="#e7e5e4")
    fig.update_yaxes(showgrid=True, gridcolor="#e7e5e4")
    return fig


_PROFILE_AND_SELECT_SCRIPT = """
var gd = document.getElementById('{plot_id}');
if (gd) {
  var selectXrefs = {select_xrefs_json};
  gd._klineSelectX = null;
  gd._klineHoverY = null;

  function buildShapes() {
    var shapes = [];
    if (gd._klineSelectX != null) {
      for (var i = 0; i < selectXrefs.length; i++) {
        var xref = selectXrefs[i];
        var yAxis = xref === 'x' ? 'y' : ('y' + xref.slice(1));
        shapes.push({
          type: 'line',
          xref: xref,
          yref: yAxis + ' domain',
          x0: gd._klineSelectX,
          x1: gd._klineSelectX,
          y0: 0,
          y1: 1,
          line: {color: 'rgba(15, 23, 42, 0.85)', width: 1.2, dash: 'dot'},
          layer: 'above'
        });
      }
    }
    if (gd._klineHoverY != null) {
      shapes.push({
        type: 'line',
        xref: 'x2 domain',
        yref: 'y2',
        x0: 0,
        x1: 1,
        y0: gd._klineHoverY,
        y1: gd._klineHoverY,
        line: {color: 'rgba(37, 99, 235, 0.75)', width: 1},
        layer: 'above'
      });
    }
    return shapes;
  }

  function applyShapes() {
    Plotly.relayout(gd, {shapes: buildShapes()});
  }

  gd.on('plotly_click', function(data) {
    var pt = data.points && data.points[0];
    if (!pt || !pt.data || pt.data.name === 'Price Volume') {
      return;
    }
    if (pt.x == null) {
      return;
    }
    gd._klineSelectX = pt.x;
    applyShapes();
  });

  gd.on('plotly_hover', function(data) {
    var pt = data.points && data.points[0];
    if (!pt || !pt.data || pt.data.name !== 'Price Volume') {
      return;
    }
    gd._klineHoverY = pt.y;
    applyShapes();
  });

  gd.on('plotly_unhover', function(data) {
    var pt = data.points && data.points[0];
    if (pt && pt.data && pt.data.name === 'Price Volume') {
      gd._klineHoverY = null;
      applyShapes();
    }
  });
}
"""


def _select_xrefs_for_figure(figure: go.Figure) -> list[str]:
    meta = figure.layout.meta or {}
    if isinstance(meta, dict):
        refs = meta.get("select_xrefs")
        if isinstance(refs, (list, tuple)) and refs:
            return [str(item) for item in refs]
    return ["x"]


def render_kline(
    bars: Sequence[Mapping[str, Any]] | pd.DataFrame,
    *,
    title: str | None = None,
    code: str | None = None,
    height: int | None = None,
    bollinger: bool = True,
    macd: bool = True,
    heats: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Return embeddable HTML for a candlestick chart."""
    figure = build_kline_figure(
        bars,
        title=title,
        code=code,
        height=height,
        bollinger=bollinger,
        macd=macd,
        heats=heats,
    )
    xrefs = _select_xrefs_for_figure(figure)
    post_script = _PROFILE_AND_SELECT_SCRIPT.replace(
        "{select_xrefs_json}", json.dumps(xrefs)
    )
    return figure.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": False},
        post_script=post_script,
    )
