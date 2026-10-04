"""Build the theme-wave overview prose reading prompt."""

from __future__ import annotations

from datetime import date

from jinja2 import StrictUndefined, Template

from app.db import (
    fetch_concept_heat_named_window,
    fetch_concept_heat_window,
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
)
from app.prompts.template import PromptTemplate, load_prompt
from app.themes import list_themes
from app.themes.concept_wave import CONCEPT_TOP_N, build_concept_top_heat_payload
from app.themes.config import theme_board_codes
from app.themes.heat_seriation import late_quarter_dates
from app.themes.industry_wave import build_industry_board_heat_payload
from app.themes.wave_surface import build_theme_wave_payload

DEFAULT_WINDOW_DAYS = 40


def _fmt(value: object | None, digits: int = 3) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return ""


def _theme_label(title: str) -> str:
    return title.replace("主题域", "").strip() or title


def _row_hotness(z: list[list[float | None]], day_i: int) -> list[float | None]:
    if day_i < 0 or day_i >= len(z):
        return []
    return list(z[day_i])


def _named_levels(
    names: list[str],
    values: list[float | None],
    *,
    hottest_first: bool,
    limit: int,
) -> list[tuple[str, float]]:
    pairs: list[tuple[str, float]] = []
    for name, value in zip(names, values):
        if value is None:
            continue
        pairs.append((name, float(value)))
    pairs.sort(key=lambda item: item[1], reverse=hottest_first)
    return pairs[:limit]


def _column_series(
    z: list[list[float | None]], col_i: int
) -> list[float]:
    vals: list[float] = []
    for row in z:
        if col_i >= len(row) or row[col_i] is None:
            continue
        vals.append(float(row[col_i]))
    return vals


