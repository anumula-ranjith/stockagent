"""DuckDB schema. Every table defined here, with a single idempotent
`init_schema(conn)` that creates anything missing without touching data.

Point-in-time columns are first-class: every fact table has `effective_date`
(the date the row describes) and `known_date` (the first date it could have
been known). Agents only read where `known_date <= t`.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from stock_agents.common import config as _config
from stock_agents.common.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Table:
    name: str
    ddl: str
    indexes: tuple[str, ...] = ()


# -- Reference ---------------------------------------------------------------

SYMBOLOGY = Table(
    "symbology",
    """CREATE TABLE IF NOT EXISTS symbology (
        ticker       VARCHAR  NOT NULL,
        eodhd_symbol VARCHAR,
        factset_id   VARCHAR,
        isin         VARCHAR,
        cusip        VARCHAR,
        active       BOOLEAN  NOT NULL DEFAULT TRUE,
        updated_at   TIMESTAMP,
        PRIMARY KEY (ticker)
    )""",
)

INDEX_MEMBERSHIP = Table(
    "index_membership",
    """CREATE TABLE IF NOT EXISTS index_membership (
        index_code   VARCHAR  NOT NULL,
        ticker       VARCHAR  NOT NULL,
        joined_on    DATE     NOT NULL,
        left_on      DATE,
        known_on     DATE     NOT NULL,
        PRIMARY KEY (index_code, ticker, joined_on)
    )""",
)

CLASSIFICATION = Table(
    "classification",
    """CREATE TABLE IF NOT EXISTS classification (
        ticker         VARCHAR  NOT NULL,
        effective_date DATE     NOT NULL,
        known_date     DATE     NOT NULL,
        sector         VARCHAR,
        industry       VARCHAR,
        source         VARCHAR,
        PRIMARY KEY (ticker, effective_date, source)
    )""",
)

# -- Market data -------------------------------------------------------------

PRICES_DAILY = Table(
    "prices_daily",
    """CREATE TABLE IF NOT EXISTS prices_daily (
        ticker     VARCHAR  NOT NULL,
        date       DATE     NOT NULL,
        open       DOUBLE,
        high       DOUBLE,
        low        DOUBLE,
        close      DOUBLE,
        adj_close  DOUBLE,
        volume     BIGINT,
        source     VARCHAR,
        known_date DATE     NOT NULL,
        PRIMARY KEY (ticker, date, source)
    )""",
    indexes=("CREATE INDEX IF NOT EXISTS idx_prices_date ON prices_daily(date)",),
)

CORPORATE_ACTIONS = Table(
    "corporate_actions",
    """CREATE TABLE IF NOT EXISTS corporate_actions (
        ticker      VARCHAR NOT NULL,
        action_type VARCHAR NOT NULL,     -- 'split' | 'dividend' | 'spinoff'
        ex_date     DATE    NOT NULL,
        value       DOUBLE,
        source      VARCHAR,
        known_date  DATE    NOT NULL,
        PRIMARY KEY (ticker, action_type, ex_date, source)
    )""",
)

# -- Fundamentals & estimates -----------------------------------------------

FUNDAMENTALS_PIT = Table(
    "fundamentals_pit",
    """CREATE TABLE IF NOT EXISTS fundamentals_pit (
        ticker         VARCHAR NOT NULL,
        metric         VARCHAR NOT NULL,
        fiscal_period  VARCHAR NOT NULL,   -- e.g. '2024Q3'
        value          DOUBLE,
        effective_date DATE    NOT NULL,   -- fiscal period end
        known_date     DATE    NOT NULL,   -- filing/report date
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, metric, fiscal_period, source)
    )""",
    indexes=("CREATE INDEX IF NOT EXISTS idx_fund_known ON fundamentals_pit(ticker, known_date)",),
)

ESTIMATES_PIT = Table(
    "estimates_pit",
    """CREATE TABLE IF NOT EXISTS estimates_pit (
        ticker         VARCHAR NOT NULL,
        metric         VARCHAR NOT NULL,   -- 'eps_ntm' | 'eps_fy1' | 'rev_ntm' | ...
        value          DOUBLE,
        n_analysts     INTEGER,
        effective_date DATE NOT NULL,      -- estimate_date
        known_date     DATE NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, metric, effective_date, source)
    )""",
)

ANALYST_PIT = Table(
    "analyst_pit",
    """CREATE TABLE IF NOT EXISTS analyst_pit (
        ticker         VARCHAR NOT NULL,
        rating_mean    DOUBLE,
        target_mean    DOUBLE,
        n_analysts     INTEGER,
        effective_date DATE NOT NULL,
        known_date     DATE NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, effective_date, source)
    )""",
)

EARNINGS_SURPRISE = Table(
    "earnings_surprise",
    """CREATE TABLE IF NOT EXISTS earnings_surprise (
        ticker         VARCHAR NOT NULL,
        fiscal_period  VARCHAR NOT NULL,
        eps_reported   DOUBLE,
        eps_estimate   DOUBLE,
        surprise_pct   DOUBLE,
        report_date    DATE NOT NULL,
        known_date     DATE NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, fiscal_period, source)
    )""",
)

EVENTS_CALENDAR = Table(
    "events_calendar",
    """CREATE TABLE IF NOT EXISTS events_calendar (
        ticker       VARCHAR NOT NULL,
        event_type   VARCHAR NOT NULL,   -- 'earnings' | 'conference' | ...
        event_date   DATE    NOT NULL,
        time_of_day  VARCHAR,            -- 'BMO' | 'AMC' | NULL
        fiscal_period VARCHAR,
        known_date   DATE    NOT NULL,
        source       VARCHAR NOT NULL,
        PRIMARY KEY (ticker, event_type, event_date, source)
    )""",
)

# -- News, sentiment, ownership ---------------------------------------------

NEWS = Table(
    "news",
    """CREATE TABLE IF NOT EXISTS news (
        news_id      VARCHAR PRIMARY KEY,
        ticker       VARCHAR NOT NULL,
        published_at TIMESTAMP NOT NULL,
        source       VARCHAR,
        headline     VARCHAR,
        url          VARCHAR,
        polarity     DOUBLE,             -- -1..+1 from source if given
        pos          DOUBLE,
        neg          DOUBLE,
        neu          DOUBLE,
        known_date   DATE NOT NULL
    )""",
    indexes=("CREATE INDEX IF NOT EXISTS idx_news_tk_dt ON news(ticker, published_at)",),
)

SENTIMENT_DAILY = Table(
    "sentiment_daily",
    """CREATE TABLE IF NOT EXISTS sentiment_daily (
        ticker         VARCHAR NOT NULL,
        effective_date DATE    NOT NULL,
        polarity       DOUBLE,
        n_headlines    INTEGER,
        source         VARCHAR NOT NULL,
        known_date     DATE    NOT NULL,
        PRIMARY KEY (ticker, effective_date, source)
    )""",
)

INSIDER_TX = Table(
    "insider_tx",
    """CREATE TABLE IF NOT EXISTS insider_tx (
        tx_id        VARCHAR PRIMARY KEY,
        ticker       VARCHAR NOT NULL,
        tx_date      DATE    NOT NULL,
        tx_type      VARCHAR,           -- 'P'/'S' etc.
        shares       DOUBLE,
        price        DOUBLE,
        value_usd    DOUBLE,
        insider_role VARCHAR,
        known_date   DATE    NOT NULL,
        source       VARCHAR NOT NULL
    )""",
)

INST_OWNERSHIP = Table(
    "inst_ownership",
    """CREATE TABLE IF NOT EXISTS inst_ownership (
        ticker         VARCHAR NOT NULL,
        effective_date DATE    NOT NULL,   -- 13F period end
        inst_holders   INTEGER,
        inst_pct_owned DOUBLE,
        known_date     DATE    NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, effective_date, source)
    )""",
)

SHORT_INTEREST = Table(
    "short_interest",
    """CREATE TABLE IF NOT EXISTS short_interest (
        ticker         VARCHAR NOT NULL,
        settlement_date DATE   NOT NULL,
        short_shares   BIGINT,
        short_pct_float DOUBLE,
        days_to_cover  DOUBLE,
        known_date     DATE NOT NULL,    -- FINRA publication date
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, settlement_date, source)
    )""",
)

SOCIAL_DAILY = Table(
    "social_daily",
    """CREATE TABLE IF NOT EXISTS social_daily (
        ticker         VARCHAR NOT NULL,
        effective_date DATE    NOT NULL,
        mentions       INTEGER,
        avg_sentiment  DOUBLE,
        known_date     DATE    NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (ticker, effective_date, source)
    )""",
)

# -- Macro ------------------------------------------------------------------

MACRO = Table(
    "macro",
    """CREATE TABLE IF NOT EXISTS macro (
        series_id      VARCHAR NOT NULL,   -- 'DGS3MO' | 'VIXCLS' | ...
        effective_date DATE    NOT NULL,
        value          DOUBLE,
        known_date     DATE    NOT NULL,
        source         VARCHAR NOT NULL,
        PRIMARY KEY (series_id, effective_date, source)
    )""",
)

# -- Agent outputs ----------------------------------------------------------

FACTOR_VALUES = Table(
    "factor_values",
    """CREATE TABLE IF NOT EXISTS factor_values (
        date     DATE    NOT NULL,
        ticker   VARCHAR NOT NULL,
        agent    VARCHAR NOT NULL,   -- 'technical' | 'momentum' | ...
        factor   VARCHAR NOT NULL,
        raw      DOUBLE,
        score    DOUBLE,
        imputed  BOOLEAN,
        PRIMARY KEY (date, ticker, agent, factor)
    )""",
)

AGENT_SCORES = Table(
    "agent_scores",
    """CREATE TABLE IF NOT EXISTS agent_scores (
        date    DATE    NOT NULL,
        ticker  VARCHAR NOT NULL,
        agent   VARCHAR NOT NULL,
        score   DOUBLE,
        passes  BOOLEAN,
        PRIMARY KEY (date, ticker, agent)
    )""",
)

SIGNALS = Table(
    "signals",
    """CREATE TABLE IF NOT EXISTS signals (
        date       DATE    NOT NULL,
        ticker     VARCHAR NOT NULL,
        side       VARCHAR NOT NULL,   -- 'long' | 'short'
        composite  DOUBLE,
        tech       DOUBLE,
        sent       DOUBLE,
        mom        DOUBLE,
        fund       DOUBLE,
        rank       INTEGER,
        reasons    VARCHAR,
        PRIMARY KEY (date, ticker, side)
    )""",
)

TARGET_WEIGHTS = Table(
    "target_weights",
    """CREATE TABLE IF NOT EXISTS target_weights (
        date   DATE    NOT NULL,
        ticker VARCHAR NOT NULL,
        weight DOUBLE  NOT NULL,
        PRIMARY KEY (date, ticker)
    )""",
)

# -- Execution --------------------------------------------------------------

ORDERS = Table(
    "orders",
    """CREATE TABLE IF NOT EXISTS orders (
        order_id   VARCHAR PRIMARY KEY,
        date       DATE    NOT NULL,
        ticker     VARCHAR NOT NULL,
        side       VARCHAR NOT NULL,       -- 'buy' | 'sell' | 'short' | 'cover'
        qty        DOUBLE  NOT NULL,
        type       VARCHAR,
        status     VARCHAR,
        submitted_at TIMESTAMP,
        broker     VARCHAR
    )""",
)

FILLS = Table(
    "fills",
    """CREATE TABLE IF NOT EXISTS fills (
        fill_id   VARCHAR PRIMARY KEY,
        order_id  VARCHAR NOT NULL,
        ticker    VARCHAR NOT NULL,
        side      VARCHAR NOT NULL,
        qty       DOUBLE  NOT NULL,
        price     DOUBLE,
        filled_at TIMESTAMP,
        broker    VARCHAR
    )""",
)

POSITIONS = Table(
    "positions",
    """CREATE TABLE IF NOT EXISTS positions (
        date   DATE NOT NULL,
        ticker VARCHAR NOT NULL,
        qty    DOUBLE,
        avg_cost DOUBLE,
        market_value DOUBLE,
        PRIMARY KEY (date, ticker)
    )""",
)

NAV = Table(
    "nav",
    """CREATE TABLE IF NOT EXISTS nav (
        date  DATE PRIMARY KEY,
        nav   DOUBLE NOT NULL,
        cash  DOUBLE,
        gross_long DOUBLE,
        gross_short DOUBLE
    )""",
)

# -- Operational ------------------------------------------------------------

QUALITY_LOG = Table(
    "quality_log",
    """CREATE TABLE IF NOT EXISTS quality_log (
        run_id    VARCHAR NOT NULL,
        ts        TIMESTAMP NOT NULL,
        check_name VARCHAR NOT NULL,
        severity  VARCHAR NOT NULL,     -- 'info' | 'warn' | 'block'
        passed    BOOLEAN NOT NULL,
        detail    VARCHAR
    )""",
)

RUN_LOG = Table(
    "run_log",
    """CREATE TABLE IF NOT EXISTS run_log (
        run_id    VARCHAR PRIMARY KEY,
        job       VARCHAR NOT NULL,
        started_at TIMESTAMP NOT NULL,
        ended_at  TIMESTAMP,
        status    VARCHAR,            -- 'ok' | 'warn' | 'fail'
        rows_written INTEGER,
        warnings  VARCHAR
    )""",
)

ALL_TABLES: tuple[Table, ...] = (
    SYMBOLOGY,
    INDEX_MEMBERSHIP,
    CLASSIFICATION,
    PRICES_DAILY,
    CORPORATE_ACTIONS,
    FUNDAMENTALS_PIT,
    ESTIMATES_PIT,
    ANALYST_PIT,
    EARNINGS_SURPRISE,
    EVENTS_CALENDAR,
    NEWS,
    SENTIMENT_DAILY,
    INSIDER_TX,
    INST_OWNERSHIP,
    SHORT_INTEREST,
    SOCIAL_DAILY,
    MACRO,
    FACTOR_VALUES,
    AGENT_SCORES,
    SIGNALS,
    TARGET_WEIGHTS,
    ORDERS,
    FILLS,
    POSITIONS,
    NAV,
    QUALITY_LOG,
    RUN_LOG,
)


def connect(path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Open the warehouse. Defaults to settings.paths.duckdb."""
    if path is None:
        path = str(_config.load_settings().paths.duckdb)
    return duckdb.connect(path)


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create every table if missing, plus declared indexes. Idempotent."""
    for t in ALL_TABLES:
        conn.execute(t.ddl)
        for idx in t.indexes:
            conn.execute(idx)
    log.info("schema ready: %d tables", len(ALL_TABLES))


def list_tables(conn: duckdb.DuckDBPyConnection) -> list[str]:
    rows = conn.execute("SELECT table_name FROM information_schema.tables").fetchall()
    return sorted(r[0] for r in rows)
