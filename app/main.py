from datetime import date, datetime, timedelta
from pathlib import Path

import baostock as bs
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.charts.board_rotation import render_board_rotation
from app.charts.kline import render_kline
from app.charts.mini_kline import render_mini_kline
from app.charts.theme_wave import (
    render_board_heat_heatmap,
    render_theme_wave_contour,
    render_theme_wave_surface,
)
from app.charts.concept_wavelet import (
    render_wavelet_energy,
    render_wavelet_multiscale,
)
from app.charts.theme_heat import render_theme_charts, render_theme_group_chart
from app.db import (
    fetch_board_daily_bars_from_db,
    fetch_board_daily_bars_many,
    fetch_board_heat_series,
    fetch_board_name,
    fetch_board_rotation,
    fetch_concept_heat_named_window,
    fetch_concept_heat_window,
    fetch_daily_bars_from_db,
    fetch_heat_dates_ending,
    fetch_industry_heat_window,
    fetch_rotation_dates,
    fetch_trading_dates_ending,
    fetch_latest_trading_stocks,
)
from app.env import load_env
from app.interpret.service import (
    InterpretConfigError,
    InterpretFormatError,
    Interpretation,
    UnknownTemplate,
    interpret,
)
from app.market_data.board_heat import top_short_heat_keys
from app.market_data.csi500 import fetch_csi500_closes
from app.market_data.providers import baostock_kline
from app.sync_runner import JOB_IDS, get_runner_state, start_job
from app.sync_status import fetch_sync_dashboard_status
from app.themes import build_theme_view, get_theme, list_themes
from app.themes.concept_wave import build_concept_top_heat_payload
from app.themes.concept_wavelet import FEATURE_TOP_N, build_concept_wavelet_payload
from app.themes.industry_wavelet import build_industry_wavelet_payload
from app.themes.config import ThemeConfig, theme_board_codes
from app.themes.industry_wave import build_industry_board_heat_payload
from app.themes.wave_surface import build_theme_wave_payload

MINI_KLINE_TRADING_DAYS = 60

load_env()

_ROTATION_PAGES = {
    "industry": {
        "title": "板块热度轮转",
        "kind_label": "行业板块",
        "rotation_path": "/boards/rotation",
        "rotation_api": "/api/boards/rotation",
        "interpret_template": "industry-heat-rotation",
        "kline_prefix": "/boards/industry",
        "show_all_labels": True,
        "empty_message": "还没有行业板块热度。先同步板块日 K，再运行行业热度计算。",
        "missing_message": "没有这个板块",
        "missing_board": "没有这个行业板块",
    },
    "concept": {
        "title": "概念热度轮转",
        "kind_label": "概念",
        "rotation_path": "/boards/concept/rotation",
        "rotation_api": "/api/boards/concept/rotation",
        "interpret_template": "concept-heat-rotation",
        "kline_prefix": "/boards/concept",
        "show_all_labels": False,
        "empty_message": "还没有概念热度。先同步概念日 K，再运行概念热度计算。",
        "missing_message": "没有这个概念",
        "missing_board": "没有这个概念",
    },
}

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class SyncRunRequest(BaseModel):
    trading_days: int | None = Field(default=200, ge=1)
    resume: bool = True
    day: str | None = None


class InterpretRequest(BaseModel):
    as_of: str | None = None
    force: bool = False
    window_trading_days: int | None = Field(default=None, ge=20, le=180)


@app.post("/api/interpret/{template_name}")
def interpret_api(template_name: str, body: InterpretRequest | None = None) -> dict:
    try:
        requested = _parse_optional_day(body.as_of if body else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        result = interpret(
            template_name,
            requested,
            force=bool(body.force) if body else False,
            window_trading_days=(
                body.window_trading_days if body else None
            ),
        )
    except UnknownTemplate as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InterpretConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InterpretFormatError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _interpretation_payload(result)


def _interpretation_payload(result: Interpretation) -> dict:
    return {
        "template": result.template,
        "as_of": result.as_of.isoformat(),
        "model": result.model,
        "cached": result.cached,
        "content": result.content,
        "reading": result.reading,
    }


def _parse_optional_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"invalid day {value!r}; expected YYYY-MM-DD") from exc


def _parse_day(value: str | None, default: date) -> date:
    if not value:
        return default
    return datetime.strptime(value, "%Y-%m-%d").date()


def _bars_to_records(bars) -> list[dict]:
    return [
        {
            "trade_date": bar.trade_date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
        for bar in bars
    ]


def _load_online_index(start: date, end: date) -> list[dict]:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"baostock login failed: {login.error_msg}")
    try:
        bars = baostock_kline.fetch_daily_bars("sh.000001", start, end)
        return _bars_to_records(bars)
    finally:
        bs.logout()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/index-all", response_class=HTMLResponse)
def index_all_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index_all.html", {})


@app.get("/sync", response_class=HTMLResponse)
def sync_dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "sync_dashboard.html", {})


@app.get("/api/sync/status")
def sync_status_api() -> dict:
    return {
        "runner": get_runner_state(),
        "items": fetch_sync_dashboard_status(),
    }