def _industry_shape_stats(
    names: list[str],
    z: list[list[float | None]],
    *,
    hot_threshold: float = 0.70,
) -> dict[str, list]:
    """Summaries for long-red / cool-then-rewarm / challenger patterns."""
    persistence: list[tuple[str, int, float, float]] = []
    rewarm: list[tuple[str, float, float, float, float]] = []
    challengers: list[tuple[str, float, float, float]] = []

    end_vals = _row_hotness(z, len(z) - 1) if z else []
    ranked_end = sorted(
        (
            (i, float(v))
            for i, v in enumerate(end_vals)
            if v is not None and i < len(names)
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    end_rank = {i: rank for rank, (i, _v) in enumerate(ranked_end, start=1)}
    hottest_end = ranked_end[0][1] if ranked_end else None

    n_days = len(z)
    for col_i, name in enumerate(names):
        series = _column_series(z, col_i)
        if len(series) < max(8, n_days // 3):
            continue
        hot_days = sum(1 for v in series if v >= hot_threshold)
        mean_hot = sum(series) / len(series)
        end_v = series[-1]
        persistence.append((name, hot_days, mean_hot, end_v))

        # Split window into thirds: early / mid / late.
        a = max(1, len(series) // 3)
        early = series[:a]
        mid = series[a : 2 * a]
        late = series[2 * a :]
        if not early or not mid or not late:
            continue
        early_m = sum(early) / len(early)
        mid_m = sum(mid) / len(mid)
        late_m = sum(late) / len(late)
        # Cool-then-rewarm: mid dips vs early, late recovers vs mid.
        if mid_m + 0.05 < early_m and late_m > mid_m + 0.05:
            rewarm.append((name, early_m, mid_m, late_m, end_v))

        rank = end_rank.get(col_i)
        if (
            hottest_end is not None
            and rank is not None
            and 2 <= rank <= 12
            and late_m > mid_m + 0.04
            and end_v >= hottest_end - 0.12
        ):
            challengers.append((name, end_v, late_m - mid_m, float(rank)))

    persistence.sort(key=lambda item: (item[1], item[2]), reverse=True)
    rewarm.sort(key=lambda item: (item[3] - item[2], item[4]), reverse=True)
    challengers.sort(key=lambda item: (item[2], item[1]), reverse=True)
    return {
        "persistence": persistence[:8],
        "rewarm": rewarm[:8],
        "challengers": challengers[:6],
        "hottest_end": hottest_end,
    }


def _concept_theme_hits(board_codes: list[str]) -> list[tuple[str, int, int]]:
    index = {code: i for i, code in enumerate(board_codes)}
    rows: list[tuple[str, int, int]] = []
    for theme in list_themes():
        members = theme_board_codes(theme)
        hit = sum(1 for code in members if code in index)
        rows.append((_theme_label(theme.title), hit, len(members)))
    rows.sort(key=lambda item: (-item[1], item[0]))
    return rows


def _data_block(
    *,
    window_dates: list[date],
    theme_payload: dict,
    industry: dict,
    concept_top: dict,
) -> str:
    as_of = window_dates[-1]
    mid = window_dates[(len(window_dates) - 1) // 2]
    late = late_quarter_dates(window_dates)
    spectrum = theme_payload["spectrum"]
    ranked = theme_payload["ranked"]

    spectrum_raw = spectrum.get("raw_z") or spectrum["z"]
    ranked_raw = ranked.get("raw_z") or ranked["z"]
    mid_i = (len(window_dates) - 1) // 2
    end_i = len(window_dates) - 1
    start_i = 0

    ind_dates = industry.get("dates") or []
    ind_end_i = len(ind_dates) - 1 if ind_dates else end_i
    ind_mid_i = (len(ind_dates) - 1) // 2 if ind_dates else mid_i

    lines = [
        f"截止日：{as_of.isoformat()}",
        f"窗口起点：{window_dates[0].isoformat()}",
        f"窗口交易日数：{len(window_dates)}",
        f"近热排序基准日（窗口中间日）：{mid.isoformat()}",
        (
            f"概念 Top 筛选段（靠后四分之一）："
            f"{late[0].isoformat() if late else ''} → {late[-1].isoformat() if late else ''}"
        ),
        f"概念 TopN：{concept_top.get('top_n') or CONCEPT_TOP_N}"
        f"（实取 {concept_top.get('top_count') or concept_top.get('board_count') or 0}）"
        f"∪主题补入 {concept_top.get('theme_added') or 0}"
        f" → 合计 {concept_top.get('board_count') or 0}",
        "",
        "## 主题（光谱序）群A翻转热度",
        "主题\t起点热度\t中间日热度\t截止日热度",
    ]
    labels = spectrum["theme_labels"]
    start_vals = _row_hotness(spectrum_raw, start_i)
    mid_vals = _row_hotness(spectrum_raw, mid_i)
    end_vals = _row_hotness(spectrum_raw, end_i)
    for i, label in enumerate(labels):
        lines.append(
            f"{label}\t{_fmt(start_vals[i] if i < len(start_vals) else None)}"
            f"\t{_fmt(mid_vals[i] if i < len(mid_vals) else None)}"
            f"\t{_fmt(end_vals[i] if i < len(end_vals) else None)}"
        )

    scenarios = theme_payload.get("scenarios") or []
    lines.extend(
        [
            "",
            "## 光谱情景（自动标签；跟过程不跟高度）",
            "主题\t情景\t近端斜率\t斜率值\t截止热度\t读法",
        ]
    )
    if scenarios:
        for row in scenarios:
            lines.append(
                f"{row.get('label') or ''}\t"
                f"{row.get('scenario') or '—'}\t"
                f"{row.get('slope_label') or ''}\t"
                f"{_fmt(row.get('near_slope'), 4)}\t"
                f"{_fmt(row.get('hotness'))}\t"
                f"{row.get('hint') or ''}"
            )
    else:
        lines.append("（本窗无情景表）")

    lines.extend(
        [
            "",
            "## 主题近热排序（中间日热度高→低，整窗固定）",
            "名次\t主题\t中间日热度\t截止日热度",
        ]
    )
    ranked_labels = ranked["theme_labels"]
    ranked_mid = _row_hotness(ranked_raw, mid_i)
    ranked_end = _row_hotness(ranked_raw, end_i)
    for i, label in enumerate(ranked_labels):
        lines.append(
            f"{i + 1}\t{label}\t{_fmt(ranked_mid[i] if i < len(ranked_mid) else None)}"
            f"\t{_fmt(ranked_end[i] if i < len(ranked_end) else None)}"
        )

    ind_names = industry.get("board_names") or []
    ind_z = industry.get("z_short") or []
    ind_end = _row_hotness(ind_z, ind_end_i)
    ind_mid = _row_hotness(ind_z, ind_mid_i)
    hot_ind = _named_levels(ind_names, ind_end, hottest_first=True, limit=8)
    cold_ind = _named_levels(ind_names, ind_end, hottest_first=False, limit=8)
    warming: list[tuple[str, float, float, float]] = []
    for name, end_v, mid_v in zip(ind_names, ind_end, ind_mid):
        if end_v is None or mid_v is None:
            continue
        delta = float(end_v) - float(mid_v)
        warming.append((name, delta, float(mid_v), float(end_v)))
    warming.sort(key=lambda item: item[1], reverse=True)

    lines.extend(
        [
            "",
            "## 行业板块（轨迹叶序图摘要，翻转热度）",
            f"行业数：{industry.get('board_count') or len(ind_names)}",
            "截止日最热：",
        ]
    )
    for name, value in hot_ind:
        lines.append(f"  {name}\t{_fmt(value)}")
    lines.append("截止日最冷：")
    for name, value in cold_ind:
        lines.append(f"  {name}\t{_fmt(value)}")
    lines.append("中间日→截止日升温最多：")
    for name, delta, mid_v, end_v in warming[:8]:
        lines.append(
            f"  {name}\tΔ={_fmt(delta)}\t中间={_fmt(mid_v)}\t截止={_fmt(end_v)}"
        )
    lines.append("中间日→截止日降温最多：")
    for name, delta, mid_v, end_v in list(reversed(warming[-8:])):
        lines.append(
            f"  {name}\tΔ={_fmt(delta)}\t中间={_fmt(mid_v)}\t截止={_fmt(end_v)}"
        )

    shapes = _industry_shape_stats(ind_names, ind_z)
    lines.extend(
        [
            "",
            "## 行业时间形态摘要（翻转热度；高热日=热度≥0.70）",
            "长红柱（高热天数多 / 窗内均值高）：",
            "行业\t高热天数\t窗内均值\t截止热度",
        ]
    )
    for name, hot_days, mean_hot, end_v in shapes["persistence"]:
        lines.append(
            f"  {name}\t{hot_days}\t{_fmt(mean_hot)}\t{_fmt(end_v)}"
        )
    lines.extend(
        [
            "冷却后再抬（前高→中段回落→近端回升）：",
            "行业\t前段均值\t中段均值\t近段均值\t截止热度",
        ]
    )
    for name, early_m, mid_m, late_m, end_v in shapes["rewarm"]:
        lines.append(
            f"  {name}\t{_fmt(early_m)}\t{_fmt(mid_m)}\t{_fmt(late_m)}\t{_fmt(end_v)}"
        )
    lines.extend(
        [
            "候补龙头（截止非第1但近段升温且已进前列）：",
            "行业\t截止热度\t近段相对中段升幅\t截止名次",
        ]
    )
    if shapes["hottest_end"] is not None:
        lines.append(f"  （对照）截止日最热热度≈{_fmt(shapes['hottest_end'])}")
    for name, end_v, lift, rank in shapes["challengers"]:
        lines.append(
            f"  {name}\t{_fmt(end_v)}\t{_fmt(lift)}\t{int(rank)}"
        )
    if not shapes["persistence"] and not shapes["rewarm"] and not shapes["challengers"]:
        lines.append("  （本窗未识别出显著长红柱/二波/候补形态）")

    con_names = concept_top.get("board_names") or []
    con_z = concept_top.get("z_short") or []
    con_end = _row_hotness(con_z, end_i)
    hot_con = _named_levels(con_names, con_end, hottest_first=True, limit=15)
    lines.extend(
        [
            "",
            f"## 概念短热 Top{concept_top.get('top_n') or CONCEPT_TOP_N}∪主题"
            f"（截止日翻转热度代表）",
            f"入选概念数：{concept_top.get('board_count') or len(con_names)}"
            f"（主题补入 {concept_top.get('theme_added') or 0}）",
        ]
    )
    for name, value in hot_con:
        lines.append(f"  {name}\t{_fmt(value)}")

    lines.extend(
        [
            "",
            "## 主题穿透（落入概念 Top 的成员数 x / 主题成员总数 y）",
            "主题\tx\ty",
        ]
    )
    for label, hit, total in _concept_theme_hits(concept_top.get("board_codes") or []):
        lines.append(f"{label}\t{hit}\t{total}")

    lines.extend(
        [
            "",
            "## 读图提示（供组织叙述，不要复述本段）",
            "先写清当前热/冷并点名光谱情景（萌芽/中位/久热+斜率）；"
            "行业侧结合长红柱、二波回补、候补龙头；再写三层衔接；"
            "下文用可验证条件句盯萌芽续热或久热转冷，勿把中位默认可跟。",
        ]
    )
    return "\n".join(lines)


def build_theme_wave_reading_prompt(
    as_of: date | None = None,
) -> tuple[PromptTemplate, str, date]:
    template = load_prompt("theme-wave-reading")
    window = int(template.config.get("window_trading_days") or DEFAULT_WINDOW_DAYS)

    target = as_of or date.today()
    ending = fetch_heat_dates_ending("concept", target, 1)
    if not ending:
        raise RuntimeError("no concept heat rows to interpret")
    selected = ending[-1]

    window_dates = fetch_heat_dates_ending("concept", selected, window)
    if not window_dates:
        raise RuntimeError("no concept heat window to interpret")

    heat_rows = fetch_concept_heat_window(window_dates[0], window_dates[-1])
    theme_payload = build_theme_wave_payload(
        window_dates=window_dates,
        heat_rows=heat_rows,
        densify=4,
    )
    if theme_payload.get("empty_message") or not theme_payload.get("spectrum"):
        raise RuntimeError(theme_payload.get("empty_message") or "no theme wave data")

    industry_dates = fetch_heat_dates_ending("industry", selected, window)
    if not industry_dates:
        raise RuntimeError("no industry heat window to interpret")
    industry = build_industry_board_heat_payload(
        window_dates=industry_dates,
        heat_rows=fetch_industry_heat_window(industry_dates[0], industry_dates[-1]),
    )
    if industry.get("empty_message"):
        raise RuntimeError(industry["empty_message"])

    concept_top = build_concept_top_heat_payload(
        window_dates=window_dates,
        heat_rows=fetch_concept_heat_named_window(
            window_dates[0], window_dates[-1]
        ),
    )
    if concept_top.get("empty_message"):
        raise RuntimeError(concept_top["empty_message"])

    resolved = window_dates[-1]
    body = Template(template.body, undefined=StrictUndefined).render(
        window_trading_days=len(window_dates),
        data_block=_data_block(
            window_dates=window_dates,
            theme_payload=theme_payload,
            industry=industry,
            concept_top=concept_top,
        ),
    )
    return template, body, resolved
