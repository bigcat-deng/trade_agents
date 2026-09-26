from datetime import date, datetime, timedelta
from pathlib import Path

import baostock as bs
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.charts.board_rotation import render_board_rotation
from app.charts.kline import render_kline
from app.db import (
    fetch_board_daily_bars_from_db,
    fetch_board_heat_series,
    fetch_board_name,
    fetch_board_rotation,
    fetch_daily_bars_from_db,
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
from app.market_data.providers import baostock_kline
from app.sync_runner import JOB_IDS, get_runner_state, start_job
from app.sync_status import fetch_sync_dashboard_status

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


@app.post("/api/interpret/{template_name}")
def interpret_api(template_name: str, body: InterpretRequest | None = None) -> dict:
    try:
        requested = _parse_optional_day(body.as_of if body else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        result = interpret(template_name, requested)
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
