CREATE TABLE IF NOT EXISTS board_constituent_daily (
    trade_date date NOT NULL,
    board_type varchar(16) NOT NULL,
    board_code varchar(16) NOT NULL,
    stock_code varchar(16) NOT NULL,
    stock_name varchar(64) NOT NULL,
    source varchar(32) NOT NULL DEFAULT 'akshare_em',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, board_type, board_code, stock_code),
    CONSTRAINT board_constituent_daily_type_check
        CHECK (board_type IN ('industry', 'concept'))
);

CREATE INDEX IF NOT EXISTS idx_board_constituent_daily_stock
    ON board_constituent_daily (stock_code, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_board_constituent_daily_board
    ON board_constituent_daily (board_type, board_code, trade_date DESC);

CREATE TABLE IF NOT EXISTS board_constituent_sync_state (
    board_type varchar(16) NOT NULL,
    board_code varchar(16) NOT NULL,
    snapshot_date date,
    last_status varchar(32) NOT NULL,
    last_source varchar(32),
    last_rows integer,
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (board_type, board_code),
    CONSTRAINT board_constituent_sync_state_type_check
        CHECK (board_type IN ('industry', 'concept'))
);
