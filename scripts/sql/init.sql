-- PostgreSQL baseline schema. Apply timescale.sql next.

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

CREATE INDEX IF NOT EXISTS idx_prices_ticker_date
    ON prices_daily(ticker, date DESC);
CREATE INDEX IF NOT EXISTS prices_daily_date_idx ON prices_daily(date DESC);

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

-- Other warehouse tables migrated from DuckDB.
CREATE TABLE IF NOT EXISTS index_membership (
        index_code   VARCHAR  NOT NULL,
        ticker       VARCHAR  NOT NULL,
        joined_on    DATE     NOT NULL,
        left_on      DATE,
        known_on     DATE     NOT NULL,
        PRIMARY KEY (index_code, ticker, joined_on)
    );

CREATE TABLE IF NOT EXISTS analyst_pit (
        ticker         VARCHAR NOT NULL,
        rating_mean    DOUBLE PRECISION,
        target_mean    DOUBLE PRECISION,
        n_analysts     INTEGER,
        effective_date DATE NOT NULL,
        known_date     DATE NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, effective_date, source)
    );

CREATE TABLE IF NOT EXISTS earnings_surprise (
        ticker         VARCHAR NOT NULL,
        fiscal_period  VARCHAR NOT NULL,
        eps_reported   DOUBLE PRECISION,
        eps_estimate   DOUBLE PRECISION,
        surprise_pct   DOUBLE PRECISION,
        report_date    DATE NOT NULL,
        known_date     DATE NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, fiscal_period, source)
    );

CREATE TABLE IF NOT EXISTS events_calendar (
        ticker       VARCHAR NOT NULL,
        event_type   VARCHAR NOT NULL,   -- 'earnings' | 'conference' | ...
        event_date   DATE    NOT NULL,
        time_of_day  VARCHAR,            -- 'BMO' | 'AMC' | NULL
        fiscal_period VARCHAR,
        known_date   DATE    NOT NULL,
        source       VARCHAR NOT NULL,
        PRIMARY KEY (ticker, event_type, event_date, source)
    );

CREATE TABLE IF NOT EXISTS insider_tx (
        tx_id        VARCHAR PRIMARY KEY,
        ticker       VARCHAR NOT NULL,
        tx_date      DATE    NOT NULL,
        tx_type      VARCHAR,           -- 'P'/'S' etc.
        shares       DOUBLE PRECISION,
        price        DOUBLE PRECISION,
        value_usd    DOUBLE PRECISION,
        insider_role VARCHAR,
        known_date   DATE    NOT NULL,
        source       VARCHAR NOT NULL
    );

CREATE TABLE IF NOT EXISTS inst_ownership (
        ticker         VARCHAR NOT NULL,
        effective_date DATE    NOT NULL,   -- 13F period end
        inst_holders   INTEGER,
        inst_pct_owned DOUBLE PRECISION,
        known_date     DATE    NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, effective_date, source)
    );

CREATE TABLE IF NOT EXISTS short_interest (
        ticker         VARCHAR NOT NULL,
        settlement_date DATE   NOT NULL,
        short_shares   BIGINT,
        short_pct_float DOUBLE PRECISION,
        days_to_cover  DOUBLE PRECISION,
        known_date     DATE NOT NULL,    -- FINRA publication date
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, settlement_date, source)
    );

CREATE TABLE IF NOT EXISTS social_daily (
        ticker         VARCHAR NOT NULL,
        effective_date DATE    NOT NULL,
        mentions       INTEGER,
        avg_sentiment  DOUBLE PRECISION,
        known_date     DATE    NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, effective_date, source)
    );

CREATE TABLE IF NOT EXISTS macro (
        series_id      VARCHAR NOT NULL,   -- 'DGS3MO' | 'VIXCLS' | ...
        effective_date DATE    NOT NULL,
        value          DOUBLE PRECISION,
        known_date     DATE    NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (series_id, effective_date, source)
    );

CREATE TABLE IF NOT EXISTS factor_values (
        date     DATE    NOT NULL,
        ticker   VARCHAR NOT NULL,
        agent    VARCHAR NOT NULL,   -- 'technical' | 'momentum' | ...
        factor   VARCHAR NOT NULL,
        raw      DOUBLE PRECISION,
        score    DOUBLE PRECISION,
        imputed  BOOLEAN,
        PRIMARY KEY (date, ticker, agent, factor)
    );

CREATE TABLE IF NOT EXISTS target_weights (
        date   DATE    NOT NULL,
        ticker VARCHAR NOT NULL,
        weight DOUBLE PRECISION  NOT NULL,
        PRIMARY KEY (date, ticker)
    );

CREATE TABLE IF NOT EXISTS orders (
        order_id   VARCHAR PRIMARY KEY,
        date       DATE    NOT NULL,
        ticker     VARCHAR NOT NULL,
        side       VARCHAR NOT NULL,       -- 'buy' | 'sell' | 'short' | 'cover'
        qty        DOUBLE PRECISION  NOT NULL,
        type       VARCHAR,
        status     VARCHAR,
        submitted_at TIMESTAMP,
        broker     VARCHAR
    );

CREATE TABLE IF NOT EXISTS fills (
        fill_id   VARCHAR PRIMARY KEY,
        order_id  VARCHAR NOT NULL,
        ticker    VARCHAR NOT NULL,
        side      VARCHAR NOT NULL,
        qty       DOUBLE PRECISION  NOT NULL,
        price     DOUBLE PRECISION,
        filled_at TIMESTAMP,
        broker    VARCHAR
    );

CREATE TABLE IF NOT EXISTS positions (
        date   DATE NOT NULL,
        ticker VARCHAR NOT NULL,
        qty    DOUBLE PRECISION,
        avg_cost DOUBLE PRECISION,
        market_value DOUBLE PRECISION,
        PRIMARY KEY (date, ticker)
    );

CREATE TABLE IF NOT EXISTS nav (
        date  DATE PRIMARY KEY,
        nav   DOUBLE PRECISION NOT NULL,
        cash  DOUBLE PRECISION,
        gross_long DOUBLE PRECISION,
        gross_short DOUBLE PRECISION
    );

CREATE TABLE IF NOT EXISTS quality_log (
        run_id    VARCHAR NOT NULL,
        ts        TIMESTAMP NOT NULL,
        check_name VARCHAR NOT NULL,
        severity  VARCHAR NOT NULL,     -- 'info' | 'warn' | 'block'
        passed    BOOLEAN NOT NULL,
        detail    VARCHAR
    );

CREATE TABLE IF NOT EXISTS run_log (
        run_id    VARCHAR PRIMARY KEY,
        job       VARCHAR NOT NULL,
        started_at TIMESTAMP NOT NULL,
        ended_at  TIMESTAMP,
        status    VARCHAR,            -- 'ok' | 'warn' | 'fail'
        rows_written INTEGER,
        warnings  VARCHAR
    );
