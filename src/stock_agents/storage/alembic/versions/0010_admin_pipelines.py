"""Durable Celery pipeline administration, separate from RQ jobs."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "0010_admin_pipelines"
down_revision = "0009_nse_short_selling"
branch_labels = depends_on = None


def upgrade():
    op.create_table("pipeline_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pipeline", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("trigger", sa.String(24), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid(as_uuid=False), sa.ForeignKey("users.id")),
        sa.Column("parent_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("stages", JSONB(), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text()))
    op.create_index("pipeline_runs_created_idx", "pipeline_runs", ["created_at"])
    op.create_table("pipeline_schedules",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.execute("INSERT INTO pipeline_schedules VALUES ('morning','Morning catch-up',7,0,true),('evening','After-close update',18,30,true)")


def downgrade():
    op.drop_table("pipeline_schedules")
    op.drop_table("pipeline_runs")
