"""Build and call concept-theme fused reading prompts."""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from statistics import mean

from jinja2 import StrictUndefined, Template

from app.db import (
    fetch_board_daily_bars_many,
    fetch_concept_heat_window,
    fetch_heat_dates_ending,
    fetch_rotation_dates,
)
from app.market_data.csi500 import fetch_csi500_closes
from app.prompts.template import PromptTemplate, load_prompt
from app.themes import get_theme
from app.themes.config import theme_board_codes
from app.themes.service import build_theme_view

DEFAULT_PRICE_DAYS = 60
PROSE_THEME_TEMPLATES = frozenset(
    {
        "medicine-theme-reading",
        "ai-theme-reading",
        "semiconductor-theme-reading",
        "metals-theme-reading",
        "energy-theme-reading",
        "defense-theme-reading",
        "renewables-theme-reading",
        "battery-theme-reading",
        "robots-theme-reading",
        "food-theme-reading",
        "finance-theme-reading",
        "property-theme-reading",
        "theme-wave-reading",
    }
)


def build_theme_reading_prompt(
    template_name: str,
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    template = load_prompt(template_name)
    theme_id = str(template.config.get("theme_id") or "")
    if not theme_id:
        raise RuntimeError(f"theme_id missing in prompt config: {template_name}")
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
    price_days = int(template.config.get("price_trading_days") or DEFAULT_PRICE_DAYS)
    price_stats = _price_stats(theme.board_type, theme_board_codes(theme), resolved, price_days)
    body = Template(template.body, undefined=StrictUndefined).render(
        data_block=_data_block(view, price_stats),
    )
    return template, body, resolved


def build_medicine_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("medicine-theme-reading", as_of)


def build_ai_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("ai-theme-reading", as_of)


def build_semiconductor_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("semiconductor-theme-reading", as_of)


def build_metals_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("metals-theme-reading", as_of)


def build_energy_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("energy-theme-reading", as_of)


def build_defense_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("defense-theme-reading", as_of)


def build_renewables_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("renewables-theme-reading", as_of)


def build_battery_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("battery-theme-reading", as_of)


def build_robots_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("robots-theme-reading", as_of)


def build_food_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("food-theme-reading", as_of)


def build_finance_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("finance-theme-reading", as_of)


def build_property_theme_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    return build_theme_reading_prompt("property-theme-reading", as_of)


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


def _group_labels(view: dict) -> tuple[str, str, str]:
    grouping = view.get("grouping") or {}
    label_a = (grouping.get("group_a") or {}).get("label") or "群A"
    label_b = (grouping.get("group_b") or {}).get("label") or "群B"
    label_sat = (grouping.get("satellite") or {}).get("label") or "卫星"
    return label_a, label_b, label_sat


def _data_block(view: dict, price_stats: dict) -> str:
    label_a, label_b, label_sat = _group_labels(view)
    sats = view.get("satellites") or []
    ab = view["badge_ab"]
    ab_label = ab["label"]
    if ab.get("sublabel"):
        ab_label = f"{ab_label}·{ab['sublabel']}"

    a_codes = [(m["board_code"], m["board_name"]) for m in view["members_a"]]
    b_codes = [(m["board_code"], m["board_name"]) for m in view["members_b"]]

    lines = [
        f"截止日：{view['as_of']}",
        f"热度窗口起点：{view['window_start']}",
        f"热度窗口交易日数：{view['window_days']}",
        (
            f"价格窗口：{price_stats.get('start') or ''} → {price_stats.get('end') or ''}"
            f"（{price_stats.get('days') or 0} 个交易日）"
        ),
        f"成员：{view.get('membership_note') or ''}",
        "",
        "## 徽章",
        f"{label_a}：{view['badge_a']['label']} — {view['badge_a'].get('detail') or ''}",
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
    for sat in sats:
        lines.extend(
            [
                (
                    f"{label_sat}：{sat['board_name']} — {sat['label']}；"
                    f"{sat.get('detail') or ''}"
                ),
                (
                    f"  变热={sat.get('delta')}；截止分位={sat.get('percentile_as_of')}"
                ),
            ]
        )

    lines.extend(
        [
            "",
            "## 价格相对中证500（近价格窗口，单位 %）",
            "",
            f"中证500收益率：{_fmt(price_stats.get('index_ret'), 2)}",
            "概念\t窗口变热\t短热分位\t概念收益率\t中证500收益率\t超额",
        ]
    )
    price_by_code = {row["board_code"]: row for row in price_stats.get("rows") or []}
    for group_name, members in (
        (label_a, view["members_a"]),
        (label_b, view["members_b"]),
    ):
        lines.append(f"# {group_name}")
        for member in members:
            prow = price_by_code.get(member["board_code"]) or {}
            lines.append(
                "\t".join(
                    [
                        member["board_name"],
                        _fmt(member.get("delta"), 1),
                        _fmt(member.get("percentile"), 3),
                        _fmt(prow.get("ret"), 2),
                        _fmt(prow.get("index_ret"), 2),
                        _fmt(prow.get("excess"), 2),
                    ]
                )
            )
    if sats:
        lines.append(f"# {label_sat}")
        for sat in sats:
            prow = price_by_code.get(sat["board_code"]) or {}
            lines.append(
                "\t".join(
                    [
                        sat["board_name"],
                        _fmt(sat.get("delta"), 1),
                        _fmt(sat.get("percentile_as_of"), 3),
                        _fmt(prow.get("ret"), 2),
                        _fmt(prow.get("index_ret"), 2),
                        _fmt(prow.get("excess"), 2),
                    ]
                )
            )

    group_lines = _group_excess_summary(view, price_by_code)
    if group_lines:
        lines.extend(["", "## 群层超额（成员超额简单平均）", *group_lines])

    lines.extend(
        [
            "",
            "## 截止日成员热度表",
            "",
            f"### {label_a}",
            _member_table(view["members_a"]),
            "",
            f"### {label_b}",
            _member_table(view["members_b"]),
            "",
            "## 上图序列（群中位分位，按日）",
            "",
            _series_line(view["series_group_a"], f"{label_a}中位"),
            _series_line(view["series_group_b"], f"{label_b}中位"),
            "",
            "## 下图序列（成员短热分位，按日）",
            "",
            f"### {label_a}",
            _member_series(a_codes, view["member_series"]),
            "",
            f"### {label_b}",
            _member_series(b_codes, view["member_series"]),
        ]
    )
    if sats:
        lines.extend(
            [
                "",
                f"### {label_sat}",
                _member_series(
                    [(s["board_code"], s["board_name"]) for s in sats],
                    view["member_series"],
                ),
            ]
        )
    return "\n".join(lines)


def _group_excess_summary(view: dict, price_by_code: dict) -> list[str]:
    label_a, label_b, _ = _group_labels(view)
    lines = []
    for label, members in ((label_a, view["members_a"]), (label_b, view["members_b"])):
        excesses = []
        for member in members:
            row = price_by_code.get(member["board_code"]) or {}
            if row.get("excess") is not None:
                excesses.append(float(row["excess"]))
        if excesses:
            lines.append(f"{label}平均超额：{_fmt(mean(excesses), 2)}")
    return lines


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


def _fmt(value: object, digits: int) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def _price_stats(
    board_type: str,
    board_codes: list[str],
    as_of: date,
    trading_days: int,
) -> dict:
    dates = fetch_heat_dates_ending(board_type, as_of, trading_days)
    if not dates:
        return {
            "start": None,
            "end": None,
            "days": 0,
            "index_ret": None,
            "rows": [],
        }
    start, end = dates[0], dates[-1]
    bars_by_code = fetch_board_daily_bars_many(board_type, board_codes, start, end)
    index_closes = dict(fetch_csi500_closes(start, end))
    index_ret = _series_return(
        [(day, value) for day, value in sorted(index_closes.items())]
    )
    rows = []
    for code in board_codes:
        bars = bars_by_code.get(code) or []
        series = []
        for bar in bars:
            close = bar.get("close")
            if close is None:
                continue
            day = bar["trade_date"]
            if not isinstance(day, date):
                day = date.fromisoformat(str(day)[:10])
            series.append((day, float(close)))
        concept_ret = _series_return(series)
        excess = None
        if concept_ret is not None and index_ret is not None:
            excess = concept_ret - index_ret
        rows.append(
            {
                "board_code": code,
                "ret": concept_ret,
                "index_ret": index_ret,
                "excess": excess,
            }
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": len(dates),
        "index_ret": index_ret,
        "rows": rows,
    }


def _series_return(series: list[tuple[date, float]]) -> float | None:
    if len(series) < 2:
        return None
    first = series[0][1]
    last = series[-1][1]
    if first == 0:
        return None
    return (last / first - 1.0) * 100.0
