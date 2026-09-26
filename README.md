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

Open the tool index and sync dashboard:

```text
http://127.0.0.1:8000/          # 总索引
http://127.0.0.1:8000/sync      # 同步看板
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

## Sync board universe

Tonghuashun industry/concept board list into `board_universe_daily` (daily snapshot).
Board codes are THS ids: industry `881xxx`, concept `30xxxx`.

Downloads retry with backoff and cache name maps under `.cache/board/`.
The job retries the full sync (`--retries`, default 3) and refuses to replace a
healthy THS snapshot with a clearly worse download (`--min-industry` / `--min-concept`).

```bash
.venv/bin/python -m app.jobs.sync_board_universe
.venv/bin/python -m app.jobs.sync_board_universe --retries 5
.venv/bin/python -m app.jobs.sync_board_universe --day 2026-09-24
.venv/bin/python -m app.jobs.sync_board_universe --board-type industry
```

Switching from Eastmoney: truncate old BK-coded board tables first, then re-sync:

```bash
psql "$DATABASE_URL" -c "TRUNCATE board_universe_daily, board_daily_bar, board_daily_bar_sync_state, board_constituent_daily, board_constituent_sync_state;"
```

## Sync board daily bars

Tonghuashun board daily K-lines into `board_daily_bar` (THS board codes).
Sync board universe first. Per board probe order:

1. **Tonghuashun** (`akshare_ths`) — by THS `board_code`
2. **local_synth** — equal-weight index from THS constituents + `stock_daily_bar`

No Eastmoney fallback (taxonomies differ). Configurable `--retries` / `--resume`.

```bash
# First full-ish backfill: last 200 trading days
.venv/bin/python -m app.jobs.sync_board_daily_bars --trading-days 200

# Daily update: last 5 trading days
.venv/bin/python -m app.jobs.sync_board_daily_bars --trading-days 5

# Explicit range / trial / resume / retries
.venv/bin/python -m app.jobs.sync_board_daily_bars --start-date 2026-09-01 --end-date 2026-09-23
.venv/bin/python -m app.jobs.sync_board_daily_bars --limit 5 --trading-days 30
.venv/bin/python -m app.jobs.sync_board_daily_bars --resume --retries 5 --trading-days 200
.venv/bin/python -m app.jobs.sync_board_daily_bars --board-type concept --board-code 300084 --trading-days 30 --verbose-probe
```

## Sync board constituents

Tonghuashun board/concept ↔ stock membership into `board_constituent_daily` (daily snapshot).
Stock codes are normalized to baostock format (`sh.600000`). Sync board universe first.

```bash
# Full snapshot for latest board_universe_daily date
.venv/bin/python -m app.jobs.sync_board_constituents

# Resume / retries / trial
.venv/bin/python -m app.jobs.sync_board_constituents --resume --retries 5
.venv/bin/python -m app.jobs.sync_board_constituents --limit 5 --verbose-probe
.venv/bin/python -m app.jobs.sync_board_constituents --board-type industry --board-code 881151
.venv/bin/python -m app.jobs.sync_board_constituents --day 2026-09-25
```

Periodic update: re-run on a schedule; use `--resume` if a previous run was interrupted.

## Industry board heat

Rank industry boards (`board_type = industry`) by the 5-day mean of a new return and store the result in `board_heat_daily`. The new return is the percent change of the 2-day mean of `(high + low + close) / 3`. The highest smoothed return is rank 1. Short heat is the 5-day mean of that board's ranks; long heat is the 20-day mean. Re-running aligns the heat table to the latest industry bars.

```bash
.venv/bin/python -m app.jobs.compute_board_heat
```

## K-line demo

Generic chart helper plus a test page:

```text
http://127.0.0.1:8000/charts/kline-demo
```

Sources: online Shanghai Composite (`sh.000001`) or local DB (`sh.600000`).

## Move to another server

Keep **one primary database** on a machine that stays on and runs cron (e.g. UTM). Use a laptop DB only for local development—do not sync both every day.

### 0. Before you start

1. Push (or otherwise copy) the code you want to run so the new host has one canonical tree.
2. Choose data strategy:
   - Keep history → `pg_dump` from the old primary, restore on the new host.
   - Rebuild from market sources → empty `analytics` + run the sync jobs below.

Default DB URL is Unix-socket peer auth: `postgresql:///analytics`. Override with `DATABASE_URL` when needed.