@app.post("/api/sync/run/{job_id}")
def sync_run_api(job_id: str, body: SyncRunRequest | None = None) -> dict:
    if job_id not in JOB_IDS:
        raise HTTPException(status_code=404, detail=f"unknown job_id: {job_id}")
    payload = body or SyncRunRequest()
    try:
        state = start_job(
            job_id,
            trading_days=payload.trading_days,
            resume=payload.resume,
            day=_parse_optional_day(payload.day),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "runner": state}


@app.get("/stocks", response_class=HTMLResponse)
def stocks_page(request: Request) -> HTMLResponse:
    sync_date, stocks = fetch_latest_trading_stocks(limit=30)
    return templates.TemplateResponse(
        request,
        "stocks.html",
        {
            "sync_date": sync_date,
            "stocks": stocks,
        },
    )


@app.get("/api/stocks/latest")
def stocks_latest_api() -> dict:
    sync_date, stocks = fetch_latest_trading_stocks(limit=30)
    return {
        "sync_date": sync_date.isoformat() if sync_date else None,
        "count": len(stocks),
        "stocks": [
            {
                "trade_date": item.trade_date.isoformat(),
                "code": item.code,
                "code_name": item.code_name,
            }
            for item in stocks
        ],
    }


def _rotation_page_fields(board_type: str) -> dict:
    page = _ROTATION_PAGES[board_type]
    return {
        "title": page["title"],
        "kind_label": page["kind_label"],
        "rotation_api": page["rotation_api"],
        "interpret_template": page["interpret_template"],
        "kline_prefix": page["kline_prefix"],
        "show_all_labels": page["show_all_labels"],
        "empty_message": page["empty_message"],
        "missing_message": page["missing_message"],
    }


def _rotation_payload(
    board_type: str,
    as_of: date | None,
    *,
    include_plotlyjs: bool,
    highlight: str | None = None,
    labels: list[str] | None = None,
) -> dict:
    dates = fetch_rotation_dates(board_type, 10)
    if as_of is not None and as_of not in dates:
        raise HTTPException(status_code=400, detail="date is outside the last 11 trading days")
    selected = as_of or (dates[-1] if dates else None)
    got_as_of, prev_date, rows = fetch_board_rotation(board_type, selected)
    if board_type == "concept":
        kept = top_short_heat_keys(
            [(row.board_code, row.heat_short) for row in rows]
        )
        rows = [row for row in rows if row.board_code in kept]
    name = highlight.strip() if highlight else ""
    matched = bool(name) and any(row.board_name == name for row in rows)
    page = _ROTATION_PAGES[board_type]
    label_names = None
    if not page["show_all_labels"]:
        label_names = {item.strip() for item in (labels or []) if item and item.strip()}
    chart_html = None
    short_count = 0
    long_count = 0
    if got_as_of is not None and prev_date is not None:
        chart_html, short_count, long_count = render_board_rotation(
            rows,
            as_of=got_as_of.isoformat(),
            prev_date=prev_date.isoformat(),
            include_plotlyjs=include_plotlyjs,
            highlight=name if matched else None,
            label_names=label_names,
        )
    return {
        "dates": [day.isoformat() for day in dates],
        "as_of": got_as_of.isoformat() if got_as_of else None,
        "prev_date": prev_date.isoformat() if prev_date else None,
        "chart_html": chart_html,
        "short_count": short_count,
        "long_count": long_count,
        "highlight_matched": matched if name else None,
        **_rotation_page_fields(board_type),
    }


def _rotation_page(request: Request, board_type: str) -> HTMLResponse:
    payload = _rotation_payload(board_type, None, include_plotlyjs=True)
    return templates.TemplateResponse(request, "board_rotation.html", payload)


def _rotation_api(
    board_type: str,
    as_of: str,
    highlight: str | None,
    label: list[str] | None,
) -> dict:
    try:
        day = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="as_of must be YYYY-MM-DD") from exc
    payload = _rotation_payload(
        board_type,
        day,
        include_plotlyjs=False,
        highlight=highlight,
        labels=label,
    )
    if payload["chart_html"] is None:
        raise HTTPException(status_code=404, detail=f"no {board_type} heat for that date")
    return payload


@app.get("/boards/rotation", response_class=HTMLResponse)
def board_rotation_page(request: Request) -> HTMLResponse:
    return _rotation_page(request, "industry")


@app.get("/boards/concept/rotation", response_class=HTMLResponse)
def concept_rotation_page(request: Request) -> HTMLResponse:
    return _rotation_page(request, "concept")


@app.get("/boards/concept/themes", response_class=HTMLResponse)
def concept_themes_hub_page(request: Request) -> HTMLResponse:
    payload = _themes_hub_page_payload(None, include_plotlyjs=False)
    return templates.TemplateResponse(request, "concept_themes_hub.html", payload)


@app.get("/boards/concept/themes/wave", response_class=HTMLResponse)
def concept_themes_wave_page(
    request: Request,
    days: int = Query(40, ge=20, le=180),
) -> HTMLResponse:
    payload = _themes_wave_page_payload(days=days, include_plotlyjs=False)
    return templates.TemplateResponse(request, "theme_wave.html", payload)


