"""Industry/concept short-heat 5-day forecast page payloads (slope + CWT)."""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from typing import Any

from jinja2 import StrictUndefined, Template

from app.db import (
    fetch_concept_heat_named_window,
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
    fetch_trading_dates_after,
    fetch_trading_dates_ending,
)
from app.interpret.industry_heat import model_settings
from app.prompts.template import PromptTemplate, load_prompt
from app.themes.heat_forecast import (
    FORECAST_CONTEXT_DAYS,
    FORECAST_DAYS,
    FORECAST_HISTORY_DAYS,
    build_industry_heat_forecast_payload,
    resolve_forecast_dates,
    tip_hottest_labels,
)
from app.themes.heat_rim_regime import (
    REGIME_DISPLAY_DAYS,
    REGIME_PLANE_WINDOW,
    REGIME_WARMUP_DAYS,
    build_regime_panel_payload,
)
from app.themes.heat_seriation import (
    as_float,
    hotness_series_by_code,
    order_by_trajectory_seriation,
)

TEMPLATE_NAME = "industry-heat-forecast"
HOTTEST_N = 15
COOLEST_N = 8
RECENT_DAYS = 5
RECENT_TOP_N = 6


def build_industry_heat_forecast_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date, dict[str, Any]]:
    """Load template and fill with live industry short-heat context."""
    template = load_prompt(TEMPLATE_NAME)
    forecast_n = int(template.config.get("forecast_trading_days") or FORECAST_DAYS)
    recent_window = int(template.config.get("window_trading_days") or 40)

    tip_dates = fetch_heat_dates_ending("industry", as_of or date.today(), 1)
    if not tip_dates:
        raise RuntimeError("no industry heat rows for forecast prompt")
    tip = tip_dates[-1]

    hist = fetch_heat_dates_ending("industry", tip, max(recent_window, RECENT_DAYS + 1))
    if not hist:
        raise RuntimeError("no industry heat history for forecast prompt")
    rows = fetch_industry_heat_window(hist[0], tip)
    heat, names = _heat_maps(rows)
    if tip not in heat:
        raise RuntimeError(f"no industry heat on as_of {tip}")

    known_fwd = fetch_trading_dates_after("industry", tip, forecast_n)
    forecast_dates = resolve_forecast_dates(
        as_of=tip, n=forecast_n, known_forward=known_fwd
    )
    tip_ranked = sorted(heat[tip].items(), key=lambda kv: kv[1])
    hottest = tip_ranked[:HOTTEST_N]
    coolest = tip_ranked[-COOLEST_N:]
    recent = hist[-RECENT_DAYS:]
    recent_lines = []
    for day in recent:
        top = sorted((heat.get(day) or {}).items(), key=lambda kv: kv[1])[:RECENT_TOP_N]
        recent_lines.append(
            f"{day.isoformat()}: "
            + ", ".join(names.get(code, code) for code, _ in top)
        )

    regime_summary = _regime_summary_line(tip)
    body = Template(template.body, undefined=StrictUndefined).render(
        as_of=tip.isoformat(),
        forecast_trading_days=len(forecast_dates),
        forecast_dates=", ".join(d.isoformat() for d in forecast_dates),
        regime_summary=regime_summary,
        hottest_n=len(hottest),
        coolest_n=len(coolest),
        hottest_list=", ".join(
            f"{names.get(code, code)}({val:.1f})" for code, val in hottest
        ),
        coolest_list=", ".join(
            f"{names.get(code, code)}({val:.1f})" for code, val in coolest
        ),
        recent_n=len(recent),
        recent_top_n=RECENT_TOP_N,
        recent_top_block="\n".join(recent_lines),
    )
    ctx = {
        "tip": tip,
        "forecast_dates": forecast_dates,
        "heat": heat,
        "names": names,
        "hist": hist,
    }
    return template, body, tip, ctx