### 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git postgresql postgresql-client
```

Python must be 3.11 or newer.

### 2. Code and Python env

```bash
git clone https://github.com/bigcat-deng/trade_agents.git
cd trade_agents
bash scripts/install.sh
mkdir -p logs
```

### 3. Database and schema

```bash
sudo -u postgres createuser -s "$USER"   # if peer-auth role missing
sudo -u postgres createdb analytics      # if database missing
bash db/apply.sh
```

Optional: migrate existing data instead of (or before) a full re-sync:

```bash
# on old host
pg_dump -Fc postgresql:///analytics -f analytics.dump

# on new host (empty or replace carefully)
pg_restore -d postgresql:///analytics --clean --if-exists analytics.dump
bash db/apply.sh   # applies any migrations not in the dump; skips already recorded ones
```

### 4. First data load (empty database)

Order matters (boards depend on universe / constituents / stock bars for local synth):

```bash
.venv/bin/python -m app.jobs.sync_stock_universe
.venv/bin/python -m app.jobs.sync_stock_daily_bars --trading-days 200

.venv/bin/python -m app.jobs.sync_board_universe
.venv/bin/python -m app.jobs.sync_board_constituents
.venv/bin/python -m app.jobs.sync_board_daily_bars --trading-days 200
.venv/bin/python -m app.jobs.compute_board_heat
```

Use `--limit 5` for a trial, `--resume` if a run was interrupted.

### 5. Cron (weekday example)

Edit with `crontab -e`. Adjust the project path and times to your timezone:

```cron
30 16 * * 1-5 cd /home/YOU/trade_agents && .venv/bin/python -m app.jobs.sync_stock_universe --day "$(date -d yesterday +\%F)" >> logs/sync_stock_universe.log 2>&1
0 17 * * 1-5 cd /home/YOU/trade_agents && .venv/bin/python -m app.jobs.sync_stock_daily_bars --trading-days 5 >> logs/sync_stock_daily_bars.log 2>&1
10 17 * * 1-5 cd /home/YOU/trade_agents && .venv/bin/python -m app.jobs.sync_board_universe >> logs/sync_board_universe.log 2>&1
20 17 * * 1-5 cd /home/YOU/trade_agents && .venv/bin/python -m app.jobs.sync_board_constituents >> logs/sync_board_constituents.log 2>&1
30 17 * * 1-5 cd /home/YOU/trade_agents && .venv/bin/python -m app.jobs.sync_board_daily_bars --trading-days 5 >> logs/sync_board_daily_bars.log 2>&1
45 17 * * 1-5 cd /home/YOU/trade_agents && .venv/bin/python -m app.jobs.compute_board_heat >> logs/compute_board_heat.log 2>&1
```

### 6. Start the web service

```bash
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > logs/uvicorn.log 2>&1 &
curl http://127.0.0.1:8000/health
```

Optional: manage uvicorn with systemd for restart-on-boot.

### 7. Checklist

| Check | Expect |
|-------|--------|
| `curl http://127.0.0.1:8000/health` | `{"status":"ok"}` |
| `/`, `/sync`, `/stocks`, `/charts/kline-demo` | pages load |
| `psql postgresql:///analytics -c '\dt'` | stock/board tables + `schema_migrations` |
| `crontab -l` and `logs/*.log` | jobs scheduled; next run writes logs |
| Browser from another machine | `http://NEW_HOST_IP:8000/` |
