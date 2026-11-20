"""Add identity mapping, privileged action audit, and durable job payloads."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_authentication"
down_revision = "0001_postgres_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "hashed_pwd", existing_type=sa.String(), nullable=True)
    op.add_column("users", sa.Column("clerk_subject", sa.String()))
    op.create_unique_constraint("users_clerk_subject_key", "users", ["clerk_subject"])
    op.create_index("uq_users_normalized_email", "users", [sa.text("lower(email)")], unique=True)
    op.add_column("job_runs", sa.Column("payload", JSONB()))
    op.add_column("job_runs", sa.Column("result_data", JSONB()))
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("ip", sa.String()),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_hash", sa.String(64), nullable=False),
    )
    op.create_index("idx_audit_log_action", "audit_log", ["action"])


def downgrade() -> None:
    op.alter_column("users", "hashed_pwd", existing_type=sa.String(), nullable=False)
    op.drop_table("audit_log")
    op.drop_column("job_runs", "result_data")
    op.drop_column("job_runs", "payload")
    op.drop_index("uq_users_normalized_email", table_name="users")
    op.drop_column("users", "clerk_subject")