def call_forecast_llm(prompt: str, template: PromptTemplate) -> tuple[dict[str, Any], str]:
    """Call OpenAI-compatible chat; return parsed JSON scenario and model id."""
    settings = model_settings(template)
    missing = [k for k in ("base_url", "model", "api_key") if not settings.get(k)]
    if missing:
        raise RuntimeError(f"LLM settings missing: {', '.join(missing)}")
    base = settings["base_url"].rstrip("/")
    payload = json.dumps(
        {
            "model": settings["model"],
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    model_id = str(body.get("model") or settings["model"])
    scenario = json.loads(content)
    if not isinstance(scenario, dict):
        raise RuntimeError("LLM forecast reply is not a JSON object")
    return scenario, model_id


def build_llm_forecast_plane(
    *,
    tip: date,
    hist: list[date],
    heat: dict[date, dict[str, float]],
    names: dict[str, str],
    forecast_dates: list[date],
    scenario: dict[str, Any],
    ordered_codes: list[str] | None = None,
) -> dict[str, Any]:
    """Color a forecast plane from LLM warm/cool lists (same leaf order as tip)."""
    codes = sorted({c for day in hist for c in (heat.get(day) or {})})
    if not codes:
        return {
            "empty_message": "没有可着色的行业热度",
            "scenario_note": "",
            "thesis": "",
        }
    tip_n = min(40, len(hist))
    if ordered_codes:
        ordered = [c for c in ordered_codes if c in set(codes)]
        ordered += [c for c in codes if c not in set(ordered)]
    else:
        series = hotness_series_by_code(
            window_dates=hist[-tip_n:], codes=codes, heat_by_day=heat
        )
        ordered = order_by_trajectory_seriation(codes, series)

    name_to_codes: dict[str, list[str]] = {}
    for code, name in names.items():
        name_to_codes.setdefault(name, []).append(code)

    def resolve_names(items: list[str] | None) -> set[str]:
        out: set[str] = set()
        for name in items or []:
            out.update(name_to_codes.get(str(name), []))
        return out

    base = dict(heat.get(tip) or {})
    forecast_heat: dict[date, dict[str, float]] = {}
    days = list(scenario.get("days") or [])
    for i, day in enumerate(forecast_dates):
        spec = days[i] if i < len(days) else {}
        cur = dict(forecast_heat.get(forecast_dates[i - 1]) if i else base)
        if not cur:
            cur = dict(base)
        warm = resolve_names(spec.get("warm") if isinstance(spec, dict) else None)
        cool = resolve_names(spec.get("cool") if isinstance(spec, dict) else None)
        for code in list(cur):
            if code in warm:
                cur[code] = float(cur[code]) * (0.82 ** (1 + 0.15 * i))
            elif code in cool:
                cur[code] = float(cur[code]) * (1.12 ** (1 + 0.1 * i))
            else:
                cur[code] = 0.85 * float(cur[code]) + 0.15 * float(
                    base.get(code, cur[code])
                )
        forecast_heat[day] = cur

    from app.themes.heat_seriation import densify_hotness_plane, hotness_grid

    combined = dict(heat)
    combined.update(forecast_heat)
    context = hist[-FORECAST_CONTEXT_DAYS:]
    display_dates = list(context) + list(forecast_dates)
    z_native = hotness_grid(
        window_dates=display_dates,
        ordered_codes=ordered,
        heat_by_day=combined,
    )
    x_ticks = list(range(len(ordered)))
    dense_x, dense_z = densify_hotness_plane(
        theme_x=[float(i) for i in x_ticks],
        z_short=z_native,
        densify=4,
    )
    labels = [names.get(c, c) for c in ordered]
    thesis = str(scenario.get("thesis") or "").strip()
    day_notes = []
    for spec in days:
        if not isinstance(spec, dict):
            continue
        note = str(spec.get("note") or "").strip()
        d = str(spec.get("date") or "")
        if note:
            day_notes.append(f"{d[5:] if len(d) >= 10 else d} {note}")
    scenario_note = thesis
    if day_notes:
        scenario_note = thesis + " " + "；".join(day_notes[:3])
    return {
        "dates": [d.isoformat() for d in display_dates],
        "board_codes": ordered,
        "board_names": labels,
        "x": dense_x,
        "x_tickvals": [float(i) for i in x_ticks],
        "x_ticktext": labels,
        "z_short": dense_z,
        "axis_note": (
            "横轴叶序锁定截止日；近端实盘 + DeepSeek 情景着色（warm/cool 调短热）。"
            "属结构情景，不是点预测。"
        ),
        "as_of": tip.isoformat(),
        "forecast_dates": [d.isoformat() for d in forecast_dates],
        "context_dates": [d.isoformat() for d in context],
        "board_count": len(ordered),
        "scenario_note": scenario_note,
        "thesis": thesis,
        "empty_message": None,
        "densify": 4,
    }


FORECAST_CHART_PANELS = frozenset({"slope", "cwt"})


def _forecast_split_y(plane: dict[str, Any]) -> float | None:
    n_ctx = len(plane.get("context_dates") or [])
    if n_ctx < 1:
        return None
    return float(n_ctx) - 0.5


def _render_forecast_contour(
    plane: dict[str, Any],
    *,
    title: str,
    xaxis_title: str,
    entity_label: str,
    tip_labels: dict[str, object] | None = None,
) -> str:
    from app.charts.theme_wave import render_theme_wave_contour

    return render_theme_wave_contour(
        dates=plane["dates"],
        x=plane["x"],
        z=plane["z_short"],
        x_tickvals=plane["x_tickvals"],
        x_ticktext=plane["x_ticktext"],
        include_plotlyjs=False,
        height=520,
        title=title,
        xaxis_title=xaxis_title,
        entity_label=entity_label,
        tickangle=-55,
        tip_labels=tip_labels,
        forecast_split_y=_forecast_split_y(plane),
        show_colorbar=False,
    )


def _forecast_shell(
    *,
    title: str,
    back_href: str,
    back_label: str,
    as_of: str | None,
    requested_as_of: str,
    forecast_dates: list[str],
    slope_chart_url: str,
    cwt_chart_url: str,
    empty_message: str | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "as_of": as_of,
        "requested_as_of": requested_as_of,
        "empty_message": empty_message,
        "back_href": back_href,
        "back_label": back_label,
        "forecast_dates": forecast_dates,
        "lazy": True,
        "slope_chart_url": slope_chart_url,
        "cwt_chart_url": cwt_chart_url,
        "include_plotlyjs": False,
    }


def _chart_result(
    *,
    panel: str,
    note: str = "",
    scenario: str = "",
    error: str = "",
    html: str = "",
) -> dict[str, Any]:
    return {
        "panel": panel,
        "note": note,
        "scenario": scenario,
        "error": error,
        "html": html,
        "ok": bool(html) and not error,
    }


def build_industry_forecast_shell_payload(
    *,
    as_of: date | None,
) -> dict[str, Any]:
    """Light page shell; charts load via /industry-forecast/api/{panel}."""
    requested = as_of or date.today()
    tip_dates = fetch_heat_dates_ending("industry", requested, 1)
    if not tip_dates:
        return _forecast_shell(
            title="行业短热 · 5日推演",
            back_href="/boards/concept/themes/wave",
            back_label="返回行业短热",
            as_of=None,
            requested_as_of=requested.isoformat(),
            forecast_dates=[],
            slope_chart_url="",
            cwt_chart_url="",
            empty_message="没有可用的行业热度截止日。",
        )
    tip = tip_dates[-1]
    known_fwd = fetch_trading_dates_after("industry", tip, FORECAST_DAYS)
    forecast_dates = resolve_forecast_dates(
        as_of=tip, n=FORECAST_DAYS, known_forward=known_fwd
    )
    q = f"as_of={tip.isoformat()}"
    return _forecast_shell(
        title="行业短热 · 5日推演",
        back_href=f"/boards/concept/themes/wave?as_of={tip.isoformat()}",
        back_label="返回行业短热",
        as_of=tip.isoformat(),
        requested_as_of=requested.isoformat(),
        forecast_dates=[d.isoformat() for d in forecast_dates],
        slope_chart_url=f"/boards/concept/themes/wave/industry-forecast/api/slope?{q}",
        cwt_chart_url=f"/boards/concept/themes/wave/industry-forecast/api/cwt?{q}",
    )


def _load_industry_forecast_context(
    as_of: date | None,
) -> dict[str, Any]:
    tip_dates = fetch_heat_dates_ending("industry", as_of or date.today(), 1)
    if not tip_dates:
        return {"empty_message": "没有可用的行业热度截止日。"}
    tip = tip_dates[-1]
    hist = fetch_heat_dates_ending("industry", tip, FORECAST_HISTORY_DAYS)
    if not hist:
        return {"empty_message": "没有可用的行业热度历史。", "tip": tip}
    rows = fetch_industry_heat_window(hist[0], tip)
    heat, names = _heat_maps(rows)
    known_fwd = fetch_trading_dates_after("industry", tip, FORECAST_DAYS)
    forecast_dates = resolve_forecast_dates(
        as_of=tip, n=FORECAST_DAYS, known_forward=known_fwd
    )
    codes = sorted({c for day in hist for c in (heat.get(day) or {})})
    tip_window = hist[-min(40, len(hist)) :]
    series = hotness_series_by_code(
        window_dates=tip_window, codes=codes, heat_by_day=heat
    )
    ordered = order_by_trajectory_seriation(codes, series)
    if not ordered:
        return {"empty_message": "没有可推演的行业叶序。", "tip": tip}
    return {
        "tip": tip,
        "hist": hist,
        "heat": heat,
        "names": names,
        "ordered": ordered,
        "forecast_dates": forecast_dates,
        "empty_message": None,
    }


def build_industry_forecast_chart_payload(
    *,
    as_of: date | None,
    panel: str,
) -> dict[str, Any]:
    """One forecast panel (slope|cwt) as JSON for lazy load."""
    from app.themes.heat_cwt1d import (
        FORECAST_PLANE_DENSIFY,
        WINDOW_DAYS as CWT_WINDOW_DAYS,
        build_industry_cwt_forecast_plane,
    )

    kind = str(panel or "").strip().lower()
    if kind not in FORECAST_CHART_PANELS:
        return _chart_result(panel=kind, error="未知推演面板")
    ctx = _load_industry_forecast_context(as_of)
    if ctx.get("empty_message"):
        return _chart_result(panel=kind, error=str(ctx["empty_message"]))
    tip = ctx["tip"]
    hist = ctx["hist"]
    heat = ctx["heat"]
    names = ctx["names"]
    ordered = ctx["ordered"]
    forecast_dates = ctx["forecast_dates"]
    xaxis = "行业板块（叶序锁定截止日）"
    if kind == "slope":
        slope = build_industry_heat_forecast_payload(
            as_of=tip,
            history_dates=hist,
            heat_by_day=heat,
            names=names,
            forecast_dates=forecast_dates,
            ordered_codes=ordered,
            densify=FORECAST_PLANE_DENSIFY,
        )
        if slope.get("empty_message"):
            return _chart_result(panel=kind, error=str(slope["empty_message"]))
        html = _render_forecast_contour(
            slope,
            title="轨迹延续推演（斜率阻尼 + 截面重排）",
            xaxis_title=xaxis,
            entity_label="行业",
        )
        return _chart_result(
            panel=kind,
            note=slope.get("axis_note") or "",
            scenario=slope.get("scenario_note") or "",
            html=html,
        )
    try:
        cwt_hist = hist[-min(CWT_WINDOW_DAYS, len(hist)) :]
        cwt_plane = build_industry_cwt_forecast_plane(
            tip=tip,
            hist=cwt_hist,
            heat_by_day=heat,
            names=names,
            ordered=ordered,
            forecast_dates=forecast_dates,
            densify=FORECAST_PLANE_DENSIFY,
        )
        if cwt_plane.get("empty_message"):
            return _chart_result(
                panel=kind,
                error=str(cwt_plane.get("empty_message") or "CWT 推演不可用"),
            )
        html = _render_forecast_contour(
            cwt_plane,
            title="CWT 相位续推（近端最强1模 · 自截止日无缝）",
            xaxis_title=xaxis,
            entity_label="行业",
        )
        return _chart_result(
            panel=kind,
            note=cwt_plane.get("axis_note") or "",
            scenario=cwt_plane.get("scenario_note") or "",
            html=html,
        )
    except Exception as exc:  # noqa: BLE001
        return _chart_result(panel=kind, error=str(exc))


def build_industry_forecast_page_payload(
    *,
    as_of: date | None,
    include_plotlyjs: bool = False,
) -> dict[str, Any]:
    """Compat: shell only (charts lazy-loaded by the page)."""
    del include_plotlyjs
    return build_industry_forecast_shell_payload(as_of=as_of)


def _heat_maps(
    rows: list[tuple[date, str, str, object | None, object | None]],
) -> tuple[dict[date, dict[str, float]], dict[str, str]]:
    heat: dict[date, dict[str, float]] = {}
    names: dict[str, str] = {}
    for trade_date, board_code, board_name, heat_short, _long in rows:
        code = str(board_code)
        if board_name:
            names[code] = str(board_name)
        val = as_float(heat_short)
        if val is None:
            continue
        heat.setdefault(trade_date, {})[code] = val
    return heat, names


def _regime_summary_line(tip: date) -> str:
    need = REGIME_DISPLAY_DAYS + REGIME_WARMUP_DAYS + REGIME_PLANE_WINDOW
    cal = fetch_trading_dates_ending("industry", tip, need)
    if not cal:
        return "（无政权摘要）"
    rows = fetch_industry_heat_window(cal[0], tip)
    heat, names = _heat_maps(rows)
    panel = build_regime_panel_payload(
        as_of=tip, calendar=cal, heat_by_day=heat, names=names
    )
    rows_out = panel.get("rows") or []
    if not rows_out:
        return "（无政权摘要）"
    last = rows_out[-1]
    return (
        f"{last.get('regime')}；主线={last.get('members') or '—'}；"
        f"许可={last.get('cand_license') or '—'}；"
        f"候选={last.get('cand_members') or '—'}"
    )


def build_concept_forecast_shell_payload(
    *,
    as_of: date | None,
) -> dict[str, Any]:
    """Light page shell; charts load via /concept-forecast/api/{panel}."""
    requested = as_of or date.today()
    tip_dates = fetch_heat_dates_ending("concept", requested, 1)
    if not tip_dates:
        return _forecast_shell(
            title="概念短热 · 5日推演",
            back_href="/boards/concept/themes/wave",
            back_label="返回概念短热",
            as_of=None,
            requested_as_of=requested.isoformat(),
            forecast_dates=[],
            slope_chart_url="",
            cwt_chart_url="",
            empty_message="没有可用的概念热度截止日。",
        )
    tip = tip_dates[-1]
    known_fwd = fetch_trading_dates_after("concept", tip, FORECAST_DAYS)
    forecast_dates = resolve_forecast_dates(
        as_of=tip, n=FORECAST_DAYS, known_forward=known_fwd
    )
    q = f"as_of={tip.isoformat()}"
    return _forecast_shell(
        title="概念短热 · 5日推演",
        back_href=f"/boards/concept/themes/wave?as_of={tip.isoformat()}",
        back_label="返回概念短热",
        as_of=tip.isoformat(),
        requested_as_of=requested.isoformat(),
        forecast_dates=[d.isoformat() for d in forecast_dates],
        slope_chart_url=f"/boards/concept/themes/wave/concept-forecast/api/slope?{q}",
        cwt_chart_url=f"/boards/concept/themes/wave/concept-forecast/api/cwt?{q}",
    )


def _load_concept_forecast_context(
    as_of: date | None,
) -> dict[str, Any]:
    from app.themes.concept_wave import (
        CONCEPT_ROSTER_WINDOW_DAYS,
        CONCEPT_TOP_N,
        build_concept_top_heat_payload,
    )

    tip_dates = fetch_heat_dates_ending("concept", as_of or date.today(), 1)
    if not tip_dates:
        return {"empty_message": "没有可用的概念热度截止日。"}
    tip = tip_dates[-1]
    hist = fetch_heat_dates_ending("concept", tip, FORECAST_HISTORY_DAYS)
    if not hist:
        return {"empty_message": "没有可用的概念热度历史。", "tip": tip}
    rows = fetch_concept_heat_named_window(hist[0], tip)
    heat_all, names_all = _heat_maps(rows)
    known_fwd = fetch_trading_dates_after("concept", tip, FORECAST_DAYS)
    forecast_dates = resolve_forecast_dates(
        as_of=tip, n=FORECAST_DAYS, known_forward=known_fwd
    )
    roster_n = min(CONCEPT_ROSTER_WINDOW_DAYS, len(hist))
    roster_window = hist[-roster_n:]
    roster = build_concept_top_heat_payload(
        window_dates=roster_window,
        heat_rows=rows,
        top_n=CONCEPT_TOP_N,
        roster_window_dates=roster_window,
    )
    ordered = list(roster.get("board_codes") or [])
    if not ordered or roster.get("empty_message"):
        return {
            "empty_message": str(
                roster.get("empty_message") or "没有可推演的概念入选名单。"
            ),
            "tip": tip,
        }
    names = dict(names_all)
    roster_names = list(roster.get("board_names") or [])
    for i, code in enumerate(ordered):
        if i < len(roster_names) and roster_names[i]:
            names[code] = str(roster_names[i])
        else:
            names.setdefault(code, code)
    keep = set(ordered)
    heat = {
        day: {c: v for c, v in day_map.items() if c in keep}
        for day, day_map in heat_all.items()
    }
    roster_note = (
        f"入选对齐水面：Top{roster.get('top_n') or CONCEPT_TOP_N}"
        f"∪主题共 {len(ordered)} 列"
        f"（主题补入 {roster.get('theme_added') or 0}）。"
    )
    return {
        "tip": tip,
        "hist": hist,
        "heat": heat,
        "names": names,
        "ordered": ordered,
        "forecast_dates": forecast_dates,
        "roster_note": roster_note,
        "empty_message": None,
    }


def build_concept_forecast_chart_payload(
    *,
    as_of: date | None,
    panel: str,
) -> dict[str, Any]:
    from app.themes.heat_cwt1d import (
        FORECAST_PLANE_DENSIFY,
        WINDOW_DAYS as CWT_WINDOW_DAYS,
        build_industry_cwt_forecast_plane,
    )

    kind = str(panel or "").strip().lower()
    if kind not in FORECAST_CHART_PANELS:
        return _chart_result(panel=kind, error="未知推演面板")
    ctx = _load_concept_forecast_context(as_of)
    if ctx.get("empty_message"):
        return _chart_result(panel=kind, error=str(ctx["empty_message"]))
    tip = ctx["tip"]
    hist = ctx["hist"]
    heat = ctx["heat"]
    names = ctx["names"]
    ordered = ctx["ordered"]
    forecast_dates = ctx["forecast_dates"]
    roster_note = str(ctx.get("roster_note") or "")
    xaxis = "概念（叶序锁定截止日 · Top∪主题）"
    if kind == "slope":
        slope = build_industry_heat_forecast_payload(
            as_of=tip,
            history_dates=hist,
            heat_by_day=heat,
            names=names,
            forecast_dates=forecast_dates,
            ordered_codes=ordered,
            densify=FORECAST_PLANE_DENSIFY,
        )
        if slope.get("empty_message"):
            return _chart_result(panel=kind, error=str(slope["empty_message"]))
        html = _render_forecast_contour(
            slope,
            title="轨迹延续推演（斜率阻尼 + 截面重排）",
            xaxis_title=xaxis,
            entity_label="概念",
        )
        note = ((slope.get("axis_note") or "") + " " + roster_note).strip()
        return _chart_result(
            panel=kind,
            note=note,
            scenario=slope.get("scenario_note") or "",
            html=html,
        )
    try:
        cwt_hist = hist[-min(CWT_WINDOW_DAYS, len(hist)) :]
        cwt_plane = build_industry_cwt_forecast_plane(
            tip=tip,
            hist=cwt_hist,
            heat_by_day=heat,
            names=names,
            ordered=ordered,
            forecast_dates=forecast_dates,
            densify=FORECAST_PLANE_DENSIFY,
        )
        if cwt_plane.get("empty_message"):
            return _chart_result(
                panel=kind,
                error=str(cwt_plane.get("empty_message") or "CWT 推演不可用"),
            )
        html = _render_forecast_contour(
            cwt_plane,
            title="CWT 相位续推（近端最强1模 · 自截止日无缝）",
            xaxis_title=xaxis,
            entity_label="概念",
        )
        return _chart_result(
            panel=kind,
            note=cwt_plane.get("axis_note") or "",
            scenario=cwt_plane.get("scenario_note") or "",
            html=html,
        )
    except Exception as exc:  # noqa: BLE001
        return _chart_result(panel=kind, error=str(exc))


def build_concept_forecast_page_payload(
    *,
    as_of: date | None,
    include_plotlyjs: bool = False,
) -> dict[str, Any]:
    """Compat: shell only (charts lazy-loaded by the page)."""
    del include_plotlyjs
    return build_concept_forecast_shell_payload(as_of=as_of)


def build_stock_basket_forecast_shell_payload(
    *,
    names_text: str,
    as_of: date | None,
) -> dict[str, Any]:
    """Light page shell; charts load via /stocks/heat/forecast/api/{panel}."""
    from urllib.parse import quote

    from app.db import fetch_trading_dates_ending

    requested = as_of or date.today()
    back_q = f"?names={quote(names_text or '')}"
    if as_of:
        back_q += f"&as_of={as_of.isoformat()}"
    tip_dates = fetch_trading_dates_ending("industry", requested, 1)
    if not tip_dates:
        return _forecast_shell(
            title="成分股短热 · 5日推演",
            back_href=f"/boards/stocks/heat{back_q}",
            back_label="返回成分股短热",
            as_of=None,
            requested_as_of=requested.isoformat(),
            forecast_dates=[],
            slope_chart_url="",
            cwt_chart_url="",
            empty_message="没有可用的交易截止日。",
        )
    tip = tip_dates[-1]
    from app.db import fetch_trading_dates_after

    known_fwd = fetch_trading_dates_after("industry", tip, FORECAST_DAYS)
    forecast_dates = resolve_forecast_dates(
        as_of=tip, n=FORECAST_DAYS, known_forward=known_fwd
    )
    q = f"names={quote(names_text or '')}&as_of={tip.isoformat()}"
    return _forecast_shell(
        title="成分股短热 · 5日推演",
        back_href=f"/boards/stocks/heat?names={quote(names_text or '')}&as_of={tip.isoformat()}",
        back_label="返回成分股短热",
        as_of=tip.isoformat(),
        requested_as_of=requested.isoformat(),
        forecast_dates=[d.isoformat() for d in forecast_dates],
        slope_chart_url=f"/boards/stocks/heat/forecast/api/slope?{q}",
        cwt_chart_url=f"/boards/stocks/heat/forecast/api/cwt?{q}",
    )


def _load_stock_forecast_context(
    *,
    names_text: str,
    as_of: date | None,
) -> dict[str, Any]:
    from app.db import fetch_trading_dates_after, fetch_trading_dates_ending
    from app.themes.stock_basket_wave import (
        load_stock_basket_heat_maps,
        resolve_stock_basket_universe,
    )

    requested = as_of or date.today()
    tip_dates = fetch_trading_dates_ending("industry", requested, 1)
    if not tip_dates:
        return {"empty_message": "没有可用的交易截止日。"}
    tip = tip_dates[-1]
    universe = resolve_stock_basket_universe(names_text=names_text, tip=tip)
    if universe.get("empty_message") or not universe.get("codes"):
        return {
            "empty_message": str(
                universe.get("empty_message") or "没有可推演的成分股入选名单。"
            ),
            "tip": tip,
        }
    codes = list(universe["codes"])
    names = dict(universe["names"])
    hist, heat, names = load_stock_basket_heat_maps(
        codes=codes,
        names=names,
        tip=tip,
        history_days=FORECAST_HISTORY_DAYS,
    )
    if not hist:
        return {"empty_message": "没有可用的成分股热度历史。", "tip": tip}
    keep = set(codes)
    heat = {
        day: {c: v for c, v in day_map.items() if c in keep}
        for day, day_map in heat.items()
    }
    tip_window = hist[-min(40, len(hist)) :]
    series = hotness_series_by_code(
        window_dates=tip_window, codes=codes, heat_by_day=heat
    )
    ordered = order_by_trajectory_seriation(codes, series)
    if not ordered:
        return {"empty_message": "没有可推演的成分股叶序。", "tip": tip}
    known_fwd = fetch_trading_dates_after("industry", tip, FORECAST_DAYS)
    forecast_dates = resolve_forecast_dates(
        as_of=tip, n=FORECAST_DAYS, known_forward=known_fwd
    )
    roster_note = (
        f"入选对齐水面：{universe.get('meta_line') or ''}；"
        f"推演列 {len(ordered)} 只。"
    )
    return {
        "tip": tip,
        "hist": hist,
        "heat": heat,
        "names": names,
        "ordered": ordered,
        "forecast_dates": forecast_dates,
        "roster_note": roster_note,
        "empty_message": None,
    }


def build_stock_basket_forecast_chart_payload(
    *,
    names_text: str,
    as_of: date | None,
    panel: str,
) -> dict[str, Any]:
    from app.themes.heat_cwt1d import (
        FORECAST_PLANE_DENSIFY,
        WINDOW_DAYS as CWT_WINDOW_DAYS,
        build_industry_cwt_forecast_plane,
    )

    kind = str(panel or "").strip().lower()
    if kind not in FORECAST_CHART_PANELS:
        return _chart_result(panel=kind, error="未知推演面板")
    ctx = _load_stock_forecast_context(names_text=names_text, as_of=as_of)
    if ctx.get("empty_message"):
        return _chart_result(panel=kind, error=str(ctx["empty_message"]))
    tip = ctx["tip"]
    hist = ctx["hist"]
    heat = ctx["heat"]
    names = ctx["names"]
    ordered = ctx["ordered"]
    forecast_dates = ctx["forecast_dates"]
    roster_note = str(ctx.get("roster_note") or "")
    xaxis = "个股（叶序锁定截止日 · 成分并集）"
    if kind == "slope":
        slope = build_industry_heat_forecast_payload(
            as_of=tip,
            history_dates=hist,
            heat_by_day=heat,
            names=names,
            forecast_dates=forecast_dates,
            ordered_codes=ordered,
            densify=FORECAST_PLANE_DENSIFY,
        )
        if slope.get("empty_message"):
            return _chart_result(panel=kind, error=str(slope["empty_message"]))
        tip_labels = tip_hottest_labels(
            ordered_codes=list(slope.get("board_codes") or ordered),
            names=list(slope.get("board_names") or []),
            z_native=list(slope.get("z_boards") or []),
            n_dates=len(slope.get("dates") or []),
            top_n=5,
        )
        html = _render_forecast_contour(
            slope,
            title="轨迹延续推演（斜率阻尼 + 截面重排）",
            xaxis_title=xaxis,
            entity_label="个股",
            tip_labels=tip_labels,
        )
        note = (
            (slope.get("axis_note") or "").replace("各板块", "各成分股")
            + " "
            + roster_note
        ).strip()
        return _chart_result(
            panel=kind,
            note=note,
            scenario=slope.get("scenario_note") or "",
            html=html,
        )
    try:
        cwt_hist = hist[-min(CWT_WINDOW_DAYS, len(hist)) :]
        cwt_plane = build_industry_cwt_forecast_plane(
            tip=tip,
            hist=cwt_hist,
            heat_by_day=heat,
            names=names,
            ordered=ordered,
            forecast_dates=forecast_dates,
            densify=FORECAST_PLANE_DENSIFY,
        )
        if cwt_plane.get("empty_message"):
            return _chart_result(
                panel=kind,
                error=str(cwt_plane.get("empty_message") or "CWT 推演不可用"),
            )
        tip_labels = tip_hottest_labels(
            ordered_codes=list(cwt_plane.get("board_codes") or ordered),
            names=list(cwt_plane.get("board_names") or []),
            z_native=list(cwt_plane.get("z_boards") or []),
            n_dates=len(cwt_plane.get("dates") or []),
            top_n=5,
        )
        html = _render_forecast_contour(
            cwt_plane,
            title="CWT 相位续推（近端最强1模 · 自截止日无缝）",
            xaxis_title=xaxis,
            entity_label="个股",
            tip_labels=tip_labels,
        )
        return _chart_result(
            panel=kind,
            note=cwt_plane.get("axis_note") or "",
            scenario=cwt_plane.get("scenario_note") or "",
            html=html,
        )
    except Exception as exc:  # noqa: BLE001
        return _chart_result(panel=kind, error=str(exc))


def build_stock_basket_forecast_page_payload(
    *,
    names_text: str,
    as_of: date | None,
    include_plotlyjs: bool = False,
) -> dict[str, Any]:
    """Compat: shell only (charts lazy-loaded by the page)."""
    del include_plotlyjs
    return build_stock_basket_forecast_shell_payload(
        names_text=names_text, as_of=as_of
    )
