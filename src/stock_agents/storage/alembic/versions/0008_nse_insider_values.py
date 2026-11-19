"""Store INR values and revision dates for NSE insider trades."""

import sqlalchemy as sa
from alembic import op

revision = "0008_nse_insider_values"
down_revision = "0007_broker_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insider_tx", sa.Column("value_inr", sa.Double()))
    op.add_column("insider_tx", sa.Column("superseded_on", sa.Date()))


def downgrade() -> None:
    op.drop_column("insider_tx", "superseded_on")
    op.drop_column("insider_tx", "value_inr")
