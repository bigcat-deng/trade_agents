"""Fund / amount wave surface: self rolling amount anomaly."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.db import (
    fetch_board_amount_named_window,
    fetch_board_bar_dates_ending,
    fetch_board_constituents_many,
)
from app.themes import list_themes
from app.themes.config import theme_board_codes
from app.themes.heat_forecast import tip_hottest_labels
from app.themes.heat_seriation import (
    DEFAULT_PLANE_DENSIFY,
    DEFAULT_SELF_ANOMALY_LOOKBACK,
    as_float,
    densify_hotness_plane,
    order_by_fused_seriation,
    order_by_trajectory_seriation,
    rolling_self_anomaly_grid,
    rolling_self_anomaly_series,
    select_top_codes_by_late_strength,
)

FUND_WAVE_WINDOW_DAYS = 40
FUND_CONCEPT_TOP_N = 200
FUND_CONCEPT_TRAJ_WEIGHT = 0.72
FUND_ANOMALY_LOOKBACK = DEFAULT_SELF_ANOMALY_LOOKBACK

INDUSTRY_FUND_AXIS_NOTE = (
    "横轴：全部行业板块，按窗口内成交额自身异常轨迹聚类叶序固定排列"
    "（共动近的挨在一起，整窗不逐日重排）；"
    f"颜色为 log(成交额) 相对近{FUND_ANOMALY_LOOKBACK}日自身均值的滚动 z"
    "（经 tanh 映到 0–1；越高=相对自身越异常放量）；"
    "进深为时间；末日前方红字=截止日自身异常最高的行业名。"
)

INDUSTRY_FUND_AXIS_NOTE_HEAT_ALIGN = (
    "横轴：与上方行业短热图同一叶序（列一一对应，便于对照）；"
    f"颜色为 log(成交额) 相对近{FUND_ANOMALY_LOOKBACK}日自身滚动 z"
    "（越高=相对自身越放量）；进深为时间；"
    "末日前方红字=截止日自身异常最高的行业名。"
)

CONCEPT_FUND_AXIS_NOTE = (
    f"横轴：近窗靠后四分之一成交额均值 Top{FUND_CONCEPT_TOP_N}"
    "∪ 全部主题分析概念；叶序=自身异常轨迹 + 成分/名称结构融合；"
    f"颜色为 log(成交额) 相对近{FUND_ANOMALY_LOOKBACK}日自身滚动 z（越高=相对自身越放量）；"
    "进深为时间；末日前方红字=自身异常最高概念名。"
)

CONCEPT_FUND_AXIS_NOTE_HEAT_ALIGN = (
    "横轴：与上方概念短热 Top∪主题图同一叶序（列一一对应，便于对照）；"
    f"颜色为 log(成交额) 相对近{FUND_ANOMALY_LOOKBACK}日自身滚动 z"
    "（越高=相对自身越放量）；进深为时间；"
    "末日前方红字=自身异常最高概念名。"
)


def _theme_member_codes() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for theme in list_themes():
        for code in theme_board_codes(theme):
            if code in seen:
                continue
            seen.add(code)
            ordered.append(code)
    return ordered


def _theme_ids_by_concept_code() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for theme in list_themes():
        for code in theme_board_codes(theme):
            out.setdefault(code, set()).add(theme.theme_id)
    return out


def _amount_maps(
    rows: list[tuple[date, str, str, object | None]],
) -> tuple[dict[date, dict[str, float]], dict[str, str]]:
    amount: dict[date, dict[str, float]] = {}
    names: dict[str, str] = {}
    for trade_date, board_code, board_name, raw in rows:
        code = str(board_code)
        if board_name:
            names[code] = str(board_name)
        val = as_float(raw)
        if val is None or val <= 0:
            continue
        amount.setdefault(trade_date, {})[code] = val
    return amount, names


def _history_dates_for_window(
    board_type: str,
    window: list[date],
    lookback: int = FUND_ANOMALY_LOOKBACK,
) -> list[date]:
    """Trading days covering lookback before window start through tip."""
    if not window:
        return []
    tip = window[-1]
    need = len(window) + max(2, lookback) + 5
    hist = fetch_board_bar_dates_ending(board_type, tip, need)
    if not hist:
        return list(window)
    # Ensure window days are included even if board_type calendar differs slightly.
    merged = sorted(set(hist) | set(window))
    return merged


def _build_plane(
    *,
    window_dates: list[date],
    history_dates: list[date],
    amount_by_day: dict[date, dict[str, float]],
    names: dict[str, str],
    ordered: list[str],
    densify: int,
    axis_note: str,
    lookback: int,
) -> dict[str, Any]:
    labels = [names.get(c, c) for c in ordered]
    z_native = rolling_self_anomaly_grid(
        window_dates=window_dates,
        history_dates=history_dates,
        ordered_codes=ordered,
        value_by_day=amount_by_day,
        lookback=lookback,
    )
    theme_x = [float(i) for i in range(len(ordered))]
    dense_x, dense_z = densify_hotness_plane(
        theme_x=theme_x, z_short=z_native, densify=densify
    )
    tip_labels = tip_hottest_labels(
        ordered_codes=ordered,
        names=labels,
        z_native=z_native,
        n_dates=len(window_dates),
        top_n=5,
    )
    return {
        "dates": [d.isoformat() for d in window_dates],
        "board_codes": ordered,
        "board_names": labels,
        "x": dense_x,
        "x_tickvals": theme_x,
        "x_ticktext": labels,
        "z_short": dense_z,
        "z_boards": z_native,
        "axis_note": axis_note,
        "as_of": window_dates[-1].isoformat() if window_dates else None,
        "board_count": len(ordered),
        "densify": densify,
        "lookback": lookback,
        "tip_labels": tip_labels,
        "empty_message": None,
    }


def build_industry_fund_plane(
    *,
    window_dates: list[date],
    amount_rows: list[tuple[date, str, str, object | None]],
    history_dates: list[date] | None = None,
    ordered_codes: list[str] | None = None,
    lookback: int = FUND_ANOMALY_LOOKBACK,
    densify: int = DEFAULT_PLANE_DENSIFY,
) -> dict[str, Any]:
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": INDUSTRY_FUND_AXIS_NOTE,
        "as_of": None,
        "board_count": 0,
        "densify": densify,
        "lookback": lookback,
        "tip_labels": {"x": [], "y": [], "text": [], "color": "#dc2626"},
        "empty_message": "没有可绘制的行业成交额窗口",
    }
    if not window_dates:
        return empty
    amount_by_day, names = _amount_maps(amount_rows)
    hist = list(history_dates) if history_dates else sorted(
        set(amount_by_day) | set(window_dates)
    )
    present = sorted(
        {c for day in window_dates for c in (amount_by_day.get(day) or {})}
    )
    frozen = [str(c) for c in (ordered_codes or []) if c]
    for code in present:
        names.setdefault(code, code)
    for code in frozen:
        names.setdefault(code, code)
    if frozen:
        ordered = frozen
        axis_note = INDUSTRY_FUND_AXIS_NOTE_HEAT_ALIGN
    else:
        if not present:
            return empty
        series = rolling_self_anomaly_series(
            window_dates=window_dates,
            history_dates=hist,
            codes=present,
            value_by_day=amount_by_day,
            lookback=lookback,
        )
        ordered = order_by_trajectory_seriation(present, series)
        axis_note = INDUSTRY_FUND_AXIS_NOTE
    return _build_plane(
        window_dates=window_dates,
        history_dates=hist,
        amount_by_day=amount_by_day,
        names=names,
        ordered=ordered,
        densify=densify,
        axis_note=axis_note,
        lookback=lookback,
    )


def build_concept_fund_plane(
    *,
    window_dates: list[date],
    amount_rows: list[tuple[date, str, str, object | None]],
    history_dates: list[date] | None = None,
    ordered_codes: list[str] | None = None,
    top_n: int = FUND_CONCEPT_TOP_N,
    lookback: int = FUND_ANOMALY_LOOKBACK,
    densify: int = DEFAULT_PLANE_DENSIFY,
) -> dict[str, Any]:
    axis_note = CONCEPT_FUND_AXIS_NOTE
    empty = {
        "dates": [],
        "board_codes": [],
        "board_names": [],
        "x": [],
        "x_tickvals": [],
        "x_ticktext": [],
        "z_short": [],
        "axis_note": axis_note,
        "as_of": None,
        "board_count": 0,
        "top_n": top_n,
        "top_count": 0,
        "theme_added": 0,
        "densify": densify,
        "lookback": lookback,
        "tip_labels": {"x": [], "y": [], "text": [], "color": "#dc2626"},
        "empty_message": "没有可绘制的概念成交额窗口",
    }
    if not window_dates:
        return empty
    amount_by_day, names = _amount_maps(amount_rows)
    hist = list(history_dates) if history_dates else sorted(
        set(amount_by_day) | set(window_dates)
    )
    all_codes = sorted(
        {c for day in window_dates for c in (amount_by_day.get(day) or {})}
    )
    for code in all_codes:
        names.setdefault(code, code)
    frozen = [str(c) for c in (ordered_codes or []) if c]
    if frozen:
        for code in frozen:
            names.setdefault(code, code)
        note = (
            f"横轴：与上方概念短热同一叶序，共 {len(frozen)} 列；"
            f"颜色为 log(成交额) 相对近{lookback}日自身滚动 z（越高=相对自身越放量）；"
            "进深为时间；末日前方红字=自身异常最高概念名。"
        )
        plane = _build_plane(
            window_dates=window_dates,
            history_dates=hist,
            amount_by_day=amount_by_day,
            names=names,
            ordered=frozen,
            densify=densify,
            axis_note=note,
            lookback=lookback,
        )
        plane["top_n"] = top_n
        plane["top_count"] = len(frozen)
        plane["theme_added"] = 0
        plane["heat_aligned"] = True
        return plane
    if not all_codes:
        return empty
    present = set(all_codes)
    candidates = list(all_codes)
    top_selected = select_top_codes_by_late_strength(
        window_dates=window_dates,
        value_by_day=amount_by_day,
        candidate_codes=candidates,
        top_n=top_n,
    )
    if not top_selected:
        return empty
    selected_set = set(top_selected)
    theme_added_codes: list[str] = []
    for code in _theme_member_codes():
        if code not in present or code in selected_set:
            continue
        selected_set.add(code)
        theme_added_codes.append(code)
    selected = list(top_selected) + theme_added_codes
    series = rolling_self_anomaly_series(
        window_dates=window_dates,
        history_dates=hist,
        codes=selected,
        value_by_day=amount_by_day,
        lookback=lookback,
    )
    as_of = window_dates[-1]
    constituents = fetch_board_constituents_many("concept", selected, as_of=as_of)
    ordered = order_by_fused_seriation(
        selected,
        series,
        names=names,
        constituents=constituents,
        theme_ids_by_code=_theme_ids_by_concept_code(),
        traj_weight=FUND_CONCEPT_TRAJ_WEIGHT,
    )
    note = (
        f"横轴：近窗靠后四分之一成交额均值 Top{top_n}"
        f"（实取 {len(top_selected)}）"
        f"∪ 主题概念（补入 {len(theme_added_codes)}），合计 {len(ordered)} 列；"
        "叶序=自身异常轨迹 + 成分/名称结构融合；"
        f"颜色为 log(成交额) 相对近{lookback}日自身滚动 z（越高=相对自身越放量）；"
        "进深为时间；末日前方红字=自身异常最高概念名。"
    )
    plane = _build_plane(
        window_dates=window_dates,
        history_dates=hist,
        amount_by_day=amount_by_day,
        names=names,
        ordered=ordered,
        densify=densify,
        axis_note=note,
        lookback=lookback,
    )
    plane["top_n"] = top_n
    plane["top_count"] = len(top_selected)
    plane["theme_added"] = len(theme_added_codes)
    return plane


FUND_WAVE_PANELS = frozenset({"industry", "concept"})


def _resolve_fund_tip_window(
    *,
    as_of: date | None,
    days: int,
) -> tuple[date | None, list[date], str | None]:
    """Return (tip, window_dates, error)."""
    requested = as_of or date.today()
    tip_days = fetch_board_bar_dates_ending("industry", requested, 1)
    if not tip_days:
        tip_days = fetch_board_bar_dates_ending("concept", requested, 1)
    if not tip_days:
        return None, [], "没有可用的板块成交额截止日。"
    tip = tip_days[-1]
    window = fetch_board_bar_dates_ending("industry", tip, days)
    if len(window) < 5:
        window = fetch_board_bar_dates_ending("concept", tip, days)
    if len(window) < 5:
        return tip, [], "成交额历史不足，无法绘制资金水面。"
    return tip, window, None


def build_fund_wave_panel_payload(
    *,
    panel: str,
    as_of: date | None,
    days: int = FUND_WAVE_WINDOW_DAYS,
    ordered_codes: list[str] | None = None,
    include_plotlyjs: bool = False,
    height: int = 520,
) -> dict[str, Any]:
    """JSON panel for lazy embed: industry or concept self-anomaly wave.

    When ``ordered_codes`` is provided (theme-wave heat leaf order), the X axis
    is frozen to that sequence so fund and heat charts line up column-wise.
    """
    from app.charts.theme_wave import render_theme_wave_contour

    panel_key = str(panel or "").strip().lower()
    requested = as_of or date.today()
    frozen = [str(c) for c in (ordered_codes or []) if c]
    out: dict[str, Any] = {
        "panel": panel_key,
        "as_of": None,
        "requested_as_of": requested.isoformat(),
        "days": days,
        "window_start": None,
        "window_end": None,
        "note": "",
        "html": "",
        "error": None,
        "heat_aligned": bool(frozen),
        "board_codes": frozen,
    }
    if panel_key not in FUND_WAVE_PANELS:
        out["error"] = "unknown panel"
        return out
    tip, window, err = _resolve_fund_tip_window(as_of=as_of, days=days)
    if err or tip is None or not window:
        out["error"] = err or "资金水面暂不可用。"
        return out
    out["as_of"] = tip.isoformat()
    out["window_start"] = window[0].isoformat()
    out["window_end"] = window[-1].isoformat()

    if panel_key == "industry":
        hist = _history_dates_for_window("industry", window)
        rows = fetch_board_amount_named_window("industry", hist[0], tip)
        plane = build_industry_fund_plane(
            window_dates=window,
            amount_rows=rows,
            history_dates=hist,
            ordered_codes=frozen or None,
        )
        default_note = (
            INDUSTRY_FUND_AXIS_NOTE_HEAT_ALIGN if frozen else INDUSTRY_FUND_AXIS_NOTE
        )
        title = "行业资金水面 · 成交额自身异常"
        xaxis_title = (
            "行业（与热度叶序对齐）" if frozen else "行业（自身异常叶序）"
        )
        entity_label = "行业"
    else:
        hist = _history_dates_for_window("concept", window)
        rows = fetch_board_amount_named_window("concept", hist[0], tip)
        plane = build_concept_fund_plane(
            window_dates=window,
            amount_rows=rows,
            history_dates=hist,
            ordered_codes=frozen or None,
        )
        default_note = (
            CONCEPT_FUND_AXIS_NOTE_HEAT_ALIGN if frozen else CONCEPT_FUND_AXIS_NOTE
        )
        title = "概念资金水面 · 成交额自身异常（Top∪主题）"
        xaxis_title = (
            "概念（与热度叶序对齐）"
            if frozen
            else "概念（自身异常叶序 · Top∪主题）"
        )
        entity_label = "概念"

    if plane.get("empty_message"):
        out["error"] = str(plane["empty_message"])
        out["note"] = default_note
        return out
    out["note"] = str(plane.get("axis_note") or default_note)
    out["board_codes"] = list(plane.get("board_codes") or frozen)
    out["html"] = render_theme_wave_contour(
        dates=plane["dates"],
        x=plane["x"],
        z=plane["z_short"],
        x_tickvals=plane["x_tickvals"],
        x_ticktext=plane["x_ticktext"],
        include_plotlyjs=include_plotlyjs,
        height=height,
        title=title,
        xaxis_title=xaxis_title,
        entity_label=entity_label,
        tickangle=-45,
        tip_labels=plane.get("tip_labels"),
        show_colorbar=False,
    )
    return out


def build_fund_wave_page_payload(
    *,
    as_of: date | None,
    days: int = FUND_WAVE_WINDOW_DAYS,
    include_plotlyjs: bool = False,
) -> dict[str, Any]:
    """Page payload: industry + concept self-anomaly amount wave charts."""
    requested = as_of or date.today()
    tip, window, err = _resolve_fund_tip_window(as_of=as_of, days=days)
    base = {
        "title": "资金水面",
        "as_of": tip.isoformat() if tip else None,
        "requested_as_of": requested.isoformat(),
        "days": days,
        "window_start": window[0].isoformat() if window else None,
        "window_end": window[-1].isoformat() if window else None,
        "industry_html": "",
        "concept_html": "",
        "industry_note": INDUSTRY_FUND_AXIS_NOTE,
        "concept_note": CONCEPT_FUND_AXIS_NOTE,
        "industry_empty": "",
        "concept_empty": "",
        "empty_message": err,
        "include_plotlyjs": include_plotlyjs,
        "heat_wave_href": "/boards/concept/themes/wave",
    }
    if err or tip is None or not window:
        return base
    base["heat_wave_href"] = f"/boards/concept/themes/wave?as_of={tip.isoformat()}"

    ind = build_fund_wave_panel_payload(
        panel="industry",
        as_of=tip,
        days=days,
        include_plotlyjs=include_plotlyjs,
        height=560,
    )
    if ind.get("error"):
        base["industry_empty"] = str(ind["error"])
    else:
        base["industry_note"] = ind.get("note") or INDUSTRY_FUND_AXIS_NOTE
        base["industry_html"] = ind.get("html") or ""

    con = build_fund_wave_panel_payload(
        panel="concept",
        as_of=tip,
        days=days,
        include_plotlyjs=False,
        height=560,
    )
    if con.get("error"):
        base["concept_empty"] = str(con["error"])
    else:
        base["concept_note"] = con.get("note") or CONCEPT_FUND_AXIS_NOTE
        base["concept_html"] = con.get("html") or ""
    return base
