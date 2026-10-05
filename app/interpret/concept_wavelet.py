"""Build concept Top200 2D-wavelet reading prompt."""

from __future__ import annotations

from datetime import date

from jinja2 import StrictUndefined, Template

from app.db import (
    fetch_concept_heat_named_window,
    fetch_heat_dates_ending,
)
from app.prompts.template import PromptTemplate, load_prompt
from app.themes.concept_wavelet import (
    CONCEPT_ROSTER_WINDOW_DAYS,
    DEFAULT_WINDOW_DAYS,
    build_concept_wavelet_payload,
)


def _fmt(value: object, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def _feature_table(rows: list[dict], title: str) -> list[str]:
    lines = [
        f"### {title}",
        "概念\tscore\tA3均值\tA3近端\t原近端\tD3能量\tD1能量",
    ]
    for row in rows:
        lines.append(
            "\t".join(
                [
                    str(row.get("board_name") or ""),
                    _fmt(row.get("score"), 4),
                    _fmt(row.get("a3_mean"), 3),
                    _fmt(row.get("a3_late"), 3),
                    _fmt(row.get("z_late"), 3),
                    _fmt(row.get("d3_energy"), 4),
                    _fmt(row.get("d1_energy"), 4),
                ]
            )
        )
    return lines


def _data_block(payload: dict) -> str:
    energy = payload.get("energy") or []
    directions = payload.get("directions") or []
    features = payload.get("features") or {}
    lines = [
        f"截止日：{payload.get('as_of')}",
        f"窗口交易日数：{payload.get('window_days')}",
        f"概念数：近端 Top{payload.get('top_n')}∪主题"
        f"（实际 {payload.get('board_count')}，主题补入 {payload.get('theme_added') or 0}）",
        f"入选段：{payload.get('select_from')} → {payload.get('select_to')}",
        f"小波：{payload.get('wavelet')} × {payload.get('level')} 层",
        f"近端天数：{payload.get('late_days')}",
        f"场均值：{_fmt(payload.get('z_mean'), 4)}",
        "",
        "## 多尺度能量占比 %",
    ]
    for row in energy:
        lines.append(f"- {row['label']}：{_fmt(row['share_pct'], 2)}%")
    lines.append("")
    lines.append("## 方向能量占比 %（全部细节层合计）")
    for row in directions:
        lines.append(f"- {row['label']}：{_fmt(row['share_pct'], 2)}%")

    lines.extend(
        [
            "",
            "## 概念映射表（与页面同一份；每类 Top10；解读只点名、禁止再制表）",
            "标签含义：主线占位=A3高且近端仍高；占位回落=A3窗内高但近端回落；"
            "二波回补=D3中段偏冷近段偏热；中粗活跃=D3能量高；细脉冲=D1相对粗结构偏高。",
            "",
        ]
    )
    lines.extend(_feature_table(features.get("occupancy") or [], "主线占位"))
    lines.append("")
    lines.extend(_feature_table(features.get("fade") or [], "占位回落"))
    lines.append("")
    lines.extend(_feature_table(features.get("rewarm") or [], "二波回补"))
    lines.append("")
    lines.extend(_feature_table(features.get("mid_active") or [], "中粗活跃"))
    lines.append("")
    lines.extend(_feature_table(features.get("pulse") or [], "细脉冲"))
    lines.extend(
        [
            "",
            "## 读图约束",
            "- 横轴是轨迹+结构融合叶序（共动/成分/名称近邻），不是产业链距离。",
            "- 细脉冲近端可以很热，但不得升格成主线占位，除非同名也出现在主线占位表。",
            "- 能量%与概念名单必须来自上文，禁止编造未出现的概念。",
            "- 禁止输出 Markdown 表格；映射名单已在页面展示。",
        ]
    )
    return "\n".join(lines)


def build_concept_wavelet_reading_prompt(
    as_of: date | None = None,
    *,
    window_trading_days: int | None = None,
    roster_trading_days: int | None = None,
) -> tuple[PromptTemplate, str, date]:
    template = load_prompt("concept-wavelet-reading")
    default_window = int(template.config.get("window_trading_days") or DEFAULT_WINDOW_DAYS)
    window = int(window_trading_days) if window_trading_days is not None else default_window
    window = max(20, min(180, window))
    roster_days = (
        int(roster_trading_days)
        if roster_trading_days is not None
        else CONCEPT_ROSTER_WINDOW_DAYS
    )
    roster_days = max(20, min(180, roster_days))

    target = as_of or date.today()
    ending = fetch_heat_dates_ending("concept", target, 1)
    if not ending:
        raise RuntimeError("no concept heat rows to interpret")
    selected = ending[-1]

    window_dates = fetch_heat_dates_ending("concept", selected, window)
    if not window_dates:
        raise RuntimeError("no concept heat window to interpret")
    roster_window = fetch_heat_dates_ending("concept", selected, roster_days)
    if not roster_window:
        roster_window = window_dates

    payload = build_concept_wavelet_payload(
        window_dates=window_dates,
        heat_rows=fetch_concept_heat_named_window(
            window_dates[0], window_dates[-1]
        ),
        roster_window_dates=roster_window,
    )
    if payload.get("empty_message"):
        raise RuntimeError(payload["empty_message"])

    resolved = window_dates[-1]
    body = Template(template.body, undefined=StrictUndefined).render(
        window_trading_days=len(window_dates),
        data_block=_data_block(payload),
    )
    return template, body, resolved
