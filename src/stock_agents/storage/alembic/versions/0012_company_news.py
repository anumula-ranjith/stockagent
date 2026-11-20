"""Independent NSE company news and durable source coverage."""
from alembic import op
revision = "0012_company_news"
down_revision = "0011_angel_exchange_trade_at"
branch_labels = depends_on = None

def upgrade():
    op.execute("""
    CREATE TABLE news_companies (
      symbol TEXT PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL,
      isin TEXT, instrument_ticker TEXT REFERENCES symbology(ticker),
      aliases JSONB NOT NULL DEFAULT '[]', updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
    CREATE TABLE news_items (
      id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('headline','announcement')),
      source TEXT NOT NULL, source_key TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
      published_at TIMESTAMPTZ NOT NULL, ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(source,source_key));
    CREATE INDEX news_items_publication ON news_items(published_at DESC,id DESC);
    CREATE TABLE news_item_companies (
      news_item_id BIGINT REFERENCES news_items(id) ON DELETE CASCADE,
      symbol TEXT REFERENCES news_companies(symbol), PRIMARY KEY(news_item_id,symbol));
    CREATE INDEX news_company_filter ON news_item_companies(symbol,news_item_id);
    CREATE TABLE company_news_coverage (
      source TEXT NOT NULL, day DATE NOT NULL, status TEXT NOT NULL,
      checked_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_success TIMESTAMPTZ,
      item_count INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(source,day));
    """)

def downgrade():
    for table in ('company_news_coverage','news_item_companies','news_items','news_companies'):
        op.drop_table(table)
