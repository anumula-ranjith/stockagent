"""Keep the exchange trade time of provisional Angel One prices."""

from alembic import op

revision = "0011_angel_exchange_trade_at"
down_revision = "0010_admin_pipelines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE prices_daily ADD COLUMN IF NOT EXISTS exchange_trade_at TIMESTAMPTZ")


def downgrade() -> None:
    op.drop_column("prices_daily", "exchange_trade_at")
