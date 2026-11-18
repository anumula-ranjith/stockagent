"""Register the PostgreSQL schema bootstrapped by scripts/sql/init.sql."""

revision = "0001_postgres_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """The schema already exists before this baseline is stamped."""


def downgrade() -> None:
    """Baseline removal never drops warehouse tables."""
