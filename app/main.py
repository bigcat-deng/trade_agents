from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import fetch_latest_trading_stocks

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
