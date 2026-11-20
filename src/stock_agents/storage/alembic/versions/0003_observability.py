"""Persist job correlation and cumulative execution metrics."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_observability"
down_revision = "0002_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_runs", sa.Column("request_id", sa.String(64)))
    op.add_column("job_runs", sa.Column("trace_context", JSONB()))
    op.create_table(
        "job_metrics",
        sa.Column("job_type", sa.String(), primary_key=True),
        sa.Column("outcome", sa.String(), primary_key=True),
        sa.Column("executions", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Double(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_metrics")
    op.drop_column("job_runs", "trace_context")
    op.drop_column("job_runs", "request_id")
