# Database migrations

SQL migrations for the `analytics` PostgreSQL database.

## Prerequisites

- PostgreSQL is running
- Database `analytics` exists
- Local user can connect without a password, or `DATABASE_URL` is set

Default connection (Unix socket, current OS user, peer auth):

```text
postgresql:///analytics
```

This avoids password prompts on Ubuntu. To use TCP instead:

```bash
DATABASE_URL=postgresql://deng@127.0.0.1:5432/analytics bash db/apply.sh
```

## Apply

From the project root:

```bash
bash db/apply.sh
```

Custom connection:

```bash
DATABASE_URL=postgresql:///analytics bash db/apply.sh
```

The script records applied files in `schema_migrations` and skips them on later runs.

## Tables

- `stock_universe_daily`: daily security universe from baostock
- `stock_daily_bar`: unadjusted daily OHLCV bars (baostock format; multi-source ingest)
- `stock_daily_bar_sync_state`: per-code sync status for resume
- `board_universe_daily`: Tonghuashun industry/concept board list snapshots (codes `881xxx` / `30xxxx`)
- `board_daily_bar`: board daily OHLCV bars (THS / local synth)
- `board_daily_bar_sync_state`: per-board sync status for resume
- `board_constituent_daily`: board/concept ↔ stock membership snapshots (THS boards; baostock stock codes)
- `board_constituent_sync_state`: per-board constituent sync status for resume
- `board_heat_daily`: industry/concept heat (rank of daily return, MA5 / MA20 of rank)
- `news_flash`: CLS / Tonghuashun flashes (`source` `cls` or `ths`); deduped by source, publish time, and title
- `news_cctv_item`: Xinwen Lianbo items by broadcast date
- `stock_comment_daily`: Eastmoney per-stock score snapshot (baostock codes). `trade_date` is the API session date
- `stock_hot_rank_daily`: Eastmoney popularity (`list_name` `rank`) and surge (`surge`) snapshots
- `stock_weibo_daily`: Jin10 Weibo attention snapshot. `code` stays null until the name resolves
- `stock_notice_daily`: Eastmoney announcements, keyed by `notice_id`
- `news_sync_state`: one row per news feed (`cls`, `ths`, `cctv`, `stock_comment`, `em_rank`, `em_surge`, `weibo`, `stock_notice`)

## Layout

```text
db/
  apply.sh
  migrations/
    001_stock_universe_daily.sql
```
