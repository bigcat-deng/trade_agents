"""Build a theme × time heat surface for the 3D wave overview."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from statistics import median

from app.themes import list_themes
from app.themes.badges import percentiles_from_heats
from app.themes.config import ThemeConfig
from app.themes.wave_order import (
    RANK_AXIS_NOTE,
    SPECTRUM_AXIS_NOTE,
    SPECTRUM_THEME_IDS,
)


def _as_float(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _group_a_hotness(
    heats: dict[str, float],
    percentiles: dict[str, float],
    codes: list[str],
) -> float | None:
    """Market percentile of group A, flipped so 1 = hottest."""
    vals = [percentiles[code] for code in codes if code in percentiles and code in heats]
    if not vals:
        return None
    return 1.0 - float(median(vals))


def _interp_row(values: list[float | None], densify: int) -> list[float | None]:
    """Linear-interpolate along theme axis; densify subdivides each gap."""
    if densify < 1 or len(values) < 2:
        return list(values)
    out: list[float | None] = []
    for i, left in enumerate(values[:-1]):
        right = values[i + 1]
        out.append(left)
        for step in range(1, densify):
            t = step / densify
            if left is None or right is None:
                out.append(None)
            else:
                out.append(left * (1.0 - t) + right * t)
    out.append(values[-1])
    return out


def _fill_time_gaps(grid: list[list[float | None]]) -> list[list[float | None]]:
    if not grid:
        return grid
    cols = len(grid[0])
    out = [list(row) for row in grid]
    for c in range(cols):
        last: float | None = None
        for r in range(len(out)):
            if out[r][c] is None:
                out[r][c] = last
            else:
                last = out[r][c]
        last = None
        for r in range(len(out) - 1, -1, -1):
            if out[r][c] is None:
                out[r][c] = last
            else:
                last = out[r][c]
    return out


def _spectrum_themes() -> list[ThemeConfig]:
    themes_by_id = {theme.theme_id: theme for theme in list_themes()}
    ordered: list[ThemeConfig] = []
    for theme_id in SPECTRUM_THEME_IDS:
        theme = themes_by_id.get(theme_id)
        if theme is not None:
            ordered.append(theme)
    known = set(SPECTRUM_THEME_IDS)
    for theme in list_themes():
        if theme.theme_id not in known:
            ordered.append(theme)
    return ordered


def _theme_label(theme: ThemeConfig) -> str:
    return theme.title.replace("主题域", "")


def _surface_for_order(
    *,
    ordered: list[ThemeConfig],
    window_dates: list[date],
    heat_by_day: dict[date, dict[str, float]],
    densify: int,
    axis_note: str,
    as_of_hotness: dict[str, float | None] | None = None,
) -> dict:
    theme_codes = {
        theme.theme_id: [board.board_code for board in theme.group_a]
        for theme in ordered
    }
    theme_labels = [_theme_label(theme) for theme in ordered]
    theme_ids = [theme.theme_id for theme in ordered]
    theme_x = [float(i) for i in range(len(ordered))]

    grid: list[list[float | None]] = []
    for day in window_dates:
        heats = heat_by_day.get(day, {})
        pct = percentiles_from_heats(heats)
        row = [
            _group_a_hotness(heats, pct, theme_codes[theme.theme_id])
            for theme in ordered
        ]
        grid.append(row)

    dense_x: list[float] = []
    steps = max(1, densify)
    for i in range(len(theme_x) - 1):
        dense_x.append(theme_x[i])
        for step in range(1, steps):
            dense_x.append(theme_x[i] + step / steps)
    if theme_x:
        dense_x.append(theme_x[-1])

    dense_z = [_interp_row(row, steps) for row in grid]
    filled = _fill_time_gaps(dense_z)

    rank_meta = None
    if as_of_hotness is not None:
        rank_meta = [
            {
                "theme_id": theme.theme_id,
                "label": _theme_label(theme),
                "hotness": as_of_hotness.get(theme.theme_id),
            }
            for theme in ordered
        ]

    return {
        "dates": [day.isoformat() for day in window_dates],
        "theme_ids": theme_ids,
        "theme_labels": theme_labels,
        "theme_x": theme_x,
        "theme_hrefs": [f"/boards/concept/themes/{tid}" for tid in theme_ids],
        "x": dense_x,
        "x_tickvals": theme_x,
        "x_ticktext": theme_labels,
        "z": filled,
        "raw_z": grid,
        "axis_note": axis_note,
        "rank_meta": rank_meta,
        "densify": steps,
    }


def build_theme_wave_payload(
    *,
    window_dates: list[date],
    heat_rows: list[tuple[date, str, object | None]],
    densify: int = 4,
) -> dict:
    """Return spectrum + mid-window-rank surfaces.

    Height is group-A median hotness in [0, 1] (1 = hottest among concepts that day).
    Rank surface X order is fixed by mid-window-day hotness (hottest → left), then
    the whole window is drawn in that fixed order.
    """
    ordered_spectrum = _spectrum_themes()
    empty = {
        "dates": [],
        "spectrum": None,
        "ranked": None,
        "axis_note": SPECTRUM_AXIS_NOTE,
        "rank_axis_note": RANK_AXIS_NOTE,
        "empty_message": "没有可绘制的主题热度窗口",
    }
    if not window_dates or not ordered_spectrum:
        return empty

    heat_by_day: dict[date, dict[str, float]] = {}
    for trade_date, board_code, heat_short in heat_rows:
        value = _as_float(heat_short)
        if value is None:
            continue
        heat_by_day.setdefault(trade_date, {})[board_code] = value

    as_of = window_dates[-1]
    # Mid trading day of the window (e.g. day 20 of 40 → index 19).
    rank_as_of = window_dates[(len(window_dates) - 1) // 2]
    rank_heats = heat_by_day.get(rank_as_of, {})
    rank_pct = percentiles_from_heats(rank_heats)
    rank_hotness: dict[str, float | None] = {}
    for theme in ordered_spectrum:
        codes = [board.board_code for board in theme.group_a]
        rank_hotness[theme.theme_id] = _group_a_hotness(rank_heats, rank_pct, codes)

    def _rank_key(theme: ThemeConfig) -> tuple[int, float, str]:
        hot = rank_hotness.get(theme.theme_id)
        # Hottest first; missing heats sink to the right.
        if hot is None:
            return (1, 0.0, theme.theme_id)
        return (0, -hot, theme.theme_id)

    ordered_ranked = sorted(ordered_spectrum, key=_rank_key)

    spectrum = _surface_for_order(
        ordered=ordered_spectrum,
        window_dates=window_dates,
        heat_by_day=heat_by_day,
        densify=densify,
        axis_note=SPECTRUM_AXIS_NOTE,
    )
    ranked = _surface_for_order(
        ordered=ordered_ranked,
        window_dates=window_dates,
        heat_by_day=heat_by_day,
        densify=densify,
        axis_note=RANK_AXIS_NOTE,
        as_of_hotness=rank_hotness,
    )

    return {
        "dates": spectrum["dates"],
        "spectrum": spectrum,
        "ranked": ranked,
        "axis_note": SPECTRUM_AXIS_NOTE,
        "rank_axis_note": RANK_AXIS_NOTE,
        "as_of": as_of.isoformat(),
        "rank_as_of": rank_as_of.isoformat(),
        "empty_message": None,
        "densify": densify,
        # Back-compat fields for callers expecting the spectrum surface at top level.
        "theme_ids": spectrum["theme_ids"],
        "theme_labels": spectrum["theme_labels"],
        "theme_hrefs": spectrum["theme_hrefs"],
        "x": spectrum["x"],
        "x_tickvals": spectrum["x_tickvals"],
        "x_ticktext": spectrum["x_ticktext"],
        "z": spectrum["z"],
    }
