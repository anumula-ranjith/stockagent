"""Separate short-sale disclosures, outstanding estimates, buzz and public posts."""

from alembic import op

revision = "0014_market_signals"
down_revision = "0013_free_news_sentiment"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE research_universe_snapshots (
      id TEXT PRIMARY KEY, observed_on DATE NOT NULL, retrieved_at TIMESTAMPTZ NOT NULL,
      source_url TEXT NOT NULL, content_hash TEXT NOT NULL, constituent_count INTEGER NOT NULL,
      UNIQUE(observed_on,content_hash));
    CREATE TABLE research_universe_members (
      snapshot_id TEXT REFERENCES research_universe_snapshots(id),
      ticker TEXT REFERENCES symbology(ticker),company_name TEXT NOT NULL,isin TEXT NOT NULL,series TEXT NOT NULL,
      PRIMARY KEY(snapshot_id,ticker));
    CREATE TABLE market_signal_runs (
      id TEXT PRIMARY KEY,source TEXT NOT NULL,ticker TEXT,start_date DATE NOT NULL,end_date DATE NOT NULL,
      snapshot_id TEXT REFERENCES research_universe_snapshots(id),
      membership_basis TEXT NOT NULL DEFAULT 'current_snapshot_backfill',status TEXT NOT NULL,
      started_at TIMESTAMPTZ NOT NULL,finished_at TIMESTAMPTZ,rows_fetched INTEGER NOT NULL DEFAULT 0,
      rows_inserted INTEGER NOT NULL DEFAULT 0,rows_updated INTEGER NOT NULL DEFAULT 0,
      reason TEXT NOT NULL DEFAULT '',details JSONB NOT NULL DEFAULT '{}');
    CREATE INDEX market_signal_run_lookup ON market_signal_runs(source,start_date,end_date,started_at DESC);
    CREATE TABLE short_sale_observations (
      ticker TEXT REFERENCES symbology(ticker),trade_date DATE,short_sale_shares BIGINT NOT NULL CHECK(short_sale_shares>=0),
      source TEXT NOT NULL DEFAULT 'NSE historical short selling',retrieved_at TIMESTAMPTZ NOT NULL,
      run_id TEXT NOT NULL REFERENCES market_signal_runs(id),PRIMARY KEY(ticker,trade_date));
    CREATE TABLE short_interest_estimates (
      ticker TEXT REFERENCES symbology(ticker),observation_date DATE,source TEXT NOT NULL DEFAULT 'ORTEX',
      short_interest_shares DOUBLE PRECISION CHECK(short_interest_shares>=0 AND short_interest_shares<'Infinity'::float8),
      short_interest_pct_free_float DOUBLE PRECISION CHECK(short_interest_pct_free_float>=0 AND short_interest_pct_free_float<'Infinity'::float8),
      retrieved_at TIMESTAMPTZ NOT NULL,run_id TEXT NOT NULL REFERENCES market_signal_runs(id),
      CHECK(short_interest_shares IS NOT NULL OR short_interest_pct_free_float IS NOT NULL),
      PRIMARY KEY(ticker,observation_date,source));
    CREATE TABLE publisher_buzz (
      news_item_id BIGINT PRIMARY KEY REFERENCES news_items(id),rule_version TEXT NOT NULL,
      retrieved_at TIMESTAMPTZ NOT NULL,run_id TEXT NOT NULL REFERENCES market_signal_runs(id));
    CREATE TABLE publisher_buzz_companies (
      news_item_id BIGINT REFERENCES publisher_buzz(news_item_id),ticker TEXT REFERENCES symbology(ticker),
      PRIMARY KEY(news_item_id,ticker));
    CREATE INDEX publisher_buzz_ticker ON publisher_buzz_companies(ticker,news_item_id);
    CREATE TABLE public_social_posts (
      hn_item_id BIGINT PRIMARY KEY,title TEXT NOT NULL,discussion_url TEXT NOT NULL,published_at TIMESTAMPTZ NOT NULL,
      points INTEGER CHECK(points>=0),comment_count INTEGER CHECK(comment_count>=0),
      retrieved_at TIMESTAMPTZ NOT NULL,engagement_observed_at TIMESTAMPTZ NOT NULL,
      run_id TEXT NOT NULL REFERENCES market_signal_runs(id));
    CREATE INDEX public_social_publication ON public_social_posts(published_at DESC,hn_item_id);
    CREATE TABLE public_social_post_companies (
      hn_item_id BIGINT REFERENCES public_social_posts(hn_item_id),ticker TEXT REFERENCES symbology(ticker),
      PRIMARY KEY(hn_item_id,ticker));
    CREATE INDEX public_social_ticker ON public_social_post_companies(ticker,hn_item_id);
    """)


def downgrade():
    for table in (
        "public_social_post_companies",
        "public_social_posts",
        "publisher_buzz_companies",
        "publisher_buzz",
        "short_interest_estimates",
        "short_sale_observations",
        "market_signal_runs",
        "research_universe_members",
        "research_universe_snapshots",
    ):
        op.drop_table(table)
