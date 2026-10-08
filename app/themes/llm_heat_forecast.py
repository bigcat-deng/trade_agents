"""DeepSeek / OpenAI-compatible industry heat forecast via prompt template."""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from typing import Any

from jinja2 import StrictUndefined, Template

from app.db import (
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


def build_industry_forecast_page_payload(
    *,
    as_of: date | None,
    include_plotlyjs: bool = False,
    run_llm: bool = True,
) -> dict[str, Any]:
    """Page payload: slope forecast + optional bubble-field vision redraw."""
    from app.charts.theme_wave import render_theme_wave_contour

    tip_dates = fetch_heat_dates_ending("industry", as_of or date.today(), 1)
    if not tip_dates:
        return {
            "title": "行业短热 · 5日推演",
            "as_of": None,
            "requested_as_of": (as_of or date.today()).isoformat(),
            "empty_message": "没有可用的行业热度截止日。",
            "back_href": "/boards/concept/themes/wave",
            "slope_html": "",
            "llm_html": "",
            "slope_note": "",
            "llm_note": "",
            "slope_scenario": "",
            "llm_scenario": "",
            "llm_error": "",
            "prompt_preview": "",
            "include_plotlyjs": include_plotlyjs,
        }
    tip = tip_dates[-1]
    back = (
        f"/boards/concept/themes/wave?as_of={tip.isoformat()}"
    )
    hist = fetch_heat_dates_ending("industry", tip, FORECAST_HISTORY_DAYS)
    rows = fetch_industry_heat_window(hist[0], tip) if hist else []
    heat, names = _heat_maps(rows)
    known_fwd = fetch_trading_dates_after("industry", tip, FORECAST_DAYS)
    forecast_dates = resolve_forecast_dates(
        as_of=tip, n=FORECAST_DAYS, known_forward=known_fwd
    )
    # Tip leaf order for both charts.
    codes = sorted({c for day in hist for c in (heat.get(day) or {})})
    tip_window = hist[-min(40, len(hist)) :]
    series = hotness_series_by_code(
        window_dates=tip_window, codes=codes, heat_by_day=heat
    )
    ordered = order_by_trajectory_seriation(codes, series)

    slope = build_industry_heat_forecast_payload(
        as_of=tip,
        history_dates=hist,
        heat_by_day=heat,
        names=names,
        forecast_dates=forecast_dates,
        ordered_codes=ordered,
    )
    slope_html = ""
    if not slope.get("empty_message"):
        slope_html = render_theme_wave_contour(
            dates=slope["dates"],
            x=slope["x"],
            z=slope["z_short"],
            x_tickvals=slope["x_tickvals"],
            x_ticktext=slope["x_ticktext"],
            include_plotlyjs=include_plotlyjs,
            height=520,
            title="轨迹延续推演（斜率阻尼 + 截面重排）",
            xaxis_title="行业板块（叶序锁定截止日）",
            entity_label="行业",
            tickangle=-55,
        )

    llm_html = ""
    llm_note = ""
    llm_scenario = ""
    llm_error = ""
    prompt_preview = ""
    model_id = ""
    if run_llm:
        try:
            from app.themes.bubble_field_forecast import run_bubble_field_forecast

            llm_plane, prompt_preview, model_id, _ref = run_bubble_field_forecast(
                tip=tip,
                hist=hist,
                heat_by_day=heat,
                names=names,
                ordered=ordered,
                forecast_dates=forecast_dates,
            )
            if not llm_plane.get("empty_message"):
                llm_note = llm_plane.get("axis_note") or ""
                llm_scenario = llm_plane.get("scenario_note") or ""
                if model_id:
                    llm_scenario = f"[{model_id}] {llm_scenario}"
                llm_html = render_theme_wave_contour(
                    dates=llm_plane["dates"],
                    x=llm_plane["x"],
                    z=llm_plane["z_short"],
                    x_tickvals=llm_plane["x_tickvals"],
                    x_ticktext=llm_plane["x_ticktext"],
                    include_plotlyjs=False,
                    height=520,
                    title="DeepSeek 看图续气泡（结构场 → 重绘）",
                    xaxis_title="行业板块（叶序锁定截止日）",
                    entity_label="行业",
                    tickangle=-55,
                )
        except Exception as exc:  # noqa: BLE001 — surface to page
            llm_error = str(exc)

    return {
        "title": "行业短热 · 5日推演",
        "as_of": tip.isoformat(),
        "requested_as_of": (as_of or tip).isoformat(),
        "empty_message": None,
        "back_href": back,
        "slope_html": slope_html,
        "llm_html": llm_html,
        "slope_note": slope.get("axis_note") or "",
        "llm_note": llm_note,
        "slope_scenario": slope.get("scenario_note") or "",
        "llm_scenario": llm_scenario,
        "llm_error": llm_error,
        "prompt_preview": prompt_preview,
        "forecast_dates": [d.isoformat() for d in forecast_dates],
        "include_plotlyjs": include_plotlyjs,
    }


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
