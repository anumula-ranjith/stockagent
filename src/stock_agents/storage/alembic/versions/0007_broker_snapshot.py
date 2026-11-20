"""Read-only broker snapshots without persisting login secrets."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_broker_snapshot"
down_revision = "0006_portfolios_watchlists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_snapshots",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("broker", sa.String(30), primary_key=True),
        sa.Column("account_mask", sa.String(12), nullable=False),
        sa.Column("holdings", JSONB(), nullable=False),
        sa.Column("trades", JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("broker_snapshots")
