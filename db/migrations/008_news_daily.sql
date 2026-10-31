CREATE TABLE IF NOT EXISTS news_flash (
    source varchar(16) NOT NULL,
    published_at timestamptz NOT NULL,
    title text NOT NULL,
    content text NOT NULL DEFAULT '',
    url text,
    level varchar(8),
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, published_at, title),
    CONSTRAINT news_flash_source_check
        CHECK (source IN ('cls', 'ths'))
);

CREATE INDEX IF NOT EXISTS idx_news_flash_published
    ON news_flash (published_at DESC);

CREATE TABLE IF NOT EXISTS news_cctv_item (
    broadcast_date date NOT NULL,
    title text NOT NULL,
    content text NOT NULL DEFAULT '',
    source varchar(32) NOT NULL DEFAULT 'cctv',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (broadcast_date, title)
);

CREATE INDEX IF NOT EXISTS idx_news_cctv_item_date
    ON news_cctv_item (broadcast_date DESC);

CREATE TABLE IF NOT EXISTS stock_comment_daily (
    trade_date date NOT NULL,
    code varchar(16) NOT NULL,
    name varchar(64) NOT NULL,
    close numeric,
    pct_chg numeric,
    turnover numeric,
    pe numeric,
    main_cost numeric,
    inst_participation numeric,
    score numeric,
    rank_change integer,
    rank_no integer,
    focus numeric,
    source varchar(32) NOT NULL DEFAULT 'eastmoney',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, code)
);

CREATE INDEX IF NOT EXISTS idx_stock_comment_daily_code
    ON stock_comment_daily (code, trade_date DESC);

CREATE TABLE IF NOT EXISTS stock_hot_rank_daily (
    trade_date date NOT NULL,
    list_name varchar(16) NOT NULL,
    code varchar(16) NOT NULL,
    name varchar(64) NOT NULL,
    rank_no integer,
    rank_change integer,
    close numeric,
    change_amt numeric,
    pct_chg numeric,
    source varchar(32) NOT NULL DEFAULT 'eastmoney',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, list_name, code),
    CONSTRAINT stock_hot_rank_daily_list_check
        CHECK (list_name IN ('rank', 'surge'))
);

CREATE INDEX IF NOT EXISTS idx_stock_hot_rank_daily_code
    ON stock_hot_rank_daily (code, trade_date DESC);

CREATE TABLE IF NOT EXISTS stock_weibo_daily (
    trade_date date NOT NULL,
    time_period varchar(16) NOT NULL,
    name varchar(64) NOT NULL,
    code varchar(16),
    rate numeric,
    source varchar(32) NOT NULL DEFAULT 'jin10',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, time_period, name)
);

CREATE INDEX IF NOT EXISTS idx_stock_weibo_daily_code
    ON stock_weibo_daily (code, trade_date DESC);

CREATE TABLE IF NOT EXISTS stock_notice_daily (
    notice_id varchar(64) NOT NULL,
    notice_date date NOT NULL,
    code varchar(16) NOT NULL,
    name varchar(64) NOT NULL,
    notice_type varchar(64) NOT NULL,
    title text NOT NULL,
    url text,
    source varchar(32) NOT NULL DEFAULT 'eastmoney',
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (notice_id)
);

CREATE INDEX IF NOT EXISTS idx_stock_notice_daily_date
    ON stock_notice_daily (notice_date DESC);

CREATE INDEX IF NOT EXISTS idx_stock_notice_daily_code
    ON stock_notice_daily (code, notice_date DESC);

CREATE TABLE IF NOT EXISTS news_sync_state (
    feed varchar(32) PRIMARY KEY,
    snapshot_date date,
    cursor_at timestamptz,
    last_status varchar(32) NOT NULL,
    last_rows integer,
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT news_sync_state_feed_check
        CHECK (feed IN (
            'cls',
            'ths',
            'cctv',
            'stock_comment',
            'em_rank',
            'em_surge',
            'weibo',
            'stock_notice'
        ))
);

INSERT INTO news_sync_state (feed, last_status)
VALUES
    ('cls', 'pending'),
    ('ths', 'pending'),
    ('cctv', 'pending'),
    ('stock_comment', 'pending'),
    ('em_rank', 'pending'),
    ('em_surge', 'pending'),
    ('weibo', 'pending'),
    ('stock_notice', 'pending')
ON CONFLICT (feed) DO NOTHING;
