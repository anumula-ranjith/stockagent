"""Retain exchange-published company names with their security identifiers."""

import sqlalchemy as sa
from alembic import op

revision = "0005_company_reference"
down_revision = "0004_account_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_reference",
        sa.Column("ticker", sa.String(), sa.ForeignKey("symbology.ticker"), primary_key=True),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("isin", sa.String()),
        sa.Column("venue", sa.String(), nullable=False),
        sa.Column("series", sa.String()),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("company_reference")
