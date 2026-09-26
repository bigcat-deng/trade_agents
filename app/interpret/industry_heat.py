"""Fill the industry heat-rotation prompt from board_heat_daily."""

from __future__ import annotations

import json
import os
import urllib.request
from decimal import Decimal
from datetime import date

from jinja2 import StrictUndefined, Template

from app.db import (
    IndustryHeatPoint,
    IndustryPriceSummary,
    fetch_industry_heat_window,
    fetch_industry_price_summary,
)
from app.prompts.template import PromptTemplate, load_prompt

TEMPLATE_NAME = "industry-heat-rotation"
_COLUMNS = (
    "trade_date",
    "board_name",
    "heat_short",
    "heat_long",
    "heat_short_change",
    "heat_long_change",
    "pct_chg",
)
_SUMMARY_COLUMNS = (
    "board_name",
    "ret_20",
    "range_pos",
    "amount_ratio",
)
_SECTIONS = (
    ("hot_zone", "截止日的轮动", frozenset({"热区", "变热", "退潮"}), 10),
    ("aligned", "短期和长期一致", frozenset({"短长都热", "变热且长期热"}), 10),
    ("divergent", "短期和长期分歧", frozenset({"新升温", "热度消退"}), 10),
    ("price_split", "涨跌与热度背离", frozenset({"变热但下跌", "变冷但大涨"}), 10),
    ("watch", "继续看", frozenset({"看短期能否稳住", "看长期是否跟上", "看短期是否止跌"}), 8),
)


def build_industry_heat_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date, dict[str, IndustryHeatPoint], dict[str, IndustryPriceSummary]]:
    template = load_prompt(TEMPLATE_NAME)
    window = int(template.config.get("window_trading_days") or 20)
    resolved, prev_date, points = fetch_industry_heat_window(window, as_of)
    if resolved is None or not points:
        raise RuntimeError("no industry heat rows to interpret")
    latest = {
        point.board_name: point
        for point in points
        if point.trade_date == resolved
    }
    summaries = {
        row.board_name: row for row in fetch_industry_price_summary(window, resolved)
    }
    body = Template(template.body, undefined=StrictUndefined).render(
        as_of=resolved.isoformat(),
        prev_date=prev_date.isoformat() if prev_date else "",
        board_count=len(latest),
        heat_table=_table(points),
        price_summary=_summary_table(summaries.values()),
    )
    return template, body, resolved, latest, summaries


def model_settings(template: PromptTemplate) -> dict[str, str]:
    """Frontmatter model block, with empty fields filled from the environment."""
    from app.env import load_env

    load_env()
    model = template.config.get("model") or {}
    if not isinstance(model, dict):
        model = {}
    return {
        "provider": _setting(model.get("provider"), "LLM_PROVIDER"),
        "base_url": _setting(model.get("base_url"), "LLM_BASE_URL"),
        "model": _setting(model.get("model"), "LLM_MODEL"),
        "api_key": _setting(model.get("api_key"), "LLM_API_KEY"),
    }


def normalize_reading(
    content: str,
    latest: dict[str, IndustryHeatPoint],
    summaries: dict[str, IndustryPriceSummary] | None = None,
) -> dict | None:
    """Turn a model reply or a saved reading into the five tables shown on the page.

    Heat numbers are taken from latest, not from the model. Unknown boards and
    judgments outside the allowed set are dropped.
    """
    payload = _extract_json(content)
    if payload is None:
        return None
    conclusion = _text(payload.get("conclusion")) or _text(payload.get("结论"))
    if not conclusion:
        return None
    raw_sections = payload.get("sections")
    sections = []
    for section_id, title, judgments, limit in _SECTIONS:
        rows = _section_rows(payload, raw_sections, section_id, title)
        kept = []
        seen: set[str] = set()
        for row in rows:
            if len(kept) >= limit:
                break
            if not isinstance(row, dict):
                continue
            board = _text(row.get("board")) or _text(row.get("板块")) or _text(row.get("board_name"))
            judgment = _text(row.get("judgment")) or _text(row.get("判断"))
            point = latest.get(board)
            if point is None or judgment not in judgments or board in seen:
                continue
            if not _consistent(judgment, point):
                continue
            seen.add(board)
            summary = None if summaries is None else summaries.get(board)
            kept.append(
                {
                    "board": board,
                    "board_code": point.board_code,
                    "heat_short": _number(point.heat_short),
                    "heat_long": _number(point.heat_long),
                    "heat_short_change": _number(point.heat_short_change),
                    "heat_long_change": _number(point.heat_long_change),
                    "pct_chg": _number(point.pct_chg),
                    "judgment": judgment,
                    "note": _note_from_summary(summary),
                }
            )
        sections.append({"id": section_id, "title": title, "rows": kept})
    return {"conclusion": conclusion, "sections": sections}