@app.get("/boards/concept/themes/wave/wavelet", response_class=HTMLResponse)
def concept_themes_wave_wavelet_page(
    request: Request,
    days: int = Query(60, ge=20, le=180),
) -> HTMLResponse:
    payload = _themes_wave_wavelet_page_payload(scope="concept", days=days)
    return templates.TemplateResponse(request, "theme_wave_wavelet.html", payload)


@app.get("/boards/concept/themes/wave/industry-wavelet", response_class=HTMLResponse)
def concept_themes_wave_industry_wavelet_page(
    request: Request,
    days: int = Query(60, ge=20, le=180),
) -> HTMLResponse:
    payload = _themes_wave_wavelet_page_payload(scope="industry", days=days)
    return templates.TemplateResponse(request, "theme_wave_wavelet.html", payload)


@app.get("/api/boards/concept/themes")
def concept_themes_hub_api(as_of: str = Query(...)) -> dict:
    try:
        day = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="as_of must be YYYY-MM-DD") from exc
    return _themes_hub_payload(day, include_plotlyjs=False)


@app.get("/boards/concept/themes/{theme_id}", response_class=HTMLResponse)
def concept_theme_page(request: Request, theme_id: str) -> HTMLResponse:
    payload = _theme_page_payload(theme_id, None, include_plotlyjs=False)
    return templates.TemplateResponse(request, "concept_theme.html", payload)


@app.get("/api/boards/concept/themes/{theme_id}")
def concept_theme_api(theme_id: str, as_of: str = Query(...)) -> dict:
    try:
        day = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="as_of must be YYYY-MM-DD") from exc
    return _theme_api_payload(theme_id, day, include_plotlyjs=False)


def _themes_hub_page_payload(
    as_of: date | None,
    *,
    include_plotlyjs: bool,
) -> dict:
    data = _themes_hub_payload(as_of, include_plotlyjs=include_plotlyjs)
    return {
        "title": "主题域",
        "as_of": data["as_of"],
        "dates": data["dates"],
        "hub_api": "/api/boards/concept/themes",
        "back_href": "/",
        "back_label": "索引",
        "initial": data,
    }


def _themes_wave_empty(
    *,
    empty_message: str,
    axis_note: str = "",
    rank_axis_note: str = "",
) -> dict:
    return {
        "title": "主题热度水面",
        "axis_note": axis_note,
        "rank_axis_note": rank_axis_note,
        "industry_axis_note": "",
        "concept_axis_note": "",
        "dates": [],
        "as_of": None,
        "rank_as_of": None,
        "industry_board_count": 0,
        "concept_board_count": 0,
        "concept_select_from": None,
        "concept_select_to": None,
        "concept_theme_options": [],
        "interpret_template": "theme-wave-reading",
        "spectrum_chart_html": "",
        "spectrum_map_html": "",
        "ranked_chart_html": "",
        "ranked_map_html": "",
        "industry_short_html": "",
        "concept_short_html": "",
        "wavelet_href": "/boards/concept/themes/wave/wavelet",
        "industry_wavelet_href": "/boards/concept/themes/wave/industry-wavelet",
        "spectrum_links": [],
        "ranked_links": [],
        "empty_message": empty_message,
    }


def _concept_theme_highlight_options(board_codes: list[str]) -> list[dict]:
    """Themes → column indices that appear in the concept Top-N chart."""
    if not board_codes:
        return []
    index_by_code = {code: i for i, code in enumerate(board_codes)}
    options: list[dict] = []
    for theme in list_themes():
        member_codes = theme_board_codes(theme)
        indices = sorted(
            {
                index_by_code[code]
                for code in member_codes
                if code in index_by_code
            }
        )
        label = theme.title.replace("主题域", "").strip() or theme.theme_id
        options.append(
            {
                "id": theme.theme_id,
                "label": label,
                "indices": indices,
                "hit_count": len(indices),
                "member_count": len(member_codes),
            }
        )
    return options


