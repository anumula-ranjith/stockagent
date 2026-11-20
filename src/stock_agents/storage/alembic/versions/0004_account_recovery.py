"""Public email verification and password recovery with revocable sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0004_account_recovery"
down_revision = "0003_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Previously provisioned accounts retain their access.
    op.add_column(
        "users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "account_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_table("account_tokens")
    op.drop_column("users", "session_version")
    op.drop_column("users", "email_verified")
