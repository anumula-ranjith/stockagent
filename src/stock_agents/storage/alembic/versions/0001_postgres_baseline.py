"""Create the PostgreSQL baseline, or register an existing SQL bootstrap."""

from alembic import op

from stock_agents.common.config import project_root

revision = "0001_postgres_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute((project_root() / "scripts/sql/init.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    """Baseline removal never drops warehouse tables."""