def _themes_wave_page_payload(*, days: int, include_plotlyjs: bool) -> dict:
    slider_dates = fetch_rotation_dates("concept", 10)
    selected = slider_dates[-1] if slider_dates else None
    if selected is None:
        return _themes_wave_empty(empty_message="还没有概念热度。")
    window_dates = fetch_heat_dates_ending("concept", selected, days)
    if not window_dates:
        return _themes_wave_empty(empty_message="窗口内没有热度日期")
    heat_rows = fetch_concept_heat_window(window_dates[0], window_dates[-1])
    payload = build_theme_wave_payload(
        window_dates=window_dates,
        heat_rows=heat_rows,
        densify=4,
    )
    if payload.get("empty_message") or not payload.get("spectrum") or not payload.get(
        "ranked"
    ):
        return _themes_wave_empty(
            empty_message=payload.get("empty_message") or "没有可绘制的曲面",
            axis_note=payload.get("axis_note") or "",
            rank_axis_note=payload.get("rank_axis_note") or "",
        )
    spectrum = payload["spectrum"]
    ranked = payload["ranked"]
    rank_as_of = payload.get("rank_as_of") or payload["as_of"]
    spectrum_chart_html = render_theme_wave_surface(
        dates=spectrum["dates"],
        x=spectrum["x"],
        z=spectrum["z"],
        x_tickvals=spectrum["x_tickvals"],
        x_ticktext=spectrum["x_ticktext"],
        include_plotlyjs=include_plotlyjs,
        title="光谱水面 · 可拖拽旋转",
        xaxis_title="主题光谱（防守 → 科技）",
    )
    spectrum_map_html = render_theme_wave_contour(
        dates=spectrum["dates"],
        x=spectrum["x"],
        z=spectrum["z"],
        x_tickvals=spectrum["x_tickvals"],
        x_ticktext=spectrum["x_ticktext"],
        include_plotlyjs=False,
        title="光谱等位图 · 点击取点",
        xaxis_title="主题光谱（防守 → 科技）",
    )
    ranked_chart_html = render_theme_wave_surface(
        dates=ranked["dates"],
        x=ranked["x"],
        z=ranked["z"],
        x_tickvals=ranked["x_tickvals"],
        x_ticktext=ranked["x_ticktext"],
        include_plotlyjs=False,
        title=f"近热排序水面 · 中间日 {rank_as_of} 热度从高到低",
        xaxis_title="近热排序（高 → 低）",
    )
    ranked_map_html = render_theme_wave_contour(
        dates=ranked["dates"],
        x=ranked["x"],
        z=ranked["z"],
        x_tickvals=ranked["x_tickvals"],
        x_ticktext=ranked["x_ticktext"],
        include_plotlyjs=False,
        title="近热排序等位图 · 点击取点",
        xaxis_title="近热排序（高 → 低）",
    )

    industry_short_html = ""
    industry_axis_note = ""
    industry_board_count = 0
    industry_dates = fetch_heat_dates_ending("industry", selected, days)
    if industry_dates:
        industry_rows = fetch_industry_heat_window(
            industry_dates[0], industry_dates[-1]
        )
        industry = build_industry_board_heat_payload(
            window_dates=industry_dates,
            heat_rows=industry_rows,
        )
        if not industry.get("empty_message"):
            industry_axis_note = industry["axis_note"]
            industry_board_count = industry["board_count"]
            industry_short_html = render_board_heat_heatmap(
                dates=industry["dates"],
                x=industry["x"],
                z=industry["z_short"],
                x_tickvals=industry["x_tickvals"],
                x_ticktext=industry["x_ticktext"],
                include_plotlyjs=False,
                height=620,
                title="行业短热 · 轨迹聚类叶序",
                xaxis_title="行业板块（共动近 → 相邻）",
            )

    concept_short_html = ""
    concept_axis_note = ""
    concept_board_count = 0
    concept_select_from = None
    concept_select_to = None
    concept_theme_options: list[dict] = []
    concept_named_rows = fetch_concept_heat_named_window(
        window_dates[0], window_dates[-1]
    )
    concept_top = build_concept_top_heat_payload(
        window_dates=window_dates,
        heat_rows=concept_named_rows,
    )
    if not concept_top.get("empty_message"):
        concept_axis_note = concept_top["axis_note"]
        concept_board_count = concept_top["board_count"]
        concept_select_from = concept_top["select_from"]
        concept_select_to = concept_top["select_to"]
        concept_theme_options = _concept_theme_highlight_options(
            concept_top["board_codes"]
        )
        concept_short_html = render_board_heat_heatmap(
            dates=concept_top["dates"],
            x=concept_top["x"],
            z=concept_top["z_short"],
            x_tickvals=concept_top["x_tickvals"],
            x_ticktext=concept_top["x_ticktext"],
            include_plotlyjs=False,
            height=620,
            title=f"概念短热 Top{concept_top['top_n']} · 轨迹聚类叶序",
            xaxis_title="概念（共动近 → 相邻）",
            entity_label="概念",
        )

    return {
        "title": "主题热度水面",
        "axis_note": payload["axis_note"],
        "rank_axis_note": payload["rank_axis_note"],
        "industry_axis_note": industry_axis_note,
        "concept_axis_note": concept_axis_note,
        "dates": payload["dates"],
        "as_of": payload["as_of"],
        "rank_as_of": rank_as_of,
        "industry_board_count": industry_board_count,
        "concept_board_count": concept_board_count,
        "concept_select_from": concept_select_from,
        "concept_select_to": concept_select_to,
        "concept_theme_options": concept_theme_options,
        "interpret_template": "theme-wave-reading",
        "spectrum_chart_html": spectrum_chart_html,
        "spectrum_map_html": spectrum_map_html,
        "ranked_chart_html": ranked_chart_html,
        "ranked_map_html": ranked_map_html,
        "industry_short_html": industry_short_html,
        "concept_short_html": concept_short_html,
        "wavelet_href": f"/boards/concept/themes/wave/wavelet?days={days}",
        "industry_wavelet_href": f"/boards/concept/themes/wave/industry-wavelet?days={days}",
        "spectrum_links": list(zip(spectrum["theme_labels"], spectrum["theme_hrefs"])),
        "ranked_links": list(zip(ranked["theme_labels"], ranked["theme_hrefs"])),
        "empty_message": None,
    }


