CREATE TABLE IF NOT EXISTS board_universe_daily (
    trade_date date NOT NULL,
    board_type varchar(16) NOT NULL,
    board_code varchar(16) NOT NULL,
    board_name varchar(64) NOT NULL,
    source varchar(32) NOT NULL DEFAULT 'akshare_em',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, board_type, board_code),
    CONSTRAINT board_universe_daily_type_check
        CHECK (board_type IN ('industry', 'concept'))
);

CREATE INDEX IF NOT EXISTS idx_board_universe_daily_type_date
    ON board_universe_daily (board_type, trade_date DESC);

CREATE TABLE IF NOT EXISTS board_daily_bar (
    trade_date date NOT NULL,
    board_type varchar(16) NOT NULL,
    board_code varchar(16) NOT NULL,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume bigint,
    amount numeric,
    pct_chg numeric,
    turn numeric,
    amplitude numeric,
    adjustflag smallint NOT NULL DEFAULT 3,
    source varchar(32) NOT NULL DEFAULT 'akshare_em',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, board_type, board_code),
    CONSTRAINT board_daily_bar_type_check
        CHECK (board_type IN ('industry', 'concept'))
);

CREATE INDEX IF NOT EXISTS idx_board_daily_bar_code_date
    ON board_daily_bar (board_type, board_code, trade_date DESC);

CREATE TABLE IF NOT EXISTS board_daily_bar_sync_state (
    board_type varchar(16) NOT NULL,
    board_code varchar(16) NOT NULL,
    window_start date,
    window_end date,
    last_status varchar(32) NOT NULL,
    last_source varchar(32),
    last_rows integer,
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (board_type, board_code),
    CONSTRAINT board_daily_bar_sync_state_type_check
        CHECK (board_type IN ('industry', 'concept'))
);
