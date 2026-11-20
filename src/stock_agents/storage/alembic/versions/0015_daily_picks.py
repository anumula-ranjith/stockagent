"""Private daily paper portfolios and their scheduled ranking settings."""
from alembic import op

revision = "0015_daily_picks"
down_revision = "0014_market_signals"
branch_labels = depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE daily_pick_schedules (
            user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            starts_on date NOT NULL, config jsonb NOT NULL
        );
        CREATE TABLE daily_pick_batches (
            user_id uuid REFERENCES users(id) ON DELETE CASCADE,
            signal_date date NOT NULL, config jsonb NOT NULL, book jsonb NOT NULL,
            origin text NOT NULL, saved_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, signal_date)
        )
    """)


def downgrade():
    op.drop_table("daily_pick_batches")
    op.drop_table("daily_pick_schedules")
