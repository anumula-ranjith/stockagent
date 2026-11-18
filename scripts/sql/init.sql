-- Postgres + TimescaleDB initial schema.
-- Mirrors the DuckDB schema in src/stock_agents/storage/schema.py, but
-- makes prices_daily a hypertable chunked by month.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ================================================================ Reference
CREATE TABLE IF NOT EXISTS symbology (
    ticker       VARCHAR  PRIMARY KEY,
    eodhd_symbol VARCHAR,
    factset_id   VARCHAR,
    isin         VARCHAR,
    cusip        VARCHAR,
    active       BOOLEAN  NOT NULL DEFAULT TRUE,
    updated_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS classification (
    ticker         VARCHAR  NOT NULL REFERENCES symbology(ticker),
    effective_date DATE     NOT NULL,
    known_date     DATE     NOT NULL,
    sector         VARCHAR,
    industry       VARCHAR,
    source         VARCHAR,
    PRIMARY KEY (ticker, effective_date, source)
);

-- ================================================================ Market data
CREATE TABLE IF NOT EXISTS prices_daily (
    ticker     VARCHAR  NOT NULL,
    date       DATE     NOT NULL,
    open       DOUBLE PRECISION,
    high       DOUBLE PRECISION,
    low        DOUBLE PRECISION,
    close      DOUBLE PRECISION,
    adj_close  DOUBLE PRECISION,
    volume     BIGINT,
    source     VARCHAR,
    known_date DATE     NOT NULL,
    PRIMARY KEY (ticker, date, source)
);

-- Timescale hypertable: month-chunked, keyed on `date`.
SELECT create_hypertable('prices_daily', 'date',
                         chunk_time_interval => INTERVAL '1 month',
                         if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_prices_ticker_date
    ON prices_daily(ticker, date DESC);

CREATE TABLE IF NOT EXISTS corporate_actions (
    ticker      VARCHAR NOT NULL REFERENCES symbology(ticker),
    action_type VARCHAR NOT NULL,
    ex_date     DATE    NOT NULL,
    value       DOUBLE PRECISION,
    source      VARCHAR,
    known_date  DATE    NOT NULL,
    PRIMARY KEY (ticker, action_type, ex_date, source)
);

-- ================================================================ Fundamentals
CREATE TABLE IF NOT EXISTS fundamentals_pit (
    ticker         VARCHAR NOT NULL REFERENCES symbology(ticker),
    metric         VARCHAR NOT NULL,
    fiscal_period  VARCHAR NOT NULL,
    value          DOUBLE PRECISION,
    effective_date DATE    NOT NULL,
    known_date     DATE    NOT NULL,
    source         VARCHAR NOT NULL,
    PRIMARY KEY (ticker, metric, fiscal_period, source)
);
CREATE INDEX IF NOT EXISTS idx_fund_known ON fundamentals_pit(ticker, known_date);

CREATE TABLE IF NOT EXISTS estimates_pit (
    ticker         VARCHAR NOT NULL REFERENCES symbology(ticker),
    metric         VARCHAR NOT NULL,
    value          DOUBLE PRECISION,
    n_analysts     INTEGER,
    effective_date DATE NOT NULL,
    known_date     DATE NOT NULL,
    source         VARCHAR NOT NULL,
    PRIMARY KEY (ticker, metric, effective_date, source)
);

-- ================================================================ News & sentiment
CREATE TABLE IF NOT EXISTS news (
    news_id      VARCHAR PRIMARY KEY,
    ticker       VARCHAR NOT NULL REFERENCES symbology(ticker),
    published_at TIMESTAMPTZ NOT NULL,
    source       VARCHAR,
    headline     TEXT,
    url          TEXT,
    polarity     DOUBLE PRECISION,
    pos          DOUBLE PRECISION,
    neg          DOUBLE PRECISION,
    neu          DOUBLE PRECISION,
    known_date   DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_tk_dt ON news(ticker, published_at DESC);

CREATE TABLE IF NOT EXISTS sentiment_daily (
    ticker         VARCHAR NOT NULL REFERENCES symbology(ticker),
    effective_date DATE    NOT NULL,
    polarity       DOUBLE PRECISION,
    n_headlines    INTEGER,
    source         VARCHAR NOT NULL,
    known_date     DATE    NOT NULL,
    PRIMARY KEY (ticker, effective_date, source)
);

-- ================================================================ Scores & signals
CREATE TABLE IF NOT EXISTS agent_scores (
    date    DATE    NOT NULL,
    ticker  VARCHAR NOT NULL REFERENCES symbology(ticker),
    agent   VARCHAR NOT NULL,
    score   DOUBLE PRECISION,
    passes  BOOLEAN,
    PRIMARY KEY (date, ticker, agent)
);
CREATE INDEX IF NOT EXISTS idx_scores_date ON agent_scores(date DESC);

CREATE TABLE IF NOT EXISTS signals (
    date       DATE    NOT NULL,
    ticker     VARCHAR NOT NULL REFERENCES symbology(ticker),
    side       VARCHAR NOT NULL,
    composite  DOUBLE PRECISION,
    tech       DOUBLE PRECISION,
    sent       DOUBLE PRECISION,
    mom        DOUBLE PRECISION,
    fund       DOUBLE PRECISION,
    rank       INTEGER,
    reasons    TEXT,
    PRIMARY KEY (date, ticker, side)
);

-- ================================================================ Users & auth
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR UNIQUE NOT NULL,
    hashed_pwd    VARCHAR NOT NULL,
    is_admin      BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_runs (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type   VARCHAR NOT NULL,
    status     VARCHAR NOT NULL,
    enqueued_at TIMESTAMPTZ DEFAULT NOW(),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error      TEXT,
    result_key VARCHAR,   -- S3 key when the job produced an artifact
    user_id    UUID REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_job_runs_enqueued ON job_runs(enqueued_at DESC);