def _wavelet_page_empty(
    *,
    title: str,
    empty_message: str,
    interpret_template: str,
    entity_label: str,
    reading_heading: str,
    map_heading: str,
    map_section_title: str,
    roster_note: str,
) -> dict:
    return {
        "title": title,
        "empty_message": empty_message,
        "as_of": None,
        "dates": [],
        "window_days": 0,
        "top_n": 0,
        "late_days": 0,
        "extremum_days": 0,
        "select_from": None,
        "select_to": None,
        "axis_note": "",
        "multiscale_html": "",
        "energy_html": "",
        "energy": [],
        "directions": [],
        "band_extrema": [],
        "feature_blocks": [],
        "feature_top_n": FEATURE_TOP_N,
        "interpret_template": interpret_template,
        "entity_label": entity_label,
        "reading_heading": reading_heading,
        "map_heading": map_heading,
        "map_section_title": map_section_title,
        "roster_note": roster_note,
    }


def _themes_wave_wavelet_page_payload(*, scope: str, days: int) -> dict:
    if scope == "industry":
        board_type = "industry"
        title = "行业板块短热 · 二维小波"
        interpret_template = "industry-wavelet-reading"
        entity_label = "行业"
        reading_heading = "行业映射解读"
        map_heading = "行业映射表"
        map_section_title = "行业映射"
        roster_note = (
            f"与上方全部行业叶序一致；每类按特征分排序取前 {FEATURE_TOP_N}。"
            "解读与本表同一窗口，只串读点名、不再制表。"
        )
        empty_no_data = "还没有行业热度。"
    else:
        board_type = "concept"
        title = "概念短热 · 二维小波"
        interpret_template = "concept-wavelet-reading"
        entity_label = "概念"
        reading_heading = "概念映射解读"
        map_heading = "概念映射表"
        map_section_title = "概念映射"
        roster_note = (
            f"与上方 Top 叶序一致；每类按特征分排序取前 {FEATURE_TOP_N}。"
            "解读与本表同一窗口，只串读点名、不再制表。"
        )
        empty_no_data = "还没有概念热度。"

    slider_dates = fetch_rotation_dates(board_type, 10)
    selected = slider_dates[-1] if slider_dates else None
    if selected is None:
        return _wavelet_page_empty(
            title=title,
            empty_message=empty_no_data,
            interpret_template=interpret_template,
            entity_label=entity_label,
            reading_heading=reading_heading,
            map_heading=map_heading,
            map_section_title=map_section_title,
            roster_note=roster_note,
        )
    window_dates = fetch_heat_dates_ending(board_type, selected, days)
    if not window_dates:
        return _wavelet_page_empty(
            title=title,
            empty_message="窗口内没有热度日期",
            interpret_template=interpret_template,
            entity_label=entity_label,
            reading_heading=reading_heading,
            map_heading=map_heading,
            map_section_title=map_section_title,
            roster_note=roster_note,
        )

    if scope == "industry":
        payload = build_industry_wavelet_payload(
            window_dates=window_dates,
            heat_rows=fetch_industry_heat_window(
                window_dates[0], window_dates[-1]
            ),
        )
    else:
        payload = build_concept_wavelet_payload(
            window_dates=window_dates,
            heat_rows=fetch_concept_heat_named_window(
                window_dates[0], window_dates[-1]
            ),
        )
    if payload.get("empty_message"):
        return _wavelet_page_empty(
            title=title,
            empty_message=payload["empty_message"],
            interpret_template=interpret_template,
            entity_label=entity_label,
            reading_heading=reading_heading,
            map_heading=map_heading,
            map_section_title=map_section_title,
            roster_note=roster_note,
        )

    bands = payload["bands"]
    multiscale_html = render_wavelet_multiscale(
        dates=payload["dates"],
        names=payload["board_names"],
        z_short=payload["z_short"],
        approx=bands["approx"],
        d3=bands["d3"],
        d1=bands["d1"],
        as_of=payload["as_of"],
        include_plotlyjs=True,
        entity_label=entity_label,
    )
    energy_html = render_wavelet_energy(
        energy=payload["energy"],
        directions=payload["directions"],
        as_of=payload["as_of"],
        top_n=payload["top_n"] or payload["board_count"],
        include_plotlyjs=False,
    )
    feature_blocks = [
        {
            "title": "主线占位",
            "note": "A3 高且近端仍热",
            "rows": payload["features"]["occupancy"],
        },
        {
            "title": "占位回落",
            "note": "窗内曾热、近端回落",
            "rows": payload["features"]["fade"],
        },
        {
            "title": "二波回补",
            "note": "D3 中段偏冷、近段偏热",
            "rows": payload["features"]["rewarm"],
        },
        {
            "title": "中粗活跃",
            "note": "D3 能量高（起伏大）",
            "rows": payload["features"]["mid_active"],
        },
        {
            "title": "细脉冲",
            "note": "D1 相对粗结构偏高",
            "rows": payload["features"]["pulse"],
        },
    ]
    if scope == "industry":
        roster_note = (
            f"与上方全部 {payload['board_count']} 个行业叶序一致；"
            f"每类按特征分排序取前 {FEATURE_TOP_N}。"
            "解读与本表同一窗口，只串读点名、不再制表。"
        )
    else:
        roster_note = (
            f"与上方 Top{payload['top_n']} 叶序一致；"
            f"每类按特征分排序取前 {FEATURE_TOP_N}。"
            "解读与本表同一窗口，只串读点名、不再制表。"
        )
    return {
        "title": title,
        "empty_message": None,
        "as_of": payload["as_of"],
        "dates": payload["dates"],
        "window_days": payload["window_days"],
        "top_n": payload["top_n"],
        "late_days": payload["late_days"],
        "extremum_days": payload.get("extremum_days") or 0,
        "select_from": payload.get("select_from"),
        "select_to": payload.get("select_to"),
        "axis_note": payload["axis_note"],
        "multiscale_html": multiscale_html,
        "energy_html": energy_html,
        "energy": payload["energy"],
        "directions": payload["directions"],
        "band_extrema": payload.get("band_extrema") or [],
        "feature_blocks": feature_blocks,
        "feature_top_n": FEATURE_TOP_N,
        "interpret_template": interpret_template,
        "entity_label": entity_label,
        "reading_heading": reading_heading,
        "map_heading": map_heading,
        "map_section_title": map_section_title,
        "roster_note": roster_note,
    }


