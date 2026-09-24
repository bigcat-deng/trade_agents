CREATE TABLE IF NOT EXISTS stock_daily_bar (
    trade_date date NOT NULL,
    code varchar(16) NOT NULL,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    preclose numeric,
    volume bigint,
    amount numeric,
    adjustflag smallint NOT NULL DEFAULT 3,
    turn numeric,
    tradestatus smallint,
    pct_chg numeric,
    is_st smallint,
    source varchar(32) NOT NULL DEFAULT 'baostock',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, code)
);

CREATE INDEX IF NOT EXISTS idx_stock_daily_bar_code_date
    ON stock_daily_bar (code, trade_date DESC);

CREATE TABLE IF NOT EXISTS stock_daily_bar_sync_state (
    code varchar(16) PRIMARY KEY,
    window_start date,
    window_end date,
    last_status varchar(32) NOT NULL,
    last_source varchar(32),
    last_rows integer,
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
