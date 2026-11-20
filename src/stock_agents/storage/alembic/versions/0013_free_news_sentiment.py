"""Versioned local financial headline sentiment; original stories remain intact."""
from alembic import op

revision = "0013_free_news_sentiment"
down_revision = "0012_company_news"
branch_labels = depends_on = None


def upgrade():
    op.execute("""CREATE TABLE company_news_sentiment (
      news_item_id BIGINT PRIMARY KEY REFERENCES news_items(id) ON DELETE CASCADE,
      model TEXT NOT NULL, title_hash TEXT NOT NULL, scored_at TIMESTAMPTZ NOT NULL,
      positive DOUBLE PRECISION NOT NULL CHECK(positive BETWEEN 0 AND 1),
      negative DOUBLE PRECISION NOT NULL CHECK(negative BETWEEN 0 AND 1),
      neutral DOUBLE PRECISION NOT NULL CHECK(neutral BETWEEN 0 AND 1),
      polarity DOUBLE PRECISION NOT NULL CHECK(polarity BETWEEN -1 AND 1),
      CHECK(abs(positive+negative+neutral-1)<0.001));"""
    )


def downgrade():
    op.drop_table("company_news_sentiment")