def _themes_hub_payload(
    as_of: date | None,
    *,
    include_plotlyjs: bool,
) -> dict:
    themes = list_themes()
    slider_dates = fetch_rotation_dates("concept", 10)
    if as_of is not None and as_of not in slider_dates:
        raise HTTPException(
            status_code=400,
            detail="date is outside the last 11 trading days",
        )
    selected = as_of or (slider_dates[-1] if slider_dates else None)
    if selected is None:
        return {
            "as_of": None,
            "dates": [],
            "meta_line": "还没有概念热度。先同步概念日 K，再运行概念热度计算。",
            "themes": [],
            "empty_message": "还没有概念热度。",
        }

    window_days = max((t.window_trading_days for t in themes), default=20)
    window_dates = fetch_heat_dates_ending("concept", selected, window_days)
    heat_rows: list[tuple[date, str, object | None]] = []
    if window_dates:
        heat_rows = fetch_concept_heat_window(window_dates[0], window_dates[-1])

    cards = []
    plotly_once = include_plotlyjs
    for theme in themes:
        theme_window = window_dates[-theme.window_trading_days :] if window_dates else []
        view = build_theme_view(
            theme,
            as_of=selected,
            window_dates=theme_window,
            heat_rows=heat_rows,
            slider_dates=slider_dates,
        )
        chart_html = ""
        if not view.get("empty_message"):
            chart_html = _theme_group_chart_only(
                view, include_plotlyjs=plotly_once, height=260
            )
            if chart_html and plotly_once:
                plotly_once = False
        cards.append(
            {
                "theme_id": theme.theme_id,
                "title": theme.title,
                "href": f"/boards/concept/themes/{theme.theme_id}",
                "group_a_label": theme.group_a_label,
                "group_b_label": theme.group_b_label,
                "badge_a": view.get("badge_a"),
                "badge_ab": view.get("badge_ab"),
                "group_chart_html": chart_html,
                "empty_message": view.get("empty_message"),
                "window_start": view.get("window_start"),
                "window_days": view.get("window_days"),
            }
        )

    start = window_dates[0].isoformat() if window_dates else None
    return {
        "as_of": selected.isoformat(),
        "dates": [day.isoformat() for day in slider_dates],
        "meta_line": (
            f"主题域总览 · 截止 {selected.isoformat()}"
            + (f" · 窗口约至 {start}" if start else "")
            + " · 分位 0=最热 · 每图为该主题群A↔群B中位"
        ),
        "themes": cards,
        "empty_message": None,
    }


def _theme_group_chart_only(
    view: dict, *, include_plotlyjs: bool, height: int = 280
) -> str:
    series_a = view.get("series_group_a") or []
    series_b = view.get("series_group_b") or []
    if not series_a:
        return ""
    grouping = view.get("grouping") or {}
    label_a = (grouping.get("group_a") or {}).get("label") or "群A"
    label_b = (grouping.get("group_b") or {}).get("label") or "群B"
    return render_theme_group_chart(
        dates=[point["trade_date"] for point in series_a],
        series_a=[point["value"] for point in series_a],
        series_b=[point["value"] for point in series_b],
        label_a=label_a,
        label_b=label_b,
        include_plotlyjs=include_plotlyjs,
        height=height,
    )


def _theme_page_payload(
    theme_id: str,
    as_of: date | None,
    *,
    include_plotlyjs: bool,
) -> dict:
    data = _theme_payload(theme_id, as_of, include_plotlyjs=include_plotlyjs)
    theme = get_theme(theme_id)
    interpret_template = (
        (theme.interpret_template if theme is not None else "")
        or f"{theme_id}-theme-reading"
    )
    return {
        "title": data["title"],
        "as_of": data["as_of"],
        "dates": data["dates"],
        "theme_api": f"/api/boards/concept/themes/{theme_id}",
        "kline_prefix": "/boards/concept",
        "back_href": "/boards/concept/themes",
        "back_label": "主题域",
        "interpret_template": interpret_template,
        "initial": data,
    }


def _theme_api_payload(
    theme_id: str,
    as_of: date,
    *,
    include_plotlyjs: bool,
) -> dict:
    return _theme_payload(theme_id, as_of, include_plotlyjs=include_plotlyjs)


