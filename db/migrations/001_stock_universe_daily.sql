CREATE TABLE IF NOT EXISTS stock_universe_daily (
    trade_date date NOT NULL,
    code varchar(16) NOT NULL,
    code_name varchar(64) NOT NULL,
    trade_status smallint NOT NULL,
    source varchar(32) NOT NULL DEFAULT 'baostock',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, code)
);

CREATE INDEX IF NOT EXISTS idx_stock_universe_daily_code_date
    ON stock_universe_daily (code, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_stock_universe_daily_trade_date
    ON stock_universe_daily (trade_date);