def interpret_industry_heat(prompt: str, settings: dict[str, str]) -> tuple[str, str]:
    """Call an OpenAI-compatible chat endpoint. Return reply text and model id."""
    base = settings["base_url"].rstrip("/")
    payload = json.dumps(
        {
            "model": settings["model"],
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
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
    return content, str(body.get("model") or settings["model"])


def _summary_table(rows) -> str:
    lines = ["\t".join(_SUMMARY_COLUMNS)]
    for row in rows:
        lines.append(
            "\t".join(
                _cell(value)
                for value in (row.board_name, row.ret_20, row.range_pos, row.amount_ratio)
            )
        )
    return "\n".join(lines)


def _section_rows(payload: dict, raw_sections: object, section_id: str, title: str) -> list:
    if isinstance(raw_sections, list):
        for section in raw_sections:
            if not isinstance(section, dict):
                continue
            if section.get("id") == section_id or section.get("title") == title:
                rows = section.get("rows")
                return rows if isinstance(rows, list) else []
        return []
    rows = payload.get(section_id)
    if isinstance(rows, list):
        return rows
    rows = payload.get(title)
    return rows if isinstance(rows, list) else []


def _extract_json(content: str) -> dict | None:
    raw = content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        fence = raw.rfind("```")
        if fence >= 0:
            raw = raw[:fence]
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    return round(float(value), 2)


def _consistent(judgment: str, point: IndustryHeatPoint) -> bool:
    change = point.heat_short_change
    pct = point.pct_chg
    if judgment in {"变热", "变热且长期热", "新升温"}:
        return change is not None and change > 0
    if judgment in {"退潮", "热度消退"}:
        return change is not None and change < 0
    if judgment == "变热但下跌":
        return change is not None and change > 0 and pct is not None and pct <= -1
    if judgment == "变冷但大涨":
        return change is not None and change < 0 and pct is not None and pct >= 1
    return True


def _note_from_summary(summary: IndustryPriceSummary | None) -> str:
    if summary is None:
        return ""
    parts: list[str] = []
    if summary.ret_20 is not None:
        ret = float(summary.ret_20)
        if ret > 0:
            parts.append("近20日上涨")
        elif ret < 0:
            parts.append("近20日下跌")
        else:
            parts.append("近20日持平")
    if summary.range_pos is not None:
        pos = float(summary.range_pos)
        if pos >= 0.8:
            parts.append("区间上沿")
        elif pos <= 0.2:
            parts.append("区间下沿")
        else:
            parts.append("区间中部")
    if summary.amount_ratio is not None:
        ratio = float(summary.amount_ratio)
        if ratio >= 1.2:
            parts.append("量能放大")
        elif ratio <= 0.8:
            parts.append("量能萎缩")
        else:
            parts.append("量能平常")
    return "，".join(parts)


def _table(points) -> str:
    lines = ["\t".join(_COLUMNS)]
    for point in points:
        lines.append(
            "\t".join(
                _cell(value)
                for value in (
                    point.trade_date,
                    point.board_name,
                    point.heat_short,
                    point.heat_long,
                    point.heat_short_change,
                    point.heat_long_change,
                    point.pct_chg,
                )
            )
        )
    return "\n".join(lines)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    return str(value)


def _setting(value: object, env_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if text:
        return text
    return os.environ.get(env_name, "").strip()
