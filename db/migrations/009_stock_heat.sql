CREATE TABLE IF NOT EXISTS stock_heat_daily (
    trade_date date NOT NULL,
    code varchar(16) NOT NULL,
    pct_chg numeric,
    rank_no integer,
    universe_n integer,
    heat_short numeric,
    heat_long numeric,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, code)
);

CREATE INDEX IF NOT EXISTS idx_stock_heat_daily_code_date
    ON stock_heat_daily (code, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_stock_heat_daily_date
    ON stock_heat_daily (trade_date DESC);
