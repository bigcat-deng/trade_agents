CREATE TABLE IF NOT EXISTS board_heat_daily (
    trade_date date NOT NULL,
    board_type varchar(16) NOT NULL,
    board_code varchar(16) NOT NULL,
    pct_chg numeric NOT NULL,
    rank_no integer NOT NULL,
    universe_n integer NOT NULL,
    heat_short numeric,
    heat_long numeric,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, board_type, board_code),
    CONSTRAINT board_heat_daily_type_check
        CHECK (board_type IN ('industry', 'concept'))
);

CREATE INDEX IF NOT EXISTS idx_board_heat_daily_code_date
    ON board_heat_daily (board_type, board_code, trade_date DESC);