def _theme_payload(
    theme_id: str,
    as_of: date | None,
    *,
    include_plotlyjs: bool,
) -> dict:
    theme = get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail=f"unknown theme: {theme_id}")

    slider_dates = fetch_rotation_dates(theme.board_type, 10)
    if as_of is not None and as_of not in slider_dates:
        raise HTTPException(
            status_code=400,
            detail="date is outside the last 11 trading days",
        )
    selected = as_of or (slider_dates[-1] if slider_dates else None)
    if selected is None:
        view = build_theme_view(
            theme,
            as_of=date.today(),
            window_dates=[],
            heat_rows=[],
            slider_dates=[],
        )
        view["meta_line"] = "还没有概念热度。先同步概念日 K，再运行概念热度计算。"
        view["group_chart_html"] = ""
        view["member_chart_html"] = ""
        view["mini_kline_html"] = ""
        return view

    window_dates = fetch_heat_dates_ending(
        theme.board_type,
        selected,
        theme.window_trading_days,
    )
    heat_rows: list[tuple[date, str, object | None]] = []
    if window_dates:
        heat_rows = fetch_concept_heat_window(window_dates[0], window_dates[-1])

    view = build_theme_view(
        theme,
        as_of=selected,
        window_dates=window_dates,
        heat_rows=heat_rows,
        slider_dates=slider_dates,
    )
    view["meta_line"] = _theme_meta_line(view)
    view["group_chart_html"], view["member_chart_html"] = _theme_charts(
        view, include_plotlyjs=include_plotlyjs
    )
    view["mini_kline_html"] = _theme_mini_klines(theme, selected)
    return view


def _theme_meta_line(view: dict) -> str:
    if view.get("empty_message"):
        return view["empty_message"]
    start = view.get("window_start")
    as_of = view.get("as_of")
    days = view.get("window_days") or 0
    return (
        f"概念主题域 · 窗口 {start} → {as_of}（{days} 日）"
        " · 分位 0=当日全市场概念中最热 · 热度越小越热"
    )


def _theme_mini_klines(theme: ThemeConfig, as_of: date) -> str:
    kline_dates = fetch_heat_dates_ending(
        theme.board_type, as_of, MINI_KLINE_TRADING_DAYS
    )
    if not kline_dates:
        return ""
    start, end = kline_dates[0], kline_dates[-1]
    codes = theme_board_codes(theme)
    bars_by_code = fetch_board_daily_bars_many(theme.board_type, codes, start, end)
    benchmark = dict(fetch_csi500_closes(start, end))
    sections = [
        (theme.group_a_label, theme.group_a),
        (theme.group_b_label, theme.group_b),
        (theme.satellite_label, theme.satellites),
    ]
    bench_note = (
        " · 灰底为中证500同期走势（已按本图高低对齐）"
        if benchmark
        else " · 中证500背景暂缺"
    )
    parts = [
        '<section class="mini-klines">',
        "<h2>近 60 日 K 线</h2>",
        (
            f'<p class="meta">{start.isoformat()} → {end.isoformat()}'
            f" · 仅蜡烛 · 日期轴按月{bench_note}</p>"
        ),
    ]
    for title, boards in sections:
        parts.append('<div class="mini-row">')
        parts.append(f"<h3>{title}</h3>")
        parts.append('<div class="mini-grid">')
        for board in boards:
            href = f"/boards/{theme.board_type}/{board.board_code}/kline"
            chart = render_mini_kline(
                bars_by_code.get(board.board_code) or [],
                title=board.board_name,
                include_plotlyjs=False,
                benchmark_closes=benchmark or None,
            )
            parts.append(
                '<div class="mini-cell">'
                f'<a class="mini-link" href="{href}">{board.board_name} →</a>'
                f'<div class="mini-chart">{chart}</div>'
                "</div>"
            )
        # Keep a 3-column grid even when a row has fewer than 3 boards.
        for _ in range(3 - len(boards)):
            parts.append('<div class="mini-cell mini-spacer" aria-hidden="true"></div>')
        parts.append("</div></div>")
    parts.append("</section>")
    return "".join(parts)


def _theme_charts(view: dict, *, include_plotlyjs: bool) -> tuple[str, str]:
    series_a = view.get("series_group_a") or []
    series_b = view.get("series_group_b") or []
    if not series_a:
        return "", ""
    dates = [point["trade_date"] for point in series_a]
    values_a = [point["value"] for point in series_a]
    values_b = [point["value"] for point in series_b]
    member_series = view.get("member_series") or {}

    def _member_lines(members: list[dict]) -> list[dict]:
        lines = []
        for member in members:
            series = member_series.get(member["board_code"], {})
            points = series.get("points") or []
            lines.append(
                {
                    "name": member["board_name"],
                    "values": [point.get("percentile") for point in points],
                }
            )
        return lines

    sat_lines = []
    for sat in view.get("satellites") or []:
        series = member_series.get(sat["board_code"], {})
        points = series.get("points") or []
        sat_lines.append(
            {
                "name": sat["board_name"],
                "values": [point.get("percentile") for point in points],
            }
        )

    grouping = view.get("grouping") or {}
    label_a = (grouping.get("group_a") or {}).get("label") or "群A"
    label_b = (grouping.get("group_b") or {}).get("label") or "群B"

    return render_theme_charts(
        dates=dates,
        series_a=values_a,
        series_b=values_b,
        members_a=_member_lines(view.get("members_a") or []),
        members_b=_member_lines(view.get("members_b") or []),
        satellites=sat_lines,
        label_a=label_a,
        label_b=label_b,
        include_plotlyjs=include_plotlyjs,
    )


