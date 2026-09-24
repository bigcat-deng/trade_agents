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

## Layout

```text
db/
  apply.sh
  migrations/
    001_stock_universe_daily.sql
```
