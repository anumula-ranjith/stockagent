"""Store the NSE short-selling report separately from short interest."""

import sqlalchemy as sa
from alembic import op

revision = "0009_nse_short_selling"
down_revision = "0008_nse_insider_values"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nse_short_selling",
        sa.Column("ticker", sa.String(), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("known_date", sa.Date(), primary_key=True),
        sa.Column("short_quantity", sa.BigInteger(), nullable=False),
        sa.Column("traded_quantity", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("nse_short_selling")
