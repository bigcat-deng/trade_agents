# Database migrations

SQL migrations for the `analytics` PostgreSQL database.

## Prerequisites

- PostgreSQL is running
- Database `analytics` exists
- Local user can connect without a password, or `DATABASE_URL` is set

Default connection:

```text
postgresql://deng@localhost:5432/analytics
```

## Apply

From the project root:

```bash
bash db/apply.sh
```

Custom connection:

```bash
DATABASE_URL=postgresql://deng@localhost:5432/analytics bash db/apply.sh
```

The script records applied files in `schema_migrations` and skips them on later runs.

## Layout

```text
db/
  apply.sh
  migrations/
    001_stock_universe_daily.sql
```