@app.get("/api/boards/rotation")
def board_rotation_api(
    as_of: str,
    highlight: str | None = None,
    label: list[str] = Query(default_factory=list),
) -> dict:
    return _rotation_api("industry", as_of, highlight, label)


@app.get("/api/boards/concept/rotation")
def concept_rotation_api(
    as_of: str,
    highlight: str | None = None,
    label: list[str] = Query(default_factory=list),
) -> dict:
    return _rotation_api("concept", as_of, highlight, label)


def _board_kline_page(
    request: Request,
    board_type: str,
    board_code: str,
    start_date: str | None,
    end_date: str | None,
) -> HTMLResponse:
    page = _ROTATION_PAGES[board_type]
    board_name = fetch_board_name(board_type, board_code)
    if board_name is None:
        raise HTTPException(status_code=404, detail=page["missing_board"])

    today = date.today()
    start = today
    end = today
    error = None
    try:
        if start_date is None and end_date is None:
            days = fetch_trading_dates_ending(board_type, today, 100)
            if days:
                start = days[0]
        else:
            start = _parse_day(start_date, today)
            end = _parse_day(end_date, today)
            if start > end:
                raise RuntimeError("开始日期不能晚于结束日期")
    except ValueError:
        error = "日期格式应为 YYYY-MM-DD"
    except RuntimeError as exc:
        error = str(exc)

    chart_html = None
    summary = None
    title = f"{board_name} {board_code}"
    if error is None:
        records = fetch_board_daily_bars_from_db(board_type, board_code, start, end)
        if records:
            heats = fetch_board_heat_series(board_type, board_code, start, end)
            chart_html = render_kline(records, title=title, code=board_code, heats=heats)
            summary = f"{title} · {len(records)} 根K线 · {start} ~ {end}"
        else:
            summary = f"{title} · 所选区间无数据"

    return templates.TemplateResponse(
        request,
        "board_kline.html",
        {
            "board_code": board_code,
            "board_name": board_name,
            "kind_label": page["kind_label"],
            "back_href": page["rotation_path"],
            "form_action": f"{page['kline_prefix']}/{board_code}/kline",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "chart_html": chart_html,
            "summary": summary,
            "error": error,
        },
    )


@app.get("/boards/industry/{board_code}/kline", response_class=HTMLResponse)
def board_kline_page(
    request: Request,
    board_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> HTMLResponse:
    return _board_kline_page(request, "industry", board_code, start_date, end_date)


@app.get("/boards/concept/{board_code}/kline", response_class=HTMLResponse)
def concept_kline_page(
    request: Request,
    board_code: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> HTMLResponse:
    return _board_kline_page(request, "concept", board_code, start_date, end_date)


@app.get("/charts/kline-demo", response_class=HTMLResponse)
def kline_demo_page(
    request: Request,
    source: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> HTMLResponse:
    today = date.today()
    default_end = today - timedelta(days=1)
    default_start = default_end - timedelta(days=60)
    start = _parse_day(start_date, default_start)
    end = _parse_day(end_date, default_end)
    selected_source = source or "online_index"
    submitted = source is not None

    chart_html = None
    summary = None
    error = None

    if submitted:
        try:
            if start > end:
                raise RuntimeError("开始日期不能晚于结束日期")

            heats = None
            if selected_source == "online_index":
                records = _load_online_index(start, end)
                title = "上证指数 sh.000001（在线）"
                code = "sh.000001"
            elif selected_source == "local_stock":
                records = fetch_daily_bars_from_db("sh.600000", start, end)
                title = "浦发银行 sh.600000（本地库）"
                code = "sh.600000"
            elif selected_source == "local_board_industry":
                records = fetch_board_daily_bars_from_db(
                    "industry", "881121", start, end
                )
                heats = fetch_board_heat_series("industry", "881121", start, end)
                title = "半导体 881121（本地行业）"
                code = "881121"
            elif selected_source == "local_board_concept":
                records = fetch_board_daily_bars_from_db(
                    "concept", "300084", start, end
                )
                heats = fetch_board_heat_series("concept", "300084", start, end)
                title = "煤化工概念 300084（本地概念）"
                code = "300084"
            else:
                raise RuntimeError(f"未知数据来源: {selected_source}")

            if records:
                chart_html = render_kline(
                    records, title=title, code=code, heats=heats
                )
                summary = f"{title} · {len(records)} 根K线 · {start} ~ {end}"
            else:
                summary = f"{title} · 所选区间无数据"
        except Exception as exc:  # noqa: BLE001 - page boundary
            error = str(exc)

    return templates.TemplateResponse(
        request,
        "kline_demo.html",
        {
            "source": selected_source,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "submitted": submitted,
            "chart_html": chart_html,
            "summary": summary,
            "error": error,
        },
    )
