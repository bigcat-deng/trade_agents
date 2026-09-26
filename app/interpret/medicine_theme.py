"""Build and call the medicine theme chart-reading prompt."""

from __future__ import annotations

import json
import urllib.request
from datetime import date

from jinja2 import StrictUndefined, Template

from app.db import fetch_concept_heat_window, fetch_heat_dates_ending, fetch_rotation_dates
from app.prompts.template import PromptTemplate, load_prompt
from app.themes import get_theme
from app.themes.service import build_theme_view

TEMPLATE_NAME = "medicine-theme-heat"


def build_medicine_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    template = load_prompt(TEMPLATE_NAME)
    theme_id = str(template.config.get("theme_id") or "medicine")
    theme = get_theme(theme_id)
    if theme is None:
        raise RuntimeError(f"unknown theme: {theme_id}")

    slider_dates = fetch_rotation_dates(theme.board_type, 10)
    selected = as_of or (slider_dates[-1] if slider_dates else None)
    if selected is None:
        raise RuntimeError("no concept heat rows to interpret")
    if as_of is not None and as_of not in slider_dates:
        raise RuntimeError("date is outside the last 11 trading days")

    window = int(template.config.get("window_trading_days") or theme.window_trading_days)
    window_dates = fetch_heat_dates_ending(theme.board_type, selected, window)
    if not window_dates:
        raise RuntimeError("no concept heat window to interpret")

    heat_rows = fetch_concept_heat_window(window_dates[0], window_dates[-1])
    view = build_theme_view(
        theme,
        as_of=selected,
        window_dates=window_dates,
        heat_rows=heat_rows,
        slider_dates=slider_dates,
    )
    if view.get("empty_message"):
        raise RuntimeError(view["empty_message"])

    resolved = date.fromisoformat(view["as_of"])
    body = Template(template.body, undefined=StrictUndefined).render(
        data_block=_data_block(view),
    )
    return template, body, resolved


def interpret_prose(prompt: str, settings: dict[str, str]) -> tuple[str, str]:
    """OpenAI-compatible chat without forcing JSON."""
    base = settings["base_url"].rstrip("/")
    payload = json.dumps(
        {
            "model": settings["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
        ensure_ascii=False,
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
    return str(content).strip(), str(body.get("model") or settings["model"])


def prose_reading(content: str) -> dict:
    text = content.strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            conclusion = payload.get("conclusion") or payload.get("reading")
            if isinstance(conclusion, str) and conclusion.strip():
                return {"conclusion": conclusion.strip(), "sections": []}
    return {"conclusion": text, "sections": []}


def _fmt(value: object, digits: int) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def _data_block(view: dict) -> str:
    sat = (view.get("satellites") or [None])[0]
    ab = view["badge_ab"]
    ab_label = ab["label"]
    if ab.get("sublabel"):
        ab_label = f"{ab_label}·{ab['sublabel']}"

    a_codes = [(m["board_code"], m["board_name"]) for m in view["members_a"]]
    b_codes = [(m["board_code"], m["board_name"]) for m in view["members_b"]]
    lines = [
        f"截止日：{view['as_of']}",
        f"窗口起点：{view['window_start']}",
        f"窗口交易日数：{view['window_days']}",
        f"成员：{view.get('membership_note') or ''}",
        "",
        "## 徽章",
        f"群A：{view['badge_a']['label']} — {view['badge_a'].get('detail') or ''}",
        (
            f"  群窗口变热中位≈{view['badge_a'].get('delta')}；"
            f"同向占比={view['badge_a'].get('co_move_ratio')}；"
            f"分位离散 {view['badge_a'].get('spread_d0')} → {view['badge_a'].get('spread_as_of')}"
        ),
        f"A↔B：{ab_label} — {ab.get('detail') or ''}",
        (
            f"  ΔA={ab.get('delta_a')}；ΔB={ab.get('delta_b')}；"
            f"群间分位缺口 {ab.get('gap_d0')} → {ab.get('gap_as_of')}"
        ),
    ]
    if sat:
        lines.extend(
            [
                (
                    f"卫星：{sat['board_name']} — {sat['label']}；{sat.get('detail') or ''}"
                ),
                (
                    f"  变热={sat.get('delta')}；截止分位={sat.get('percentile_as_of')}"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## 截止日成员表",
            "",
            "### 群A",
            _member_table(view["members_a"]),
            "",
            "### 群B",
            _member_table(view["members_b"]),
            "",
            "## 上图序列（群中位分位，按日）",
            "",
            _series_line(view["series_group_a"], "群A中位"),
            _series_line(view["series_group_b"], "群B中位"),
            "",
            "## 下图序列（成员短热分位，按日）",
            "",
            "### 群A",
            _member_series(a_codes, view["member_series"]),
            "",
            "### 群B",
            _member_series(b_codes, view["member_series"]),
        ]
    )
    if sat:
        lines.extend(
            [
                "",
                "### 卫星",
                _member_series(
                    [(sat["board_code"], sat["board_name"])],
                    view["member_series"],
                ),
            ]
        )
    return "\n".join(lines)


def _member_table(members: list[dict]) -> str:
    rows = ["概念\t短热\t分位\t窗口变热\t角色"]
    for member in members:
        rows.append(
            "\t".join(
                [
                    member["board_name"],
                    _fmt(member.get("heat_short"), 1),
                    _fmt(member.get("percentile"), 3),
                    _fmt(member.get("delta"), 1),
                    member.get("role") or "",
                ]
            )
        )
    return "\n".join(rows)


def _series_line(points: list[dict], label: str) -> str:
    bits = [f"{p['trade_date']}:{_fmt(p.get('value'), 3)}" for p in points]
    return label + "\t" + " ".join(bits)


def _member_series(
    codes_names: list[tuple[str, str]],
    member_series: dict,
) -> str:
    lines = []
    for code, name in codes_names:
        points = (member_series.get(code) or {}).get("points") or []
        bits = [
            f"{p['trade_date']}:{_fmt(p.get('percentile'), 3)}" for p in points
        ]
        lines.append(name + "\t" + " ".join(bits))
    return "\n".join(lines)
