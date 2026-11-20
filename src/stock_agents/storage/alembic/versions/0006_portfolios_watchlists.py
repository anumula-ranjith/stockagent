"""User-owned manual portfolios and watchlists."""

import sqlalchemy as sa
from alembic import op

revision = "0006_portfolios_watchlists"
down_revision = "0005_company_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_portfolio_accounts_user_id", "portfolio_accounts", ["user_id"])
    op.create_table(
        "portfolio_entries",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("portfolio_id", sa.Uuid(), sa.ForeignKey("portfolio_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("ticker", sa.String(), sa.ForeignKey("symbology.ticker")),
        sa.Column("quantity", sa.Numeric(20, 6)),
        sa.Column("price", sa.Numeric(20, 4)),
        sa.Column("fees", sa.Numeric(20, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("amount", sa.Numeric(20, 4)),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("kind IN ('deposit','withdrawal','buy','sell')", name="ck_portfolio_entry_kind"),
        sa.CheckConstraint("fees >= 0", name="ck_portfolio_entry_fees"),
        sa.CheckConstraint("(kind IN ('buy','sell') AND ticker IS NOT NULL AND quantity > 0 AND price > 0 AND amount IS NULL) OR (kind IN ('deposit','withdrawal') AND ticker IS NULL AND quantity IS NULL AND price IS NULL AND amount > 0 AND fees = 0)", name="ck_portfolio_entry_shape"),
    )
    op.create_index("ix_portfolio_entries_portfolio_id", "portfolio_entries", ["portfolio_id"])
    op.create_index("ix_portfolio_entries_order", "portfolio_entries", ["portfolio_id", "trade_date", "created_at"])
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])
    op.create_table(
        "watchlist_items",
        sa.Column("watchlist_id", sa.Uuid(), sa.ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ticker", sa.String(), sa.ForeignKey("symbology.ticker"), primary_key=True),
        sa.Column("note", sa.String(500)),
        sa.Column("target_above", sa.Numeric(20, 4)),
        sa.Column("target_below", sa.Numeric(20, 4)),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("target_above IS NULL OR target_above > 0", name="ck_watchlist_above"),
        sa.CheckConstraint("target_below IS NULL OR target_below > 0", name="ck_watchlist_below"),
    )


def downgrade() -> None:
    op.drop_table("watchlist_items")
    op.drop_index("ix_watchlists_user_id", table_name="watchlists")
    op.drop_table("watchlists")
    op.drop_index("ix_portfolio_entries_order", table_name="portfolio_entries")
    op.drop_index("ix_portfolio_entries_portfolio_id", table_name="portfolio_entries")
    op.drop_table("portfolio_entries")
    op.drop_index("ix_portfolio_accounts_user_id", table_name="portfolio_accounts")
    op.drop_table("portfolio_accounts")
