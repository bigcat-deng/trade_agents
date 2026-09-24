# trade_agents

Python web service served by uvicorn.

## Requirements

Python 3.11 or newer.

## Install

From the project root:

```bash
bash scripts/install.sh
```

The script creates `.venv` and installs the packages in `requirements.txt`. `.venv` stays on the machine and is not committed.

## Run

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check that the service is up:

```bash
curl http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok"}`.

## Database

PostgreSQL database `analytics` must already exist. Apply schema migrations with:

```bash
bash db/apply.sh
```

Details are in `db/README.md`.

## Sync stock universe

Download one day of `baostock.query_all_stock` into `stock_universe_daily`:

```bash
.venv/bin/python -m app.jobs.sync_stock_universe
.venv/bin/python -m app.jobs.sync_stock_universe --day 2024-12-20
```

Schedule with system cron if needed. The job does not include a built-in scheduler.

Find the latest day baostock still has universe data for:

```bash
.venv/bin/python scripts/find_latest_stock_universe_day.py
```

## Stocks page

After the database has synced data, open:

```text
http://127.0.0.1:8000/stocks
```

It shows the latest sync date and the first 30 trading A-share stocks by code.

## Sync daily bars

Unadjusted daily K-lines for all latest trading A-shares.
Source order: baostock → Eastmoney → Tencent. Stored format follows baostock.

```bash
# First full-ish backfill: last 200 trading days
.venv/bin/python -m app.jobs.sync_stock_daily_bars --trading-days 200

# Daily update: last 5 trading days
.venv/bin/python -m app.jobs.sync_stock_daily_bars --trading-days 5

# Explicit range
.venv/bin/python -m app.jobs.sync_stock_daily_bars --start-date 2026-09-01 --end-date 2026-09-23

# Trial / resume
.venv/bin/python -m app.jobs.sync_stock_daily_bars --limit 5 --trading-days 5
.venv/bin/python -m app.jobs.sync_stock_daily_bars --resume --trading-days 200
```

## Move to another server

1. Clone the repository.
2. Install Python 3.11 or newer.
3. Install PostgreSQL and create the `analytics` database.
4. Run `bash scripts/install.sh`.
5. Run `bash db/apply.sh`.
6. Start uvicorn with the command above.
7. Open `/health` and confirm the response.
